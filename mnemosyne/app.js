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

// Transcript reads as floating captions, not a chat log: each line fades in,
// sticks around for a few seconds, then fades out on its own. Capped at
// MAX_LINES as a safety net in case several lines land faster than they fade.
const MAX_LINES = 3;
const LINE_HOLD_MS = { system: 4000, tool: 4000, assistant: 7000, error: 6000 };
const LINE_FADE_MS = 600;

function addLine(role, text) {
  const p = document.createElement("p");
  p.className = `line line-${role}`;
  p.textContent = text;
  transcriptEl.appendChild(p);
  while (transcriptEl.children.length > MAX_LINES) {
    transcriptEl.firstElementChild.remove();
  }
  return p;
}

// Call once a line's final content is set — starts its fade-out countdown.
// Kept separate from addLine() because the "assistant" line is created early
// (to show the typing dots) and keeps being rewritten while streaming; it
// should only start counting down once the real answer lands.
function scheduleFade(el, role) {
  setTimeout(() => {
    if (!el.isConnected) return;
    el.classList.add("line-out");
    setTimeout(() => el.remove(), LINE_FADE_MS);
  }, LINE_HOLD_MS[role] ?? 5000);
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
async function queryKnowledgeBase(request, liveLine, onProgress) {
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
      liveLine.textContent = finalAnswer;
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
    scheduleFade(addLine("error", `Unknown tool requested: ${name}`), "error");
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
  scheduleFade(addLine("tool", `Working on: ${request}`), "tool");
  const liveLine = addLine("assistant", "");
  liveLine.innerHTML = '<span class="typing-dots"><i></i><i></i><i></i></span>';

  // Relay every tool the agent calls along the way into the Realtime
  // conversation as it happens, without forcing a response (no
  // response.create) — the model picks it up on its own next turn. The
  // "[AGENT PROGRESS]" tag is explained once in openai_realtimeapi_prompt,
  // not repeated per message — a run with many tool calls would otherwise
  // resend the same paragraph of framing over and over. Not always a
  // lookup — the underlying agent can also write/save on request.
  const sendProgressNote = (toolCallText) => {
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
    output = await queryKnowledgeBase(request, liveLine, sendProgressNote);
  } catch (err) {
    output = `Lookup failed: ${err.message}`;
    liveLine.textContent = output;
  }
  scheduleFade(liveLine, "assistant");
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

function handleServerEvent(raw) {
  let event;
  try {
    event = JSON.parse(raw);
  } catch {
    return;
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
      scheduleFade(addLine("error", event.error?.message ?? "Unknown realtime error"), "error");
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
      scheduleFade(addLine("system", "Connected. Start talking."), "system");
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
    scheduleFade(addLine("error", err.message), "error");
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
  scheduleFade(addLine("system", "Disconnected."), "system");
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
