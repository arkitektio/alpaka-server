# alpaka-server

The language-model gateway of an [Arkitekt](https://arkitekt.live) hub. Each organization
configures its own providers and models (anything [litellm](https://docs.litellm.ai) reaches,
or a local Ollama), and alpaka puts chat, image generation, typed decisions, usage records
and budgets in front of them, so a client never sees the organization's upstream key. It
also keeps chat rooms and their messages, and document collections in ChromaDB. It is
registered as `live.arkitekt.alpaka` and has a python client,
[`alpaka`](https://github.com/jhnnsrs/alpaka).

## What it stores

| Concept | What it is |
| --- | --- |
| `Provider`, `ProviderPartner` | An organization's connection to one LLM backend, and the pre-declared backends it can be created from. |
| `LLMModel`, `DefaultUse` | A model a provider serves, and which model the organization uses by default for a kind of work. |
| `UsageRecord`, `Budget` | What every call cost, and the limit it is counted against. |
| `Room`, `Agent`, `Message` | A chat room, who writes in it, and what was written. |
| `ChromaCollection` | A document collection; the documents and their vectors live in ChromaDB. |

Everything but the partner catalog belongs to an organization, and every read and write is
scoped to the caller's.

## API

GraphQL is served at `/graphql` (HTTP and WebSocket), with the SDL at `/schema`.

| Operations | What they do |
| --- | --- |
| `createProvider`, `updateProvider`, `refreshProvider`, `deleteProvider`, `pull`, `useModelFor` | Connect a backend, list or pull its models, pick the defaults. |
| `chat`, `generateImage`, `decide` | Inference through the organization's providers. See [Typed decisions](#typed-decisions-typesafe-ollaya). |
| `createBudget`, `updateBudget`, `deleteBudget`, `budgetStatus`, `usageRecords`, `usageStats` | Limits and what was spent against them. |
| `createRoom`, `send`, `startMessage`, `appendMessage`, `finishMessage`, `room` (subscription) | Rooms and their messages. See [Streaming replies into rooms](#streaming-replies-into-rooms). |
| `createCollection`, `ensureCollection`, `addDocumentsToCollection`, `documents` | Document collections and retrieval. |

Next to GraphQL, under `/llm/`:

- an **OpenAI-compatible API**: `v1/models`, `v1/chat/completions`, `v1/completions`,
  `v1/embeddings`. A stock OpenAI client works with an alpaka token as its key;
- the **systemone** wire protocol for decision models: `systemone/v1/systemone`,
  `systemone/v1/models`.

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

## Hub integration

Declared in [`alpaka_server/contract.py`](alpaka_server/contract.py):

- **Scopes**: `alpaka_infer`, `alpaka_train`, `alpaka_manage`, `read`, `write`.
- **Roles**: `admin`, `user`, `modeler`, `viewer`.
- **Needs**: rekuest 6 or newer, an instance key, tokens issued by lok. If the hub has an
  Ollama, its URL is written into the config.

alpaka is known to the hub's rekuest in two separate ways:

- as a **service** (`_rekuest/service`): it hosts the structures `@alpaka/room`,
  `@alpaka/message`, `@alpaka/llmmodel`, `@alpaka/chromacollection` and `@alpaka/provider`
  ([`alpaka_server/service.py`](alpaka_server/service.py));
- as a **hook agent** (`_rekuest/hook`): it offers one action, `reembed_stale`
  ([`alpaka_server/hook_agent.py`](alpaka_server/hook_agent.py)).

The action is only offered. Nothing in this service loops or schedules; whether and when it
runs is the organization's own automation in rekuest.

## Running

The image is `jhnnsrs/alpaka`. Starting it takes two steps:

```sh
python -m arkitekt_service migrate   # wait for the database, migrate, ensureadmin, ensurepartners
bash run.sh                          # serve on :80 (daphne), and nothing else
```

`bash run.sh` is the image's default command. `run-debug.sh` does both steps in one go with
Django's autoreloading server, for development.

It needs Postgres with pgvector ([`jhnnsrs/daten`](https://github.com/arkitektio/daten-server)),
Redis and ChromaDB, and reaches whatever LLM backends the organizations configure. The
embedding model used for semantic search is baked into the image.

## Configuration

The service reads `config.yaml`, or the file named by `ARKITEKT_CONFIG_FILE`; any value can
be overridden by an environment variable (`POSTGRES__HOST`). `python manage.py
validate_settings` prints the configuration as the service reads it, with secrets redacted.

See [CONFIG.md](CONFIG.md) for every value, including how providers are declared
(`provider_partners`).

## Development

```sh
uv sync
uv run pytest
```

The suite runs against a real stack, brought up by [dokker](https://github.com/jhnnsrs/dokker)
from `tests/integration/docker-compose.yaml`:

- Postgres (`jhnnsrs/daten:next`, override with `DATEN_IMAGE`) and Redis;
- a real Ollaya (`ghcr.io/ollaya-dev/ollaya`), the decision-model runtime. Its
  test model (about 680 MB) is downloaded once into the Docker volume `alpaka-test-ollaya`;
- `tests/integration/faketypesafe`, a stand-in for the hosted TypeSafe API, built locally.

It needs a running Docker daemon.

## Releases

Releases are tags: a push to `main` cuts a stable version, a push to `next` a release
candidate. Each one publishes `jhnnsrs/alpaka` under its version (`X.Y.Z`, `X.Y`, `X`), plus
`latest` from `main` and `next` from `next`. The `version` in `pyproject.toml` is a
placeholder. Release notes are on
[GitHub Releases](https://github.com/arkitektio/alpaka-server/releases); `CHANGELOG.md` is
frozen.
