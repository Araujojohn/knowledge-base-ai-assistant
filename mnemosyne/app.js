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

function addLine(role, text) {
  const p = document.createElement("p");
  p.className = `line line-${role}`;
  p.textContent = text;
  transcriptEl.appendChild(p);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
  return p;
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
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }
  return full;
}

async function handleFunctionCall(name, callId, argsJson) {
  if (name !== KNOWLEDGE_BASE_TOOL) {
    addLine("error", `Unknown tool requested: ${name}`);
    return;
  }

  let request = "";
  try {
    request = JSON.parse(argsJson).request ?? "";
  } catch {
    request = argsJson;
  }

  addLine("tool", `Looking up: ${request}`);
  const liveLine = addLine("assistant", "…");

  let output;
  try {
    output = await queryKnowledgeBase(request, liveLine);
  } catch (err) {
    output = `Lookup failed: ${err.message}`;
    liveLine.textContent = output;
  }

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
      addLine("error", event.error?.message ?? "Unknown realtime error");
      break;
    default:
      break;
  }
}

async function connect() {
  connectBtn.disabled = true;
  setStatus("Connecting…", "connecting");

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
      connectBtn.textContent = "Disconnect";
      connectBtn.classList.add("active");
      connectBtn.disabled = false;
      micBtn.disabled = false;
      addLine("system", "Connected. Start talking.");
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
    addLine("error", err.message);
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
  micBtn.disabled = true;
}

function disconnect() {
  cleanup();
  setStatus("Idle", "");
  connectBtn.textContent = "Connect";
  connectBtn.classList.remove("active");
  connectBtn.disabled = false;
  addLine("system", "Disconnected.");
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
});
