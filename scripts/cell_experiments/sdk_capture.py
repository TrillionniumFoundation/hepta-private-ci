"""Capture an authorized completed SDK turn into a private POSIX original slot.

This is a typed observation, not a training record or an authorization receipt.
The caller must already be allowed to read the entire specified thread history.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from openai_codex import AsyncCodex, AsyncThread, CodexConfig, __version__
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    CommandExecutionThreadItem,
    DynamicToolCallThreadItem,
    FileChangeThreadItem,
    McpToolCallThreadItem,
    ThreadReadResponse,
    TurnItemsView,
    TurnStatus,
    UserMessageThreadItem,
)

MAX_ITEMS = 256
MAX_BYTES = 1_048_576
ITEM_TYPES = {
    UserMessageThreadItem: "userMessage",
    AgentMessageThreadItem: "agentMessage",
    CommandExecutionThreadItem: "commandExecution",
    FileChangeThreadItem: "fileChange",
    McpToolCallThreadItem: "mcpToolCall",
    DynamicToolCallThreadItem: "dynamicToolCall",
}


class CaptureRefused(ValueError):
    """A fixed, payload-free refusal code safe for the command-line summary."""


def _identity(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise CaptureRefused("invalid_identity")
    return value


def _observation(response, thread_id, turn_id):
    if not isinstance(response, ThreadReadResponse):
        raise CaptureRefused("typed_response_required")
    thread = response.thread
    if thread.id != thread_id:
        raise CaptureRefused("wrong_thread")
    _identity(thread.session_id)
    selected = [turn for turn in thread.turns if turn.id == turn_id]
    if len(selected) != 1:
        raise CaptureRefused("turn_not_unique")
    turn = selected[0]
    if turn.status is not TurnStatus.completed:
        raise CaptureRefused("turn_not_completed")
    if turn.items_view not in (TurnItemsView.full, "full"):
        raise CaptureRefused("items_not_full")
    if len(turn.items) > MAX_ITEMS:
        raise CaptureRefused("too_many_items")
    items, omitted, seen = [], [], set()
    for position, item in enumerate(turn.items):
        payload = item.root
        item_id = _identity(payload.id)
        if item_id in seen:
            raise CaptureRefused("duplicate_item_identity")
        seen.add(item_id)
        identity = {"source_index": position, "item_id": item_id, "type": payload.type}
        expected_type = ITEM_TYPES.get(type(payload))
        if expected_type is None:
            omitted.append(identity)
            continue
        if payload.type != expected_type:
            raise CaptureRefused("typed_item_mismatch")
        items.append(
            {
                **identity,
                "sdk_payload": payload.model_dump(
                    mode="json", by_alias=True, exclude_unset=True
                ),
            }
        )
    return {
        "schema": "hepta.sdk-observed-turn-source.v1",
        "read_method": "AsyncThread.read(include_turns=True)",
        "sdk_version": __version__,
        "serialization": "pydantic-json-aliases-exclude-unset/utf8-sorted-compact-v1",
        "thread": thread.model_dump(
            mode="json",
            by_alias=True,
            exclude_unset=True,
            include={"id", "session_id", "model_provider", "cli_version"},
        ),
        "turn": turn.model_dump(
            mode="json",
            by_alias=True,
            exclude_unset=True,
            include={
                "id",
                "status",
                "items_view",
                "started_at",
                "completed_at",
                "duration_ms",
            },
        ),
        "items_view_explicit": "items_view" in turn.model_fields_set,
        "returned_item_count": len(turn.items),
        "items": items,
        "omitted_items": omitted,
        "teacher_opaque_id": None,
        "teacher_model_sha256": None,
        "claims": {
            "raw_wire_preserved": False,
            "source_signed": False,
            "complete_original_trajectory_proven": False,
            "item_execution_verified": False,
            "human_training_consent_proven": False,
            "semantic_labels_verified": False,
            "evaluator_receipt_created": False,
            "training_record_created": False,
            "production_training_authorized": False,
        },
    }


def _open_private_directory(path):
    if os.name != "posix":
        raise CaptureRefused("posix_storage_required")
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise CaptureRefused("absolute_originals_path_required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path.anchor, flags)
    try:
        for index, component in enumerate(path.parts[1:], start=1):
            if index == len(path.parts) - 1:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise CaptureRefused("private_originals_directory_required")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _stable_metadata(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _verify_original(directory, digest, raw):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(digest, flags, dir_fd=directory)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != len(raw)
        ):
            raise CaptureRefused("private_regular_original_required")
        observed = bytearray()
        while len(observed) <= len(raw):
            chunk = os.read(fd, min(65536, len(raw) + 1 - len(observed)))
            if not chunk:
                break
            observed.extend(chunk)
        after = os.fstat(fd)
        current = os.stat(digest, dir_fd=directory, follow_symlinks=False)
        if (
            observed != raw
            or _stable_metadata(before) != _stable_metadata(after)
            or _stable_metadata(current) != _stable_metadata(after)
        ):
            raise CaptureRefused("original_bytes_or_metadata_differ")
    finally:
        os.close(fd)


def _publish_private_original(path, raw):
    digest = hashlib.sha256(raw).hexdigest()
    directory = _open_private_directory(path)
    temporary = "capture-stage-" + secrets.token_hex(16)
    staged = False
    created = False
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        staged = True
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary,
                digest,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            created = True
        except FileExistsError:
            pass
        os.unlink(temporary, dir_fd=directory)
        staged = False
        _verify_original(directory, digest, raw)
        os.fsync(directory)
        return digest, created
    finally:
        try:
            if staged:
                os.unlink(temporary, dir_fd=directory)
        finally:
            os.close(directory)


async def capture_completed_turn(thread: AsyncThread, *, turn_id: str, originals: Path):
    """Read caller-authorized history, then retain one completed typed projection.

    No stream is registered or consumed. IDs and all reported payloads remain
    observations; neither the caller nor this source file grants Train authority.
    """
    if not isinstance(thread, AsyncThread):
        raise CaptureRefused("sdk_async_thread_required")
    thread_id = _identity(thread.id)
    turn_id = _identity(turn_id)
    response = await thread.read(include_turns=True)
    if thread.id != thread_id:
        raise CaptureRefused("thread_handle_changed")
    observation = _observation(response, thread_id, turn_id)
    try:
        raw = json.dumps(
            observation,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise CaptureRefused("source_not_json_encodable") from error
    if len(raw) > MAX_BYTES:
        raise CaptureRefused("source_too_large")
    digest, created = await asyncio.to_thread(_publish_private_original, originals, raw)
    return {
        "schema": "hepta.sdk-observed-turn-capture.v1",
        "thread_id": thread_id,
        "turn_id": turn_id,
        "source_sha256": digest,
        "source_bytes": len(raw),
        "created": created,
        "training_record_created": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument(
        "--codex-bin", help="Optional caller-selected installed Codex executable"
    )
    args = parser.parse_args()

    async def read_and_capture():
        thread_id = _identity(args.thread_id)
        turn_id = _identity(args.turn_id)
        async with AsyncCodex(CodexConfig(codex_bin=args.codex_bin)) as codex:
            thread = AsyncThread(codex, thread_id)
            return await capture_completed_turn(
                thread, turn_id=turn_id, originals=args.originals
            )

    try:
        receipt = asyncio.run(read_and_capture())
    except CaptureRefused as error:
        parser.exit(2, "capture refused: " + str(error) + "\n")
    except Exception:
        parser.exit(2, "SDK capture failed; no training record was created.\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
