"""Framed, binary-safe transport used by the Fusion adapter and server child.

The transport deliberately has a small contract: JSON-compatible values use a
``J<len>:`` frame and a top-level bytes value uses a ``B<len>:`` frame.  The
length is always a byte length, never a character count.
"""

from __future__ import annotations

import json
from typing import Any, BinaryIO

from context import deserialize_value, serialize_value


class FrameProtocolError(RuntimeError):
    """Raised when a stream cannot be interpreted as a complete bridge frame."""


class FramedConnection:
    """A tiny bidirectional wrapper around binary input and output streams."""

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self.reader = reader
        self.writer = writer

    def read(self) -> Any:
        """Read and decode one complete frame from this connection.

        ``EOFError`` signals a clean end before a new frame; malformed or
        truncated frames instead raise :class:`FrameProtocolError`.
        """
        kind, length = self._read_header()
        payload = self._read_exact(length)
        if kind == b"B":
            return payload
        try:
            return deserialize_value(json.loads(payload.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FrameProtocolError("malformed UTF-8 JSON frame payload") from error

    def write(self, value: Any) -> None:
        """Write one frame and flush the output stream when supported."""
        self.writer.write(self._encode_frame(value))
        flush = getattr(self.writer, "flush", None)
        if flush:
            flush()

    @staticmethod
    def _encode_frame(value: Any) -> bytes:
        if isinstance(value, (bytes, bytearray, memoryview)):
            payload = bytes(value)
            kind = b"B"
        else:
            serialized = serialize_value(value)
            try:
                payload = json.dumps(
                    serialized, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            except (TypeError, ValueError) as error:
                raise TypeError("bridge JSON payload must be JSON serializable") from error
            kind = b"J"
        return kind + str(len(payload)).encode("ascii") + b":" + payload

    def _read_exact(self, length: int) -> bytes:
        """Read exactly *length* bytes, handling streams that return short chunks."""
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = self.reader.read(remaining)
            if not chunk:
                received = length - remaining
                raise FrameProtocolError(
                    f"premature end of stream: expected {length} payload bytes, received {received}"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_header(self) -> tuple[bytes, int]:
        header = bytearray()
        while True:
            byte = self.reader.read(1)
            if not byte:
                if not header:
                    raise EOFError("end of stream before next bridge frame")
                raise FrameProtocolError("premature end of stream in frame header")
            header.extend(byte)
            if len(header) > 64:
                raise FrameProtocolError("frame header exceeds maximum length")
            if byte == b":":
                break

        kind, length_text = bytes(header[:-1][:1]), bytes(header[:-1][1:])
        if kind not in (b"J", b"B"):
            raise FrameProtocolError(f"unsupported frame kind {kind!r}")
        if not length_text or not length_text.isdigit():
            raise FrameProtocolError(f"malformed frame length {length_text!r}")
        return kind, int(length_text)
