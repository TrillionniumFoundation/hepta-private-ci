"""Engineering fixtures for typed capture; no runtime, teacher, or training calls."""

import contextlib
import copy
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from openai_codex import AsyncCodex, AsyncThread
from openai_codex.generated.v2_all import ThreadReadResponse

from cell_experiments import sdk_capture


def response_payload():
    return {
        "thread": {
            "cliVersion": "fixture-runtime",
            "createdAt": 1,
            "cwd": "/fixture",
            "ephemeral": False,
            "id": "thread-observed",
            "modelProvider": "reported-provider-only",
            "preview": "not retained",
            "sessionId": "session-observed",
            "source": "cli",
            "status": {"type": "idle"},
            "updatedAt": 2,
            "turns": [
                {
                    "id": "turn-observed",
                    "status": "completed",
                    "itemsView": "full",
                    "items": [
                        {
                            "id": "user-original",
                            "type": "userMessage",
                            "content": [{"type": "text", "text": "observable input"}],
                        },
                        {
                            "id": "reasoning-original",
                            "type": "reasoning",
                            "content": ["DO-NOT-CAPTURE-CONTENT"],
                            "summary": ["DO-NOT-CAPTURE-SUMMARY"],
                        },
                        {
                            "id": "command-original",
                            "type": "commandExecution",
                            "command": "fixture command",
                            "commandActions": [],
                            "cwd": "/fixture",
                            "status": "completed",
                            "aggregatedOutput": "observable tool result",
                            "exitCode": 0,
                        },
                        {
                            "id": "phase-unknown",
                            "type": "agentMessage",
                            "text": "no inferred final role",
                            "phase": None,
                        },
                        {
                            "id": "answer-original",
                            "type": "agentMessage",
                            "text": "reported final output",
                            "phase": "final_answer",
                        },
                    ],
                },
                {
                    "id": "other-turn",
                    "status": "completed",
                    "items": [
                        {
                            "id": "other-answer",
                            "type": "agentMessage",
                            "text": "OTHER-HISTORY",
                        }
                    ],
                },
            ],
        }
    }


@unittest.skipUnless(os.name == "posix", "private dirfd storage is POSIX-specific")
class CaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.originals = Path(self.temporary.name).resolve() / "originals"

    async def capture(self, payload=None):
        response = ThreadReadResponse.model_validate(payload or response_payload())
        codex = AsyncCodex()
        reader = AsyncMock(return_value=response)
        with (
            patch.object(codex, "_ensure_initialized", AsyncMock()),
            patch.object(codex._client, "thread_read", reader),
        ):
            try:
                return await sdk_capture.capture_completed_turn(
                    AsyncThread(codex, "thread-observed"),
                    turn_id="turn-observed",
                    originals=self.originals,
                )
            finally:
                reader.assert_awaited_once_with("thread-observed", include_turns=True)

    async def test_real_sdk_read_retains_typed_identity_and_excludes_other_payloads(
        self,
    ):
        receipt = await self.capture()
        raw = (self.originals / receipt["source_sha256"]).read_bytes()
        value = json.loads(raw)
        self.assertEqual(receipt["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            value["thread"],
            {
                "id": "thread-observed",
                "sessionId": "session-observed",
                "cliVersion": "fixture-runtime",
                "modelProvider": "reported-provider-only",
            },
        )
        source_items = response_payload()["thread"]["turns"][0]["items"]
        self.assertEqual(
            value["items"],
            [
                {
                    "source_index": index,
                    "item_id": source_items[index]["id"],
                    "type": source_items[index]["type"],
                    "sdk_payload": source_items[index],
                }
                for index in (0, 2, 3, 4)
            ],
        )
        self.assertEqual(
            value["omitted_items"],
            [{"source_index": 1, "item_id": "reasoning-original", "type": "reasoning"}],
        )
        self.assertNotIn(b"DO-NOT-CAPTURE", raw)
        self.assertNotIn(b"OTHER-HISTORY", raw)
        self.assertEqual(value["items"][2]["sdk_payload"]["phase"], None)

    async def test_wrong_thread_cannot_publish(self):
        payload = response_payload()
        payload["thread"]["id"] = "other-thread"
        with self.assertRaisesRegex(sdk_capture.CaptureRefused, "^wrong_thread$"):
            await self.capture(payload)
        self.assertFalse(self.originals.exists())

    async def test_missing_or_duplicated_selected_turn_cannot_publish(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                payload = response_payload()
                turns = payload["thread"]["turns"]
                payload["thread"]["turns"] = (
                    [turns[1]] if not duplicate else [turns[0], copy.deepcopy(turns[0])]
                )
                with self.assertRaisesRegex(
                    sdk_capture.CaptureRefused, "^turn_not_unique$"
                ):
                    await self.capture(payload)
        self.assertFalse(self.originals.exists())

    async def test_unfinished_or_partial_turn_cannot_publish(self):
        for status, view, code in (
            ("inProgress", "full", "turn_not_completed"),
            ("interrupted", "full", "turn_not_completed"),
            ("failed", "full", "turn_not_completed"),
            ("completed", "summary", "items_not_full"),
            ("completed", "notLoaded", "items_not_full"),
        ):
            with self.subTest(status=status, view=view):
                payload = response_payload()
                payload["thread"]["turns"][0].update(status=status, itemsView=view)
                with self.assertRaisesRegex(
                    sdk_capture.CaptureRefused, "^" + code + "$"
                ):
                    await self.capture(payload)
        self.assertFalse(self.originals.exists())

    async def test_duplicate_identity_including_omitted_item_is_refused(self):
        payload = response_payload()
        payload["thread"]["turns"][0]["items"][1]["id"] = "user-original"
        with self.assertRaisesRegex(
            sdk_capture.CaptureRefused, "^duplicate_item_identity$"
        ):
            await self.capture(payload)

    async def test_identical_capture_is_create_only_and_private(self):
        first = await self.capture()
        path = self.originals / first["source_sha256"]
        before = path.stat()
        second = await self.capture()
        self.assertEqual(second, {**first, "created": False})
        self.assertTrue(first["created"])
        self.assertEqual(path.stat().st_ino, before.st_ino)
        self.assertEqual(stat.S_IMODE(before.st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.originals.stat().st_mode), 0o700)
        self.assertEqual(list(self.originals.iterdir()), [path])

    async def test_existing_different_bytes_are_never_overwritten(self):
        first = await self.capture()
        path = self.originals / first["source_sha256"]
        changed = b"!" + path.read_bytes()[1:]
        path.write_bytes(changed)
        with self.assertRaisesRegex(
            sdk_capture.CaptureRefused, "^original_bytes_or_metadata_differ$"
        ):
            await self.capture()
        self.assertEqual(path.read_bytes(), changed)

    async def test_digest_slot_symlink_fifo_and_directory_are_refused(self):
        first = await self.capture()
        path = self.originals / first["source_sha256"]
        raw = path.read_bytes()
        target = self.originals.parent / "target"
        target.write_bytes(raw)
        for kind in ("symlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                path.unlink()
                if kind == "symlink":
                    path.symlink_to(target)
                    with self.assertRaises(OSError) as raised:
                        await self.capture()
                    self.assertEqual(raised.exception.errno, errno.ELOOP)
                else:
                    os.mkfifo(path, 0o600) if kind == "fifo" else path.mkdir()
                    with self.assertRaisesRegex(
                        sdk_capture.CaptureRefused,
                        "^private_regular_original_required$",
                    ):
                        await self.capture()
                path.rmdir() if kind == "directory" else path.unlink()
                path.write_bytes(raw)
                path.chmod(0o600)
        self.assertEqual(target.read_bytes(), raw)

    async def test_private_directory_and_each_path_component_are_required(self):
        self.originals.mkdir(mode=0o755)
        self.originals.chmod(0o755)
        with self.assertRaisesRegex(
            sdk_capture.CaptureRefused, "^private_originals_directory_required$"
        ):
            await self.capture()
        self.originals.rmdir()
        parent = self.originals.parent / "real-parent"
        parent.mkdir(mode=0o700)
        link = self.originals.parent / "parent-link"
        link.symlink_to(parent, target_is_directory=True)
        self.originals = link / "originals"
        with self.assertRaises(OSError):
            await self.capture()
        self.assertFalse((parent / "originals").exists())

    async def test_actual_rewrite_during_readback_is_refused(self):
        first = await self.capture()
        path = self.originals / first["source_sha256"]
        raw = path.read_bytes()
        original_read, changed = os.read, False

        def rewrite_after_read(fd, count):
            nonlocal changed
            data = original_read(fd, count)
            if not changed:
                changed = True
                path.write_bytes(b"!" + raw[1:])
                path.write_bytes(raw)
                os.utime(path, ns=(1, 2))
            return data

        with patch.object(sdk_capture.os, "read", rewrite_after_read):
            with self.assertRaisesRegex(
                sdk_capture.CaptureRefused, "^original_bytes_or_metadata_differ$"
            ):
                await self.capture()
        self.assertTrue(changed)
        self.assertEqual(path.read_bytes(), raw)

    async def test_oversized_source_is_refused_without_truncation(self):
        payload = response_payload()
        payload["thread"]["turns"][0]["items"][-1]["text"] = "x" * 1_048_577
        with self.assertRaisesRegex(sdk_capture.CaptureRefused, "^source_too_large$"):
            await self.capture(payload)
        self.assertFalse(self.originals.exists())


@unittest.skipUnless(os.name == "posix", "private dirfd storage is POSIX-specific")
class CommandLineCallerTest(unittest.TestCase):
    def test_cli_calls_existing_sdk_read_with_explicit_ids(self):
        codex = AsyncCodex()
        reader = AsyncMock(
            return_value=ThreadReadResponse.model_validate(response_payload())
        )
        with tempfile.TemporaryDirectory() as temporary:
            originals = Path(temporary).resolve() / "originals"
            output = io.StringIO()
            arguments = [
                "sdk_capture",
                "--thread-id",
                "thread-observed",
                "--turn-id",
                "turn-observed",
                "--originals",
                str(originals),
            ]
            with (
                patch("sys.argv", arguments),
                patch.object(sdk_capture, "AsyncCodex", return_value=codex),
                patch.object(codex, "_ensure_initialized", AsyncMock()),
                patch.object(codex, "close", AsyncMock()),
                patch.object(codex._client, "thread_read", reader),
                contextlib.redirect_stdout(output),
            ):
                sdk_capture.main()
            reader.assert_awaited_once_with("thread-observed", include_turns=True)
            receipt = json.loads(output.getvalue())
            self.assertTrue((originals / receipt["source_sha256"]).is_file())
            self.assertNotIn("observable input", output.getvalue())


if __name__ == "__main__":
    unittest.main()
