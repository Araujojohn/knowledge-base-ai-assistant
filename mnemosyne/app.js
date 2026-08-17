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

function setStatus(text, state) {
  statusText.textContent = text;
  statusDot.className = "dot" + (state ? ` ${state}` : "");
}

// state: "" (idle) | "connecting" | "active" (connected, listening) | "thinking" (tool call in flight)
function setOrbState(state) {
  aiOrb.className = "orb-field" + (state ? ` ${state}` : "");
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

// Calls our own backend, which runs the LangGraph agent (RAG search included)
// and streams its response. send_message_to_ai() was built for the WhatsApp
// flow — it also yields "Pensando..." lines and raw tool-call summaries
// inline with the final answer, with no delimiter between chunks. We forward
// the full joined stream as the function's result for now; separating the
// noise from the final answer needs a backend change (structured chunks),
// which is out of scope here.
async function queryKnowledgeBase(request, liveLine) {
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
  let full = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    full += decoder.decode(value, { stream: true });
    liveLine.textContent = full;
  }
  return full;
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

  setOrbState("thinking");
  scheduleFade(addLine("tool", `Looking up: ${request}`), "tool");
  const liveLine = addLine("assistant", "");
  liveLine.innerHTML = '<span class="typing-dots"><i></i><i></i><i></i></span>';

  let output;
  try {
    output = await queryKnowledgeBase(request, liveLine);
  } catch (err) {
    output = `Lookup failed: ${err.message}`;
    liveLine.textContent = output;
  }
  scheduleFade(liveLine, "assistant");
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
    case "response.done": {
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
  if (dc) dc.close();
  if (pc) pc.close();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  dc = null;
  pc = null;
  micStream = null;
  micMuted = false;
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
