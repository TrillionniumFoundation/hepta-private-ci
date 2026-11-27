#!/usr/bin/python3
"""Offline helper regressions only: no image, registry or original product test."""

import importlib
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import hashlib

SOURCE = Path(sys.argv.pop(1)).resolve(strict=True)
sys.path.insert(0, str(SOURCE))
common = importlib.import_module("common")
builder = importlib.import_module("build_image")
publisher = importlib.import_module("publish_image")
WANTED = (
    "usr/local/lib/hepta-rbe-openssh/image_prepare.py",
    "usr/local/share/hepta-rbe-openssh/install.json",
    "usr/local/share/hepta-rbe-openssh/tool-test.json",
    "usr/local/lib/hepta-rbe-openssh/tool_supply.py",
    "usr/bin/ssh-keygen",
)


def layer(root, items):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        for name, kind, raw in items:
            item = tarfile.TarInfo(name)
            item.uid = item.gid = 0
            item.mode = 0o444
            if kind == "symlink":
                item.type = tarfile.SYMTYPE
                item.linkname = "elsewhere"
                archive.addfile(item)
            elif kind == "directory":
                item.type = tarfile.DIRTYPE
                item.mode = 0o755
                archive.addfile(item)
            else:
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
    raw = data.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    target = root / "blobs/sha256" / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {
        "digest": "sha256:" + digest,
        "size": len(raw),
        "mediaType": "application/vnd.oci.image.layer.v1.tar",
    }


class OverlayTests(unittest.TestCase):
    def run_layers(self, upper):
        with tempfile.TemporaryDirectory(prefix="rbe-helper-overlay-") as temporary:
            root = Path(temporary)
            original = layer(
                root, [(name, "file", b"old:" + name.encode()) for name in WANTED]
            )
            changed = layer(root, upper)
            return builder.retained_files(root, {"layers": [original, changed]})

    def test_root_opaque_hides_all_lower_receipts(self):
        with self.assertRaises(RuntimeError):
            self.run_layers([(".wh..wh..opq", "file", b"")])

    def test_file_or_symlink_ancestor_hides_lower_receipts(self):
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                self.run_layers(
                    [("usr/local/share/hepta-rbe-openssh", kind, b"blocker")]
                )

    def test_opaque_whiteout_does_not_hide_same_layer_replacements(self):
        upper = [(name, "file", b"new:" + name.encode()) for name in WANTED[1:]]
        upper.append(("usr/local/share/hepta-rbe-openssh/.wh..wh..opq", "file", b""))
        actual = self.run_layers(upper)
        self.assertEqual(actual[WANTED[0]][0], b"old:" + WANTED[0].encode())
        for name in WANTED[1:]:
            self.assertEqual(actual[name][0], b"new:" + name.encode())

    def test_individual_whiteout_still_rejects_missing_receipt(self):
        with self.assertRaises(RuntimeError):
            self.run_layers(
                [("usr/local/share/hepta-rbe-openssh/.wh.install.json", "file", b"")]
            )

    def test_regular_replacement_remains_valid(self):
        actual = self.run_layers([(WANTED[1], "file", b"new-install")])
        self.assertEqual(actual[WANTED[1]][0], b"new-install")
        self.assertEqual(actual[WANTED[0]][0], b"old:" + WANTED[0].encode())


class NoNetworkRegistry(publisher.Registry):
    def __init__(self, location):
        self.prefix = "/v2/" + common.REGISTRY_REPOSITORY + "/"
        self.location, self.calls = location, []

    def request(self, method, path, *, body=None, headers=None):
        self.calls.append((method, path))
        if method == "HEAD":
            return 404, {}, b""
        if method == "POST":
            return 202, {"location": self.location}, b""
        if method == "PUT":
            self.test_digest = "sha256:" + common.sha_file(body)
            return 201, {"docker-content-digest": self.test_digest}, b""
        raise AssertionError("unexpected offline request")


class LocationTests(unittest.TestCase):
    def exercise(self, location):
        registry = NoNetworkRegistry(location)
        with tempfile.TemporaryDirectory(prefix="rbe-helper-location-") as temporary:
            root = Path(temporary)
            raw = b"content-addressed offline test blob"
            digest = hashlib.sha256(raw).hexdigest()
            target = root / "blobs/sha256" / digest
            target.parent.mkdir(parents=True)
            target.write_bytes(raw)
            descriptor = {"digest": "sha256:" + digest, "size": len(raw)}
            registry.blob(descriptor, root)
        return registry

    def test_literal_parent_location_is_rejected_before_put(self):
        prefix = "/v2/" + common.REGISTRY_REPOSITORY + "/blobs/uploads/"
        with self.assertRaises(RuntimeError):
            self.exercise(prefix + "a/../b")

    def test_valid_absolute_and_root_relative_upload_locations(self):
        path = (
            "/v2/"
            + common.REGISTRY_REPOSITORY
            + "/blobs/uploads/owned-id?_state=opaque"
        )
        for location in (path, "https://ghcr.io" + path):
            with self.subTest(location=location):
                registry = self.exercise(location)
                self.assertEqual(
                    [method for method, _ in registry.calls], ["HEAD", "POST", "PUT"]
                )
                self.assertTrue(
                    registry.calls[-1][1].startswith(path + "&digest=sha256%3A")
                )


class FakeChild:
    pid = 12345
    returncode = None

    def __init__(self):
        self.waits = []

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if timeout is None:
            raise RuntimeError(
                "offline harness caught an unbounded wait; no process was launched"
            )
        raise subprocess.TimeoutExpired(["offline-owned-child"], timeout)


class DeadlineTests(unittest.TestCase):
    def test_interrupted_child_uses_only_remaining_hard_deadline(self):
        with tempfile.TemporaryDirectory(prefix="rbe-helper-wait-") as temporary:
            evidence = object.__new__(common.Evidence)
            evidence.root = Path(temporary)
            evidence.logs, evidence.state = [], {"status": "in-progress"}
            evidence.deadline = time.monotonic() + 31
            child = FakeChild()
            with (
                patch.object(common.subprocess, "Popen", return_value=child),
                patch.object(common.os, "killpg"),
                patch.object(common.signal, "setitimer"),
            ):
                with self.assertRaises(Exception):
                    evidence.command(["offline-owned-child"])
            self.assertEqual(len(child.waits), 2)
            self.assertTrue(
                all(value is not None and 0 < value <= 31 for value in child.waits)
            )
            self.assertTrue(evidence.state["terminal_unknown"])
            self.assertFalse(evidence.logs[0]["terminal_confirmed"])
            self.assertFalse(evidence.logs[0]["capture_complete"])

    def test_unknown_terminal_cannot_write_qualified_receipt(self):
        with tempfile.TemporaryDirectory(prefix="rbe-helper-terminal-") as temporary:
            evidence = object.__new__(common.Evidence)
            evidence.root, evidence.mode = Path(temporary), "build"
            evidence.logs = []
            evidence.started = time.monotonic()
            evidence.deadline = evidence.started + 1200
            evidence.state = {
                "status": "image-only-qualified",
                "terminal_unknown": True,
            }
            with patch.object(common.signal, "setitimer"):
                with self.assertRaises(RuntimeError):
                    evidence.finish()
            receipt = json.loads((evidence.root / "receipt.json").read_text())
            self.assertEqual(receipt["status"], "failed-not-qualified")


if __name__ == "__main__":
    unittest.main(verbosity=2)
