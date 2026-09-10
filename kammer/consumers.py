"""A websocket for streaming replies into rooms without a GraphQL round trip per token.

Mount: ``ws://<host>/<prefix>/kammer/stream/``. One connection can stream any
number of messages, one after another or interleaved.

Frames are JSON objects with a ``type``:

Client → server
    ``{"type": "auth", "token": "<jwt>"}``
        Required first, unless the token was given as ``?token=`` on the URL.
    ``{"type": "start", "room": "<id>", "agent_id": "<name>", "parent": "<id>"?, "text": ""?}``
        Open a message with ``is_streaming: true``.
    ``{"type": "append", "message": <id>, "delta": "<text>"}``
        Append text. Deltas are coalesced server-side and written at most every
        ``FLUSH_INTERVAL_SECONDS`` (or when ``MAX_BUFFER_CHARS`` accumulate),
        so a client may send one frame per token.
    ``{"type": "finish", "message": <id>, "text": "<final text>"?}``
        Flush and close the message; ``text`` replaces the whole body.

Server → client
    ``{"type": "authenticated", "user": <id>, "organization": <id>}``
    ``{"type": "started", "message": <id>}``
    ``{"type": "finished", "message": <id>, "text": "<final text>"}``
    ``{"type": "error", "detail": "...", "message": <id>?}``

Ownership rules are those of the GraphQL mutations (same user and client as
the agent that started the message; finished messages are immutable). A message
started on a connection that drops is finished with whatever had arrived, so a
crashed client never leaves a message open.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from authentikate.expand import aexpand_token_context
from authentikate.settings import get_settings
from authentikate.utils import authenticate_token
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from kammer import models, streaming
from kammer.channels import message_channel
from kammer.enums import RoomEventKind

logger = logging.getLogger(__name__)

#: Longest a delta waits in the buffer before it is written and announced.
FLUSH_INTERVAL_SECONDS = 0.1
#: Buffered characters that trigger an immediate flush.
MAX_BUFFER_CHARS = 512

CLOSE_UNAUTHENTICATED = 4401


@dataclass
class _Stream:
    """A message this connection is writing to."""

    message: models.Message
    started_here: bool
    buffer: list[str] = field(default_factory=list)
    buffered_chars: int = 0
    flush_task: Optional[asyncio.Task] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MessageStreamConsumer(AsyncJsonWebsocketConsumer):
    """See the module docstring for the protocol."""

    async def connect(self) -> None:
        self.user = self.client = self.organization = None
        self.streams: dict[int, _Stream] = {}
        await self.accept()

        token = parse_qs(self.scope.get("query_string", b"").decode()).get("token", [None])[0]
        if token:
            await self._authenticate(token)

    async def disconnect(self, code: int) -> None:
        # Flush what arrived, then close anything this connection opened so a
        # crashed client never leaves a message streaming forever.
        for message_id in list(self.streams):
            stream = self.streams.get(message_id)
            if stream is None:
                continue
            try:
                await self._flush(message_id)
                if stream.started_here and message_id in self.streams:
                    await self._finish(stream, text=None)
            except Exception:
                logger.exception("Could not close streamed message %s on disconnect", message_id)
        self.streams.clear()

    # --- frames -----------------------------------------------------------

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        kind = content.get("type") if isinstance(content, dict) else None
        if kind == "auth":
            await self._authenticate(str(content.get("token", "")))
            return
        if self.user is None:
            await self._error("Not authenticated: send {\"type\": \"auth\", \"token\": ...} first")
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        try:
            if kind == "start":
                await self._start(content)
            elif kind == "append":
                await self._append(content)
            elif kind == "finish":
                await self._finish_frame(content)
            else:
                await self._error(f"Unknown frame type {kind!r}")
        except (models.Room.DoesNotExist, models.Message.DoesNotExist):
            await self._error("No such room or message", message=content.get("message"))
        except (PermissionError, ValueError) as e:
            await self._error(str(e), message=content.get("message"))

    async def _authenticate(self, token: str) -> None:
        try:
            decoded = await authenticate_token(token, get_settings())
            context = await aexpand_token_context(decoded)
        except Exception as e:
            # Malformed, expired, unknown-issuer and blocked-membership failures
            # come from several error hierarchies; all of them mean "not you".
            logger.debug("Websocket authentication failed", exc_info=True)
            await self._error(f"Authentication failed: {type(e).__name__}")
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        self.user, self.client, self.organization = context.user, context.client, context.organization
        await self.send_json({"type": "authenticated", "user": self.user.id, "organization": self.organization.id})

    async def _start(self, content: dict) -> None:
        message = await sync_to_async(streaming.open_message)(
            organization=self.organization,
            user=self.user,
            client=self.client,
            room_id=content["room"],
            agent_name=str(content.get("agent_id") or "agent"),
            parent_id=content.get("parent"),
            text=str(content.get("text") or ""),
        )
        self.streams[message.id] = _Stream(message=message, started_here=True)
        await self.send_json({"type": "started", "message": message.id})

    async def _stream_for(self, message_id: int) -> _Stream:
        """The connection's handle on a message, adopting one started elsewhere if it is ours."""
        stream = self.streams.get(message_id)
        if stream is None:
            message = await sync_to_async(streaming.owned_streaming_message)(organization=self.organization, user=self.user, client=self.client, message_id=message_id)
            stream = self.streams[message_id] = _Stream(message=message, started_here=False)
        return stream

    async def _append(self, content: dict) -> None:
        message_id = int(content["message"])
        delta = str(content.get("delta") or "")
        if not delta:
            return
        stream = await self._stream_for(message_id)
        stream.buffer.append(delta)
        stream.buffered_chars += len(delta)
        if stream.buffered_chars >= MAX_BUFFER_CHARS:
            await self._flush(message_id)
        elif stream.flush_task is None:
            stream.flush_task = asyncio.create_task(self._flush_after_delay(message_id))

    async def _finish_frame(self, content: dict) -> None:
        message_id = int(content["message"])
        stream = await self._stream_for(message_id)
        await self._flush(message_id)
        if message_id in self.streams:
            await self._finish(stream, text=content.get("text"))

    # --- writing ------------------------------------------------------------

    async def _flush_after_delay(self, message_id: int) -> None:
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        stream = self.streams.get(message_id)
        if stream is not None:
            stream.flush_task = None
        await self._flush(message_id)

    async def _flush(self, message_id: int) -> None:
        """Write the buffered deltas in one UPDATE and announce the change."""
        stream = self.streams.get(message_id)
        if stream is None:
            return
        if stream.flush_task is not None and stream.flush_task is not asyncio.current_task():
            stream.flush_task.cancel()
            stream.flush_task = None
        async with stream.lock:
            delta = "".join(stream.buffer)
            stream.buffer.clear()
            stream.buffered_chars = 0
            if not delta:
                return
            if await sync_to_async(streaming.append_delta)(message_id, delta) == 0:
                # Finished elsewhere meanwhile; the delta is dropped.
                self.streams.pop(message_id, None)
                await self._error("This message is finished and cannot be modified", message=message_id)
                return
            await message_channel.abroadcast(*streaming.signal_for(RoomEventKind.MESSAGE_UPDATED, stream.message))

    async def _finish(self, stream: _Stream, *, text: Optional[str]) -> None:
        message = await sync_to_async(streaming.finish_message)(stream.message, text=text)
        self.streams.pop(message.id, None)
        await message_channel.abroadcast(*streaming.signal_for(RoomEventKind.MESSAGE_FINISHED, message))
        await self.send_json({"type": "finished", "message": message.id, "text": message.text})

    async def _error(self, detail: str, *, message: Any = None) -> None:
        payload: dict[str, Any] = {"type": "error", "detail": detail}
        if message is not None:
            payload["message"] = message
        await self.send_json(payload)
