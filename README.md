# Alpaka-Server


## Develompent

Alpaka-Server is LLM gateway for the Arkitekt Framework. It connects via LLMlite to various LLMs and packages them with ChromaDB for vector storage and retrieval.


## Installation

Right now the easiest way to install Alpaka-Server is with the Arkitekt CLI. You can install the CLI with:





## Streaming replies into rooms

Agents live on clients; the server never calls an LLM on behalf of a room. A client
that streams a reply (from the `chat` mutation or the OpenAI-compatible
`/llm/v1/chat/completions` endpoint) forwards it into a room in one of two ways.

**GraphQL** — `startMessage` → `appendMessage` (one delta per call) → `finishMessage`.
Batch deltas (every ~100–250 ms or ~30 characters) and await each append before the
next; always call `finishMessage` in a `finally`, passing the full text so a lost delta
is repaired.

**WebSocket** — `ws://<host>/<prefix>/kammer/stream/`, one frame per token with no
GraphQL overhead. The server coalesces deltas and writes at most every 100 ms.

```jsonc
// client → server
{"type": "auth", "token": "<jwt>"}                                   // or ?token= on the URL
{"type": "start", "room": "<id>", "agent_id": "assistant", "parent": null, "text": ""}
{"type": "append", "message": 42, "delta": "Hel"}
{"type": "append", "message": 42, "delta": "lo"}
{"type": "finish", "message": 42, "text": "Hello"}                   // text is optional
// server → client
{"type": "authenticated", "user": 1, "organization": 1}
{"type": "started", "message": 42}
{"type": "finished", "message": 42, "text": "Hello"}
{"type": "error", "detail": "...", "message": 42}
```

Only the user and client that started a message may write to it; finished messages are
immutable. A message opened on a socket that drops is finished with whatever had arrived.
Subscribers of the `room` subscription receive `MESSAGE_CREATED`, `MESSAGE_UPDATED` and
`MESSAGE_FINISHED` events either way.
