// Mnemosyne widget — browser-side WebRTC client for the OpenAI Realtime API.
//
// This page and every same-origin request it makes (including the fetch()
// calls below) sit behind HTTP Basic Auth, enforced server-side per route.
// The browser caches those credentials after the first prompt and resends
// them automatically on same-origin requests, so no token is handled here.

// Must match `openai_realtimeapi_tool_name` in prompts.py — this is the
// function name the Realtime session was configured to call.
const KNOWLEDGE_BASE_TOOL = "Knowledge_base";

const connectBtn = document.getElementById("connect-btn");
const micBtn = document.getElementById("mic-btn");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const transcriptEl = document.getElementById("transcript");
const remoteAudio = document.getElementById("remote-audio");
const aiOrb = document.getElementById("ai-orb");

let pc = null;
let dc = null;
let micStream = null;
let micMuted = false;
let sessionId = null;
let connected = false;
let toolCallInFlight = false;

// Bubble/element reserved per conversation item id, keyed at
// conversation.item.created time (true chronological order) so content
// that arrives later (transcription, streamed text) lands in the right
// spot instead of wherever it happened to finish. See handleServerEvent's
// "conversation.item.created" case.
const itemBubbles = new Map();

function setStatus(text, state) {
  statusText.textContent = text;
  statusDot.className = "dot" + (state ? ` ${state}` : "");
}

// state: "" (idle) | "connecting" | "active" (connected, listening)
//      | "thinking" (tool call in flight) | "speaking" (AI voice audio playing)
function setOrbState(state) {
  aiOrb.className = "orb-field" + (state ? ` ${state}` : "");
}

// Drives the orb's --speak-level from the real remote-audio volume (Web
// Audio AnalyserNode tapping the WebRTC track) while the AI is speaking —
// see startSpeakingAnalysis()/stopSpeakingAnalysis() below.
let audioCtx = null;
let analyser = null;
let levelData = null;
let speakingRaf = null;

function setupAudioAnalyser(stream) {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioCtx.createMediaStreamSource(stream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.6;
  source.connect(analyser); // not connected to destination — analysis only, no double playback
  levelData = new Uint8Array(analyser.frequencyBinCount);
}

function updateSpeakingLevel() {
  if (!analyser || !aiOrb.classList.contains("speaking")) {
    speakingRaf = null;
    return;
  }
  analyser.getByteFrequencyData(levelData);
  let sum = 0;
  for (let i = 0; i < levelData.length; i++) sum += levelData[i];
  aiOrb.style.setProperty("--speak-level", (sum / levelData.length / 255).toFixed(3));
  speakingRaf = requestAnimationFrame(updateSpeakingLevel);
}

function startSpeakingAnalysis() {
  setOrbState("speaking");
  if (audioCtx?.state === "suspended") audioCtx.resume();
  if (analyser && !speakingRaf) speakingRaf = requestAnimationFrame(updateSpeakingLevel);
}

function stopSpeakingAnalysis() {
  if (speakingRaf) cancelAnimationFrame(speakingRaf);
  speakingRaf = null;
  aiOrb.style.setProperty("--speak-level", "0");
  setOrbState(toolCallInFlight ? "thinking" : (connected ? "active" : ""));
}

// Transcript is a persistent conversation log (user/assistant bubbles +
// tool-activity pills), not floating captions — it scrolls internally
// instead of growing the page, which is also what stops a long raw agent
// answer from blowing out the card's layout. Only transient status notices
// (connected/disconnected/error) still fade — the conversation itself stays.
const STATUS_HOLD_MS = 5000;
const LINE_FADE_MS = 600;

function scrollTranscriptToBottom() {
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function addSystemLine(text, role = "system") {
  const p = document.createElement("p");
  p.className = `line-${role}`;
  p.textContent = text;
  transcriptEl.appendChild(p);
  scrollTranscriptToBottom();
  return p;
}

function scheduleFade(el) {
  setTimeout(() => {
    if (!el.isConnected) return;
    el.classList.add("line-out");
    setTimeout(() => el.remove(), LINE_FADE_MS);
  }, STATUS_HOLD_MS);
}

function addUserMessage(text) {
  const div = document.createElement("div");
  div.className = "msg msg-user";
  div.textContent = text;
  transcriptEl.appendChild(div);
  scrollTranscriptToBottom();
  return div;
}

// Returns the inner .msg-bubble — callers just keep setting .textContent
// on it as more of the answer streams in (see queryKnowledgeBase()/
// response.output_audio_transcript.delta below).
function addAssistantMessage() {
  const wrap = document.createElement("div");
  wrap.className = "msg msg-assistant";
  wrap.innerHTML =
    '<div class="msg-avatar"></div>' +
    '<div class="msg-bubble"><span class="typing-dots"><i></i><i></i><i></i></span></div>';
  transcriptEl.appendChild(wrap);
  scrollTranscriptToBottom();
  return wrap.querySelector(".msg-bubble");
}

// A tool call in flight, shown as a pulsing/shimmering pill. Click to expand
// what was asked of it — NOT the tool's actual return value: the backend
// stream (send_message_to_ai() in graph.py) only ever surfaces "this tool
// was called with these args", never what it handed back, so that's the
// most honest thing to show here without a backend change.
function addActivity(label) {
  const wrap = document.createElement("div");
  wrap.className = "activity";
  wrap.innerHTML =
    '<div class="activity-pill active">' +
    '<span class="activity-dot"></span>' +
    '<span class="activity-label"></span>' +
    '<span class="activity-chevron">&#9656;</span>' +
    "</div>" +
    '<div class="activity-detail"></div>';
  wrap.querySelector(".activity-label").textContent = label;
  wrap.querySelector(".activity-detail").textContent = label;
  wrap.querySelector(".activity-pill").addEventListener("click", () => wrap.classList.toggle("open"));
  transcriptEl.appendChild(wrap);
  scrollTranscriptToBottom();
  return wrap;
}

function finishActivity(wrap, ok) {
  const pill = wrap.querySelector(".activity-pill");
  pill.classList.remove("active");
  pill.classList.add(ok ? "done" : "error");
}

async function fetchEphemeralKey() {
  const res = await fetch("/realtime/new_session", { method: "POST" });
  if (!res.ok) {
    throw new Error(`new_session failed: ${res.status}`);
  }
  return await res.json();
}

// Calls our own backend, which runs the LangGraph agent (RAG search included).
// The backend streams NDJSON — one {"Type": ..., "content": ...} object per
// line (see send_message_to_ai() in graph.py). "final_aswer"/"error" chunks
// are the user-facing answer, shown here and returned as the function-call
// result. "thinking"/"tool_use" chunks are the agent's internal progress
// (covers every tool it calls along the way — search, read, write, ...) —
// not shown here, but forwarded live via onProgress so the caller can relay
// them to the Realtime API as it goes.
async function queryKnowledgeBase(request, bubble, onProgress) {
  const res = await fetch("/realtime/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: request, session_id: sessionId }),
  });
  if (!res.ok) {
    throw new Error(`query failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalAnswer = "";

  const consumeLine = (line) => {
    if (!line) return;
    let chunk;
    try {
      chunk = JSON.parse(line);
    } catch {
      return; // malformed/partial line — ignore rather than crash the stream
    }
    if (chunk.Type === "final_aswer" || chunk.Type === "error") {
      finalAnswer += chunk.content;
      bubble.textContent = finalAnswer;
      scrollTranscriptToBottom();
    } else if (chunk.Type === "tool_use") {
      // "thinking" chunks are dropped here — always the same "Pensando..."
      // filler (Portuguese, no real content); tool_use carries actual
      // signal (which tool, which args), worth relaying.
      onProgress?.(chunk.content);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // NDJSON lines don't line up with read() chunks — buffer until "\n"
    // and hold back whatever's left (may be a partial line) for next read.
    const lines = buffer.split("\n");
    buffer = lines.pop();
    lines.forEach(consumeLine);
  }
  consumeLine(buffer); // flush a final line with no trailing "\n", if any

  return finalAnswer;
}

async function handleFunctionCall(itemId, name, callId, argsJson) {
  if (name !== KNOWLEDGE_BASE_TOOL) {
    scheduleFade(addSystemLine(`Unknown tool requested: ${name}`, "error"));
    return;
  }

  let request = "";
  try {
    request = JSON.parse(argsJson).request ?? "";
  } catch {
    request = argsJson;
  }

  toolCallInFlight = true;
  setOrbState("thinking");
  // Reuse the bubble already reserved by conversation.item.created (correct
  // chronological slot) instead of appending a new one now — response.done
  // (which is what triggers this function) can fire well after the item
  // itself was created, so appending fresh here would land it after
  // messages that actually came later (see itemBubbles below).
  let bubble = itemBubbles.get(itemId);
  if (!bubble) bubble = addAssistantMessage();

  // One activity pill per tool the agent calls along the way — the backend
  // stream doesn't say when an individual tool call finishes, only when the
  // whole request does, so every pill opened during this call gets marked
  // done/error together at the end (see below), not one by one.
  const activities = [];

  // Relay every tool call into the Realtime conversation as it happens,
  // without forcing a response (no response.create) — the model picks it
  // up on its own next turn. The "[AGENT PROGRESS]" tag is explained once
  // in openai_realtimeapi_prompt, not repeated per message — a run with
  // many tool calls would otherwise resend the same paragraph of framing
  // over and over. Not always a lookup — the underlying agent can also
  // write/save on request.
  const sendProgressNote = (toolCallText) => {
    activities.push(addActivity(toolCallText));
    if (!dc || dc.readyState !== "open") return;
    dc.send(JSON.stringify({
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "system",
        content: [{ type: "input_text", text: `[AGENT PROGRESS] ${toolCallText}` }],
      },
    }));
  };

  let output;
  try {
    output = await queryKnowledgeBase(request, bubble, sendProgressNote);
    activities.forEach((a) => finishActivity(a, true));
  } catch (err) {
    output = `Lookup failed: ${err.message}`;
    bubble.textContent = output;
    activities.forEach((a) => finishActivity(a, false));
  }
  toolCallInFlight = false;
  setOrbState(connected ? "active" : "");

  if (!dc || dc.readyState !== "open") return;

  dc.send(JSON.stringify({
    type: "conversation.item.create",
    item: {
      type: "function_call_output",
      call_id: callId,
      output: JSON.stringify({ result: output }),
    },
  }));
  dc.send(JSON.stringify({ type: "response.create" }));
}

// response.output_audio_transcript.delta chunks arrive faster than the
// matching audio actually plays (text generation isn't paced to speech
// speed) — dumping each delta straight into .textContent made the words
// appear well ahead of the voice. Queue incoming text per-bubble and drip
// it out at roughly speaking pace (~14 chars/sec, close to average speech)
// instead, so the reveal tracks what's actually being said.
const TYPEWRITER_MS_PER_CHAR = 70;
function typewriterAppend(bubble, text) {
  bubble._twQueue = (bubble._twQueue ?? "") + text;
  if (bubble._twTimer) return; // already draining the queue
  bubble._twTimer = setInterval(() => {
    if (!bubble._twQueue) {
      clearInterval(bubble._twTimer);
      bubble._twTimer = null;
      return;
    }
    bubble.textContent += bubble._twQueue[0];
    bubble._twQueue = bubble._twQueue.slice(1);
    scrollTranscriptToBottom();
  }, TYPEWRITER_MS_PER_CHAR);
}

function handleServerEvent(raw) {
  let event;
  try {
    event = JSON.parse(raw);
  } catch {
    return;
  }

  // Temporary diagnostic: real arrival order/timing of these events is what
  // the bubble-ordering fix depends on — log it so a mis-ordered transcript
  // can be root-caused from the browser console (F12) instead of guessed at.
  if (["conversation.item.created", "conversation.item.input_audio_transcription.completed", "response.output_audio_transcript.delta", "response.output_audio_transcript.done", "response.done"].includes(event.type)) {
    console.log(`[EVT ${performance.now().toFixed(0)}ms]`, event.type, "item:", event.item?.id ?? event.item_id ?? "-", "role:", event.item?.role ?? "-");
  }

  switch (event.type) {
    // Fired when the model's spoken audio actually starts/stops playing —
    // distinct from response.done, which marks generation finishing, not
    // playback (the audio track can still be draining its buffer after).
    case "output_audio_buffer.started":
      startSpeakingAnalysis();
      break;
    case "output_audio_buffer.stopped":
    case "output_audio_buffer.cleared": // cleared on interruption/barge-in
      stopSpeakingAnalysis();
      break;

    // Fires the instant a turn starts — for a user turn, right when the
    // mic audio is committed (well before transcription finishes); for an
    // assistant turn, right when generation starts (before any text/audio
    // streams). This is what's actually in chronological order — reserve
    // the bubble's position here, content gets filled in by whichever
    // event below carries it, matched by item.id.
    case "conversation.item.created": {
      const item = event.item;
      if (!item) break;
      if (item.type === "message" && item.role === "user") {
        itemBubbles.set(item.id, addUserMessage("…"));
      } else if (item.type === "message" && item.role === "assistant") {
        itemBubbles.set(item.id, addAssistantMessage());
      } else if (item.type === "function_call") {
        itemBubbles.set(item.id, addAssistantMessage());
      }
      break;
    }

    // Requires audio.input.transcription set in the session config
    // (openai_realtime.py) — without it this event never fires. Often
    // arrives well after the item itself was created (separate, slower
    // pipeline) — fills the placeholder reserved above instead of
    // appending a new bubble at the (wrong, later) point it arrives.
    case "conversation.item.input_audio_transcription.completed": {
      if (!event.transcript) break;
      const bubble = itemBubbles.get(event.item_id);
      if (bubble) bubble.textContent = event.transcript;
      else addUserMessage(event.transcript); // fallback: item.created never seen
      scrollTranscriptToBottom();
      break;
    }

    // Text version of what the assistant is speaking, streamed incrementally
    // into the bubble reserved by conversation.item.created.
    case "response.output_audio_transcript.delta": {
      let bubble = itemBubbles.get(event.item_id);
      if (!bubble) {
        bubble = addAssistantMessage(); // fallback: item.created never seen
        itemBubbles.set(event.item_id, bubble);
      }
      typewriterAppend(bubble, event.delta);
      break;
    }
    case "response.done": {
      // Safety net: if the buffer events above never fired for some reason,
      // don't leave the orb stuck showing "speaking" forever.
      if (aiOrb.classList.contains("speaking")) stopSpeakingAnalysis();
      const output = event.response?.output ?? [];
      for (const item of output) {
        if (item.type === "function_call") {
          handleFunctionCall(item.id, item.name, item.call_id, item.arguments);
        }
      }
      break;
    }
    case "error":
      scheduleFade(addSystemLine(event.error?.message ?? "Unknown realtime error", "error"));
      break;
    default:
      break;
  }
}

async function connect() {
  connectBtn.disabled = true;
  setStatus("Connecting…", "connecting");
  setOrbState("connecting");

  try {
    sessionId = crypto.randomUUID();
    const ephemeralKey = await fetchEphemeralKey();

    pc = new RTCPeerConnection();
    pc.ontrack = (e) => {
      remoteAudio.srcObject = e.streams[0];
      setupAudioAnalyser(e.streams[0]);
    };

    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    micStream.getTracks().forEach((track) => pc.addTrack(track, micStream));

    dc = pc.createDataChannel("oai-events");
    dc.addEventListener("message", (e) => handleServerEvent(e.data));
    dc.addEventListener("open", () => {
      connected = true;
      setStatus("Connected", "connected");
      setOrbState("active");
      connectBtn.textContent = "Disconnect";
      connectBtn.classList.add("active");
      connectBtn.disabled = false;
      micBtn.disabled = false;
      micBtn.classList.add("listening");
      scheduleFade(addSystemLine("Connected. Start talking."));
    });
    dc.addEventListener("close", () => {
      if (connected) disconnect();
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    const sdpResponse = await fetch("https://api.openai.com/v1/realtime/calls", {
      method: "POST",
      body: offer.sdp,
      headers: {
        Authorization: `Bearer ${ephemeralKey}`,
        "Content-Type": "application/sdp",
      },
    });
    if (!sdpResponse.ok) {
      throw new Error(`realtime SDP exchange failed: ${sdpResponse.status}`);
    }

    await pc.setRemoteDescription({
      type: "answer",
      sdp: await sdpResponse.text(),
    });
  } catch (err) {
    setStatus(`Error: ${err.message}`, "error");
    scheduleFade(addSystemLine(err.message, "error"));
    cleanup();
    connectBtn.disabled = false;
  }
}

function cleanup() {
  connected = false;
  toolCallInFlight = false;
  if (dc) dc.close();
  if (pc) pc.close();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (speakingRaf) cancelAnimationFrame(speakingRaf);
  if (audioCtx) audioCtx.close();
  dc = null;
  pc = null;
  micStream = null;
  micMuted = false;
  audioCtx = null;
  analyser = null;
  levelData = null;
  speakingRaf = null;
  itemBubbles.clear();
  micBtn.textContent = "Mute";
  micBtn.classList.remove("muted");
  micBtn.classList.remove("listening");
  micBtn.disabled = true;
  setOrbState("");
}

function disconnect() {
  cleanup();
  setStatus("Idle", "");
  connectBtn.textContent = "Connect";
  connectBtn.classList.remove("active");
  connectBtn.disabled = false;
  scheduleFade(addSystemLine("Disconnected."));
}

connectBtn.addEventListener("click", () => {
  if (connected) {
    disconnect();
  } else {
    connect();
  }
});

micBtn.addEventListener("click", () => {
  if (!micStream) return;
  micMuted = !micMuted;
  micStream.getTracks().forEach((t) => (t.enabled = !micMuted));
  micBtn.textContent = micMuted ? "Unmute" : "Mute";
  micBtn.classList.toggle("muted", micMuted);
  micBtn.classList.toggle("listening", !micMuted);
});
