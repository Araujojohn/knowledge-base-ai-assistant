# Mnemosyne — voice widget

Browser-side client for talking to the agent over the OpenAI Realtime API (WebRTC). English only, by design — it doubles as spoken-English practice for interview prep.

**How it was built:** `index.html` and `app.js` in this folder were written by Claude Code, under John's direction, as the frontend half of the voice-widget feature. The backend (`api.py` routes, session/query logic, `prompts.py`) is authored by John himself. This disclosure lives here, not in commit messages, per the project's authorship convention for the portfolio repo.

## How it works

1. Browser calls `POST /realtime/new_session` to get a short-lived OpenAI ephemeral token.
2. Browser opens a WebRTC connection directly to OpenAI's Realtime API with that token — mic audio out, speaker audio in, plus a data channel for events.
3. When the model wants to consult the knowledge base, it triggers the `Knowledge_base` function (name must match `openai_realtimeapi_tool_name` in `prompts.py`). The widget then calls `POST /realtime/query`, which runs the real LangGraph agent, and feeds the result back into the Realtime session as `function_call_output`.

## Auth

The whole `/mnemosyne*` origin (the page, `app.js`, and the `/realtime/*` routes it calls) sits behind server-side HTTP Basic Auth. The browser prompts once and caches the credentials, resending them automatically on every same-origin request — including the `fetch()` calls in `app.js` — so no token lives in the frontend code. There used to be a separate widget API key baked into `app.js` at request time; it was dropped once Basic Auth covered the whole origin, since the two mechanisms collided on the same `Authorization` header and there was no secret left worth hiding in the JS anyway.

## Known rough edge

`/realtime/query`'s response is the same stream `send_message_to_ai()` produces for WhatsApp — it interleaves "Pensando..." and raw tool-call summaries with the actual answer, with no delimiter between chunks. The widget currently forwards the *whole* stream as the function result, so the voice agent may occasionally repeat that noise back. Cleanly separating "final answer" from "debug narration" needs a backend change (e.g. structured/typed chunks) — not done here.
