// Mnemosyne widget — browser-side WebRTC client for the OpenAI Realtime API.
//
// This page and every same-origin request it makes (including the fetch()
// calls below) sit behind HTTP Basic Auth, enforced server-side per route.
// The browser caches those credentials after the first prompt and resends
// them automatically on same-origin requests, so no token is handled here.
//
// The transcript has two registers, and keeping them apart is the whole
// point of the rendering code below:
//   spoken  — what you said and what Mnemosyne said (blue bubbles)
//   recall  — a knowledge-base lookup: the request, the tools that ran, and
//             the raw text the LangGraph agent returned (purple lane)
// The agent's return used to be rendered as an assistant bubble, which read
// as Mnemosyne talking twice — once in raw agent prose, once in her own
// words. It is a tool result and is now presented as one.

// Must match `openai_realtimeapi_tool_name` in prompts.py — this is the
// function name the Realtime session was configured to call.
const KNOWLEDGE_BASE_TOOL = "Knowledge_base";

// Event-timing logging is opt-in (?debug=1) — it was load-bearing while the
// bubble-ordering fix was being worked out, useless noise the rest of the time.
const DEBUG = new URLSearchParams(location.search).has("debug");

const connectBtn = document.getElementById("connect-btn");
const connectLabel = document.getElementById("connect-label");
const micBtn = document.getElementById("mic-btn");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const transcriptEl = document.getElementById("transcript");
const transcriptInner = document.getElementById("transcript-inner");
const emptyState = document.getElementById("empty-state");
const remoteAudio = document.getElementById("remote-audio");
const aiOrb = document.getElementById("ai-orb");
const dockHint = document.getElementById("dock-hint");

const railEl = document.getElementById("rail");
const railScrim = document.getElementById("rail-scrim");
const menuBtn = document.getElementById("menu-btn");
const viewTitle = document.getElementById("view-title");
const viewSub = document.getElementById("view-sub");

const recallLog = document.getElementById("recall-log");
const recallLogEmpty = document.getElementById("recall-log-empty");
const recallCount = document.getElementById("recall-count");
const statUptime = document.getElementById("stat-uptime");
const statTurns = document.getElementById("stat-turns");
const statRecalls = document.getElementById("stat-recalls");
const metaState = document.getElementById("meta-state");
const metaSession = document.getElementById("meta-session");
const metaUptime = document.getElementById("meta-uptime");
const metaMic = document.getElementById("meta-mic");
const metaTurns = document.getElementById("meta-turns");
const metaRecalls = document.getElementById("meta-recalls");

let pc = null;
let dc = null;
let micStream = null;
let micMuted = false;
let sessionId = null;
let connected = false;
let toolCallInFlight = false;

let connectedAt = 0;
let uptimeTimer = null;
let turnCount = 0;
let recallTotal = 0;

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

// ── Icons (inline, one set, matched to the markup's stroke weight) ──────
const ICON = {
  vault:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/><path d="M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/></svg>',
  caret:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 6 15 12 9 18"/></svg>',
};

// ── Shell: views, drawer, session meta ─────────────────────────────────
const VIEWS = {
  conversation: ["Conversation", "Speak, and read back what was heard and recalled"],
  recall: ["Recall log", "Every knowledge-base call made this session"],
  session: ["Connection", "What this browser is holding open right now"],
  about: ["How it works", "Voice to OpenAI, questions to your vault"],
};

const tabs = Array.from(document.querySelectorAll(".nav-item[data-view]"));

function showView(name) {
  tabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.view === name)));
  Object.keys(VIEWS).forEach((key) => {
    const section = document.getElementById(`view-${key}`);
    const isActive = key === name;
    section.classList.toggle("is-active", isActive);
    section.hidden = !isActive;
  });
  const [title, sub] = VIEWS[name];
  viewTitle.textContent = title;
  viewSub.textContent = sub;
}

tabs.forEach((tab) =>
  tab.addEventListener("click", () => {
    showView(tab.dataset.view);
    closeRail();
  })
);

function openRail() {
  document.body.classList.add("rail-open");
  menuBtn.setAttribute("aria-expanded", "true");
}
function closeRail() {
  document.body.classList.remove("rail-open");
  menuBtn.setAttribute("aria-expanded", "false");
}
menuBtn.addEventListener("click", () =>
  document.body.classList.contains("rail-open") ? closeRail() : openRail()
);
railScrim.addEventListener("click", closeRail);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeRail();
});

function formatDuration(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function refreshUptime() {
  const text = connectedAt ? formatDuration(Date.now() - connectedAt) : "--:--";
  statUptime.textContent = text;
  metaUptime.textContent = connectedAt ? text : "—";
}

function bumpTurns() {
  turnCount += 1;
  statTurns.textContent = String(turnCount);
  metaTurns.textContent = String(turnCount);
}

function bumpRecalls() {
  recallTotal += 1;
  statRecalls.textContent = String(recallTotal);
  metaRecalls.textContent = String(recallTotal);
  recallCount.textContent = String(recallTotal);
}

function setStatus(text, state) {
  statusText.textContent = text;
  statusDot.className = "pulse" + (state ? ` ${state}` : "");
  metaState.textContent = text;
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
  setOrbState(toolCallInFlight ? "thinking" : connected ? "active" : "");
}

// ── Transcript ─────────────────────────────────────────────────────────
// A persistent conversation log, not floating captions. It scrolls inside
// its own pane instead of growing the page, so a long agent answer can
// never blow out the layout.
const STATUS_HOLD_MS = 5000;
const LINE_FADE_MS = 600;

// Only stick to the bottom if already close to it — called on every single
// typewriter tick (see below), so without this check it would fight anyone
// who scrolled up to reread something, yanking them back down constantly.
function scrollTranscriptToBottom() {
  const distanceFromBottom = transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight;
  if (distanceFromBottom < 80) transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function appendToTranscript(node) {
  if (emptyState.isConnected) emptyState.remove();
  transcriptInner.appendChild(node);
  scrollTranscriptToBottom();
  return node;
}

function addSystemLine(text, role = "system") {
  const p = document.createElement("p");
  p.className = `line-${role}`;
  p.textContent = text;
  return appendToTranscript(p);
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
  return appendToTranscript(div);
}

// Returns the inner .msg-bubble — callers keep writing into it as the
// spoken transcript streams in. The wrapper is stashed on the bubble so an
// unused reservation can be removed again (see response.done).
function addAssistantMessage() {
  const wrap = document.createElement("div");
  wrap.className = "msg msg-assistant";
  wrap.innerHTML =
    '<div class="msg-avatar"></div>' +
    '<div class="msg-bubble"><span class="typing-dots"><i></i><i></i><i></i></span></div>';
  appendToTranscript(wrap);
  const bubble = wrap.querySelector(".msg-bubble");
  bubble._wrap = wrap;
  return bubble;
}

// ── Recall entry — a knowledge-base lookup, in its own register ────────
// Holds: the request Mnemosyne made, a live list of the tools the LangGraph
// agent ran, and the raw text it returned. The raw text is collapsed by
// default and labelled as what it is — it is the tool's output, and showing
// it as an assistant bubble made it read as a second, clumsier Mnemosyne.
function addRecall(request) {
  const el = document.createElement("div");
  el.className = "recall";
  el.dataset.state = "running";
  el.innerHTML =
    '<button class="recall-head" type="button" aria-expanded="false">' +
    ICON.vault +
    '<span class="recall-title">Knowledge base</span>' +
    '<span class="recall-status">Searching your vault…</span>' +
    '<span class="recall-tools"></span>' +
    '<span class="recall-time"></span>' +
    `<span class="recall-caret">${ICON.caret}</span>` +
    "</button>" +
    '<p class="recall-ask"></p>' +
    '<div class="recall-steps"></div>' +
    '<div class="recall-body">' +
    '<div class="recall-body-label">Raw result returned to Mnemosyne</div>' +
    '<div class="recall-answer"></div>' +
    "</div>";

  el.querySelector(".recall-ask").textContent = request ? `“${request}”` : "(no request text)";

  const head = el.querySelector(".recall-head");
  head.addEventListener("click", () => {
    const open = el.classList.toggle("open");
    head.setAttribute("aria-expanded", String(open));
  });

  const timeEl = el.querySelector(".recall-time");
  const toolsEl = el.querySelector(".recall-tools");
  const startedAt = Date.now();
  let stepCount = 0;
  const tick = setInterval(() => {
    timeEl.textContent = `${((Date.now() - startedAt) / 1000).toFixed(1)}s`;
  }, 100);

  appendToTranscript(el);
  bumpRecalls();

  return {
    el,
    addStep(text) {
      const row = document.createElement("div");
      row.className = "step running";
      row.innerHTML = '<span class="step-dot"></span><span class="step-text"></span>';
      row.querySelector(".step-text").textContent = text;
      el.querySelector(".recall-steps").appendChild(row);
      stepCount += 1;
      scrollTranscriptToBottom();
      return row;
    },
    setAnswer(text) {
      el.querySelector(".recall-answer").textContent = text;
    },
    finish(ok, text) {
      clearInterval(tick);
      timeEl.textContent = `${((Date.now() - startedAt) / 1000).toFixed(1)}s`;
      el.dataset.state = ok ? "done" : "failed";
      el.querySelector(".recall-status").textContent = ok ? "Recalled" : "Lookup failed";
      toolsEl.textContent = stepCount ? `${stepCount} tool${stepCount > 1 ? "s" : ""}` : "";
      el.querySelectorAll(".step").forEach((s) => {
        s.classList.remove("running");
        s.classList.add(ok ? "done" : "failed");
      });
      if (text !== undefined) el.querySelector(".recall-answer").textContent = text;
      scrollTranscriptToBottom();
    },
  };
}

// ── Recall log panel ───────────────────────────────────────────────────
// Same events, different job: the transcript shows a lookup in context, the
// log lists every individual tool call with a timestamp so a slow or wrong
// lookup can be picked apart after the fact.
function addLogRow(toolCallText) {
  if (recallLogEmpty.isConnected) recallLogEmpty.remove();

  const sep = toolCallText.indexOf(" ");
  const tool = sep === -1 ? toolCallText : toolCallText.slice(0, sep);
  const args = sep === -1 ? "" : toolCallText.slice(sep + 1);

  const row = document.createElement("div");
  row.className = "log-row";
  row.innerHTML =
    '<span class="log-time"></span>' +
    '<span class="log-body"><span class="log-tool"></span><span class="log-args"></span></span>' +
    '<span class="log-state" data-state="running">Running</span>';
  row.querySelector(".log-time").textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  row.querySelector(".log-tool").textContent = tool;
  row.querySelector(".log-args").textContent = args;
  recallLog.appendChild(row);
  return row;
}

function finishLogRow(row, ok) {
  const state = row.querySelector(".log-state");
  state.dataset.state = ok ? "done" : "failed";
  state.textContent = ok ? "Done" : "Failed";
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
// line (see send_message_to_ai() in graph.py). "final_answer"/"error" chunks
// are the answer handed back to Mnemosyne. "thinking"/"tool_use" chunks are
// the agent's internal progress (covers every tool it calls along the way —
// search, read, write, ...), forwarded live via onProgress.
async function queryKnowledgeBase(request, onAnswer, onProgress) {
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
    if (chunk.Type === "final_answer" || chunk.Type === "error") {
      finalAnswer += chunk.content;
      onAnswer?.(finalAnswer);
    } else if (chunk.Type === "tool_use") {
      // "thinking" chunks are dropped here — always the same "Thinking..."
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
  setStatus("Recalling…", "thinking");

  // response.done (what triggers this) always fires after any spoken part
  // of the same response already streamed — appending here lands right
  // after that, which is correct DOM order for this response's own turn.
  const recall = addRecall(request);

  // One row per tool the agent calls along the way. The backend stream
  // doesn't say when an individual tool call finishes, only when the whole
  // request does, so every row opened during this call is marked
  // done/failed together at the end, not one by one.
  const logRows = [];

  // Relay every tool call into the Realtime conversation as it happens.
  // Without a response.create, none of this narrates out loud — a
  // conversation.item.create alone just adds silent context; nothing makes
  // the model actually generate speech to say it. The response that
  // decided to call this tool has already finished (response.done is what
  // triggers handleFunctionCall), so the slate's clear to prompt one new
  // reply here. Only do this for the first note in this lookup — one quick
  // "let me check..." is enough, forcing a fresh response.create per
  // subsequent tool would talk over itself. The "[AGENT PROGRESS]" tag is
  // explained once in openai_realtimeapi_prompt, not repeated per message.
  let narratedOnce = false;
  const sendProgressNote = (toolCallText) => {
    recall.addStep(toolCallText);
    logRows.push(addLogRow(toolCallText));
    if (!dc || dc.readyState !== "open") return;
    dc.send(
      JSON.stringify({
        type: "conversation.item.create",
        item: {
          type: "message",
          role: "system",
          content: [{ type: "input_text", text: `[AGENT PROGRESS] ${toolCallText}` }],
        },
      })
    );
    if (!narratedOnce) {
      narratedOnce = true;
      dc.send(JSON.stringify({ type: "response.create" }));
    }
  };

  let output;
  let ok = true;
  try {
    output = await queryKnowledgeBase(request, (partial) => recall.setAnswer(partial), sendProgressNote);
  } catch (err) {
    ok = false;
    output = `Lookup failed: ${err.message}`;
  }
  recall.finish(ok, output);
  logRows.forEach((row) => finishLogRow(row, ok));

  toolCallInFlight = false;
  setOrbState(connected ? "active" : "");
  if (connected) setStatus("Connected", "connected");

  if (!dc || dc.readyState !== "open") return;

  dc.send(
    JSON.stringify({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: callId,
        output: JSON.stringify({ result: output }),
      },
    })
  );
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
const TYPEWRITER_TICK_MS = 50; // midpoint between the 70ms/char try (too slow) and 30ms (too fast)
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

  if (DEBUG) {
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
      bumpTurns();
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

      // A response whose only output is a function call never produces any
      // spoken transcript, so the bubble reserved at response.created would
      // sit there with the typing dots bouncing forever. Drop reservations
      // that never received a word.
      const reserved = responseBubbles.get(event.response?.id);
      if (reserved) {
        if (!reserved.textContent && !reserved._twQueue) {
          if (reserved._twTimer) clearInterval(reserved._twTimer);
          reserved._wrap?.remove();
        }
        responseBubbles.delete(event.response.id);
      }

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
    metaSession.textContent = sessionId;
    const ephemeralKey = await fetchEphemeralKey();

    pc = new RTCPeerConnection();
    pc.ontrack = (e) => {
      remoteAudio.srcObject = e.streams[0];
      setupAudioAnalyser(e.streams[0]);
    };

    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    micStream.getTracks().forEach((track) => pc.addTrack(track, micStream));
    metaMic.textContent = micStream.getAudioTracks()[0]?.label || "Default input";

    dc = pc.createDataChannel("oai-events");
    dc.addEventListener("message", (e) => handleServerEvent(e.data));
    dc.addEventListener("open", () => {
      connected = true;
      connectedAt = Date.now();
      refreshUptime();
      uptimeTimer = setInterval(refreshUptime, 1000);
      setStatus("Connected", "connected");
      setOrbState("active");
      connectLabel.textContent = "End session";
      connectBtn.classList.remove("btn-primary");
      connectBtn.classList.add("btn-danger");
      connectBtn.disabled = false;
      micBtn.disabled = false;
      micBtn.classList.add("listening");
      dockHint.textContent = "Listening — just talk";
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
  if (uptimeTimer) clearInterval(uptimeTimer);
  dc = null;
  pc = null;
  micStream = null;
  micMuted = false;
  audioCtx = null;
  analyser = null;
  levelData = null;
  speakingRaf = null;
  uptimeTimer = null;
  connectedAt = 0;
  pendingUserBubbles.length = 0;
  responseBubbles.clear();
  refreshUptime();
  metaMic.textContent = "—";
  micBtn.classList.remove("muted", "listening");
  micBtn.disabled = true;
  micBtn.setAttribute("aria-label", "Mute microphone");
  micBtn.title = "Mute microphone";
  dockHint.textContent = "Microphone access required · English or Portuguese";
  setOrbState("");
}

function disconnect() {
  cleanup();
  setStatus("Idle", "");
  connectLabel.textContent = "Connect";
  connectBtn.classList.remove("btn-danger");
  connectBtn.classList.add("btn-primary");
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
  micBtn.classList.toggle("muted", micMuted);
  micBtn.classList.toggle("listening", !micMuted);
  const label = micMuted ? "Unmute microphone" : "Mute microphone";
  micBtn.setAttribute("aria-label", label);
  micBtn.title = label;
  dockHint.textContent = micMuted ? "Microphone muted — she can't hear you" : "Listening — just talk";
});

refreshUptime();
