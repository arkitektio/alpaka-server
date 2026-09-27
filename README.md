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
immutable. A message *opened on* a socket that drops is finished with whatever had
arrived; one opened with `startMessage` and merely continued over the socket is flushed
but left open, because the caller that opened it still owns its lifecycle and can finish
it after reconnecting.

Subscribers of the `room` subscription receive `MESSAGE_CREATED`, `MESSAGE_UPDATED` and
`MESSAGE_FINISHED` events either way. Events are scoped per room and the group membership
is refcounted per connection, so a client may watch several rooms over one websocket:
subscriptions no longer cross-feed each other, and closing one does not silence the rest.
There is no backfill — a subscription only sees what happens after it joins.


## Typed decisions (TypeSafe, Ollaya)

Next to chat, alpaka serves **decision models**. These take a state plus named, typed
questions and return calibrated answers instead of text:

- `noul`: yes/no, answered with a probability.
- `choice`: pick one of several named options, answered with the choice, a confidence, and the probability of each option.
- `score`: rate on an ordered rubric, answered with the expected level, a confidence, and the probability of each level.

Any runtime that speaks the systemone wire protocol can serve them. Today that is TypeSafe's
hosted Jev (`kind: typesafe`) and a self-hosted Ollaya (`kind: ollaya`). The backend is picked by
the provider's kind, so budgets, usage records and tenancy work the same for both (see
CONFIG.md).

**GraphQL.** Each question is exactly one of `noul`, `choice` or `score` (a `@oneOf` input). The
answers come back as a union, in the order the questions were asked:

```graphql
mutation {
  decide(input: {
    model: "42"   # or omit it to use your default for kind DECISION
    state: "Help! My payouts have been failing for 3 days."
    questions: [
      {noul: {key: "urgent", instructions: "Does this convey urgency?"}}
      {choice: {key: "team", instructions: "Which team handles this?",
                options: [{key: "billing"}, {key: "technical"}, {key: "sales"}]}}
      {score: {key: "frustration", instructions: "How frustrated is the customer?",
               levels: ["Calm", "Frustrated", "Very angry"]}}
    ]
  }) {
    model
    answers {
      ... on NoulAnswer { key noul }
      ... on ChoiceAnswer { key choice confidence }
      ... on ScoreAnswer { key score confidence levels { level probability } }
    }
  }
}
```

**systemone REST.** alpaka also speaks the wire protocol itself at `/llm/systemone/v1/systemone` and
`/llm/systemone/v1/models`. A stock TypeSafe or Ollaya client works when you point it at alpaka
and pass an alpaka token as the key:

```python
from typesafe_sdk import TypeSafeClient, Noul

client = TypeSafeClient(api_key="<alpaka token>", base_url="https://<host>/<prefix>/llm/systemone")
client.system_one("I was charged twice.", {"billing": Noul(instructions="Is this about billing?")},
                  model="laya:en")   # a model id, or "alpaka/default" for your default
```

The client never sees the organization's upstream key. A spent budget answers `402`, which the
SDK does not retry.
