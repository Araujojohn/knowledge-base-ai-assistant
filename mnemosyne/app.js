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

// Bubble ordering: anchored on the most fundamental, longest-standing
// lifecycle events (VAD speech-start, response-created) instead of
// conversation.item.created — a fix built on that event didn't hold up in
// testing, so this drops the dependency entirely rather than guess again.
//
// User turns: pushed to a FIFO queue the instant speech starts (VAD),
// filled in (shifted off, in order) whenever a transcription completes —
// transcriptions finish in the same order their turns started, so a queue
// doesn't need item ids to stay correctly matched.
const pendingUserBubbles = [];
// Assistant turns: keyed by response_id, reserved the instant generation
// starts (response.created) — every later event carrying this turn's
// content (response.output_audio_transcript.delta, response.done) includes
// response_id, so this one's safe to key by id rather than a queue.
const responseBubbles = new Map();

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

// Only stick to the bottom if already close to it — called on every single
// typewriter tick (see below), so without this check it would fight anyone
// who scrolled up to reread something, yanking them back down constantly.
function scrollTranscriptToBottom() {
  const distanceFromBottom = transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight;
  if (distanceFromBottom < 80) transcriptEl.scrollTop = transcriptEl.scrollHeight;
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

async function handleFunctionCall(name, callId, argsJson) {
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
  // response.done (what triggers this) always fires after any spoken part
  // of the same response already streamed — appending here lands right
  // after that, which is correct DOM order for this response's own turn.
  const bubble = addAssistantMessage();

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

// response.output_audio_transcript.delta chunks aren't paced to match the
// audio's actual playback speed, so dumping each delta straight into
// .textContent could land well ahead of or behind the voice depending on
// how fast a given response happens to generate — a fixed guessed rate
// (tried 2 different ones) got one direction wrong each time. Self-adjusting
// instead: reveal at a brisk fixed pace normally, but if incoming text is
// piling up faster than that (backlog growing), reveal more per tick to
// catch up — bounds the worst-case lag instead of drifting arbitrarily far
// behind regardless of the true rate for this particular response/voice.
const TYPEWRITER_TICK_MS = 30;
const TYPEWRITER_CATCHUP_CHARS = 40; // backlog beyond this starts revealing >1 char/tick
function typewriterAppend(bubble, text) {
  bubble._twQueue = (bubble._twQueue ?? "") + text;
  if (bubble._twTimer) return; // already draining the queue
  bubble._twTimer = setInterval(() => {
    if (!bubble._twQueue) {
      clearInterval(bubble._twTimer);
      bubble._twTimer = null;
      return;
    }
    const chunkSize = Math.max(1, Math.ceil(bubble._twQueue.length / TYPEWRITER_CATCHUP_CHARS));
    bubble.textContent += bubble._twQueue.slice(0, chunkSize);
    bubble._twQueue = bubble._twQueue.slice(chunkSize);
    scrollTranscriptToBottom();
  }, TYPEWRITER_TICK_MS);
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
  if (["input_audio_buffer.speech_started", "conversation.item.input_audio_transcription.completed", "response.created", "response.output_audio_transcript.delta", "response.done"].includes(event.type)) {
    console.log(`[EVT ${performance.now().toFixed(0)}ms]`, event.type, "response:", event.response?.id ?? event.response_id ?? "-");
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

    // VAD fires this the instant it detects the user starting to talk —
    // long before transcription (a separate, slower pipeline) finishes.
    // Reserve the bubble's slot here so it lands in true chronological
    // order; content backfills whenever the transcript actually arrives.
    case "input_audio_buffer.speech_started":
      pendingUserBubbles.push(addUserMessage("…"));
      break;

    // Requires audio.input.transcription set in the session config
    // (openai_realtime.py) — without it this event never fires. Transcripts
    // complete in the same order their turns started, so the oldest pending
    // placeholder is always the right one to fill — no id matching needed.
    case "conversation.item.input_audio_transcription.completed": {
      if (!event.transcript) break;
      const bubble = pendingUserBubbles.shift();
      if (bubble) bubble.textContent = event.transcript;
      else addUserMessage(event.transcript); // fallback: nothing pending
      scrollTranscriptToBottom();
      break;
    }

    // Fires the instant the model starts generating a reply — reserve the
    // bubble here (before any audio/text exists yet) so it lands in the
    // right chronological slot regardless of how long generation takes.
    case "response.created":
      responseBubbles.set(event.response.id, addAssistantMessage());
      break;

    // Text version of what the assistant is speaking, streamed incrementally
    // into the bubble reserved by response.created.
    case "response.output_audio_transcript.delta": {
      let bubble = responseBubbles.get(event.response_id);
      if (!bubble) {
        bubble = addAssistantMessage(); // fallback: response.created never seen
        responseBubbles.set(event.response_id, bubble);
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
          handleFunctionCall(item.name, item.call_id, item.arguments);
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
  pendingUserBubbles.length = 0;
  responseBubbles.clear();
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
