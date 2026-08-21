# Mnemosyne — voice widget

Browser-side client for talking to the agent over the OpenAI Realtime API (WebRTC). Follows whichever language you speak (English or Portuguese, per `openai_realtimeapi_prompt`); speaking English to it doubles as interview practice.

**How it was built:** `index.html` and `app.js` in this folder were written by Claude Code, under John's direction, as the frontend half of the voice-widget feature. The backend (`api.py` routes, session/query logic, `prompts.py`) is authored by John himself. This disclosure lives here, not in commit messages, per the project's authorship convention for the portfolio repo.

## How it works

1. Browser calls `POST /realtime/new_session` to get a short-lived OpenAI ephemeral token.
2. Browser opens a WebRTC connection directly to OpenAI's Realtime API with that token — mic audio out, speaker audio in, plus a data channel for events.
3. When the model wants to consult the knowledge base, it triggers the `Knowledge_base` function (name must match `openai_realtimeapi_tool_name` in `prompts.py`). The widget then calls `POST /realtime/query`, which runs the real LangGraph agent, and feeds the result back into the Realtime session as `function_call_output`.

## Auth

The whole `/mnemosyne*` origin (the page, `app.js`, and the `/realtime/*` routes it calls) sits behind server-side HTTP Basic Auth. The browser prompts once and caches the credentials, resending them automatically on every same-origin request — including the `fetch()` calls in `app.js` — so no token lives in the frontend code. There used to be a separate widget API key baked into `app.js` at request time; it was dropped once Basic Auth covered the whole origin, since the two mechanisms collided on the same `Authorization` header and there was no secret left worth hiding in the JS anyway.

## Layout

An app shell, not a centred card: a 244px rail (wordmark, nav, session counters), a thin topbar (current view + link state), the view itself, and a dock pinned to the bottom.

- **The transcript is the product**, so it takes every pixel between the topbar and the dock — `100dvh` grid, `flex: 1` with `min-height: 0`, and nothing capped at a fixed height. `dvh` rather than `vh` because mobile browser chrome resizes the viewport and `vh` would push the dock under the URL bar. Under 900px the rail becomes an off-canvas drawer, which leaves the conversation ~86% of a phone screen (measured at 390×844) against the ~200px it had as a card.
- **The dock holds presence and controls together** — the orb, the session button, the mic toggle. The orb is the thing that listens and speaks, so it sits where you act, and it stays on screen on every view and every breakpoint.
- **Views stay mounted** and are swapped by `.is-active` + `hidden`, so switching tabs never loses the transcript's scroll position or a half-revealed answer.

## Two registers in the transcript

The transcript carries two different kinds of thing, and it has to be obvious which is which at a glance:

- **Blue — spoken.** Your turns and Mnemosyne's. Her bubbles are the words actually coming out of the speaker (`response.output_audio_transcript.delta`).
- **Purple — recalled.** A knowledge-base lookup, rendered as a `.recall` entry in its own lane: the request she made, a live list of the tools the LangGraph agent ran, and — collapsed by default, in mono, labelled *"raw result returned to Mnemosyne"* — the text the agent handed back.

That collapse is the point. The agent's return used to be rendered as an assistant bubble, so every lookup read as Mnemosyne answering twice: once in raw agent prose, once in her own words. It is a tool result, and it is now presented as one. Purple also drives the orb's `thinking` state and the topbar pulse, so all three agree about what's happening.

The **Recall log** view lists the same tool calls as timestamped rows — the transcript shows a lookup in context, the log is for picking a slow or wrong one apart afterwards.

## Visual identity

The blue/navy palette and the aurora + light-beam + breathing-starfield background are adapted from the shared design system used by **Ads Analyst Agent** and **Meta Ads Bulk Upload** (source of truth: `Ads Analyst Agent/docs/design/visual-identity.md`; canvas logic adapted from `Meta Ads - Bulk Upload/Arquitetura/public/_shared/background.js`). Kept inline in `index.html`/`app.js` — this widget has no build step and no static-file mount, and each asset here is served by its own explicit FastAPI route, so a separate `style.css`/`background.js` would mean touching `api.py`.

Tokens are in two layers: the platform primitives above, then Mnemosyne's own semantics on top (`--sky-1/2/3` for elevation, `--recall*` for the lookup lane). Elevation is done with **translucency, never solid fill** — the aurora has to read through the chrome, that's the page's identity — so hairline `--edge*` borders do the separating, and `backdrop-filter` is confined to the rail, topbar and dock per the design system's perf rule.

All the standard perf guardrails carried over: `prefers-reduced-motion` (single static frame, no animation loop), pause on tab-hidden, 20fps cap on the canvas, and a reduced star count under 600px viewport width.

## Known rough edges

- **No per-tool completion signal.** `send_message_to_ai()` (`graph.py`) says when a tool *starts* (`{"Type": "tool_use"}`) but never when that individual call returns — only the whole request ending is observable. So every step and log row opened during one lookup is marked done/failed together at the end, not one by one.
- **The `thinking` chunk carries no information** — it's always the same hardcoded `"Thinking..."` filler, so the widget drops it rather than showing it. Anything worth displaying comes from `tool_use`.
- **Event-timing logs are opt-in** via `?debug=1`; they were load-bearing while the bubble-ordering fix was being worked out and are noise the rest of the time.
