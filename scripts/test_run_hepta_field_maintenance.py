#!/usr/bin/env python3
"""Small local boundary tests; no Cargo, Bazel, schema writer, or model execution."""

import copy
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import run_hepta_field_maintenance as maintenance


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def output(self):
        out = self.root / "out"
        out.mkdir()
        (out / "payload").mkdir()
        (out / "delivery").mkdir()
        return out

    def locks(self):
        old = {"version": 4, "package": []}
        for name, versions in maintenance.TLS.items():
            old["package"].append(
                {
                    "name": name,
                    "version": versions[0],
                    "checksum": "old",
                    "source": "registry+https://github.com/rust-lang/crates.io-index",
                }
            )
        old["package"].append(
            {
                "name": "consumer",
                "version": "1.0",
                "dependencies": ["rustls 0.23.45", "rustls-webpki"],
            }
        )
        new = copy.deepcopy(old)
        for package in new["package"]:
            if package["name"] in maintenance.TLS:
                package["version"] = maintenance.TLS[package["name"]][1]
                package["checksum"] = "new"
        new["package"][-1]["dependencies"][0] = "rustls 0.23.46"
        return old, new

    def compressed(self, data):
        zstd = ctypes.CDLL(ctypes.util.find_library("zstd"))
        zstd.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        zstd.ZSTD_compressBound.restype = ctypes.c_size_t
        zstd.ZSTD_compress.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        zstd.ZSTD_compress.restype = ctypes.c_size_t
        capacity = zstd.ZSTD_compressBound(len(data))
        target = ctypes.create_string_buffer(capacity)
        size = zstd.ZSTD_compress(target, capacity, data, len(data), 1)
        path = self.root / "generated.json.zst"
        path.write_bytes(target.raw[:size])
        return path

    def exports(self):
        return {
            "typescript": {"v2/Tiny.ts": "export type Tiny = string;\n"},
            "json_schema": {"Tiny.json": "{}\n"},
            "internal_json_schema": {},
        }

    def test_exact_tls_scope_and_version_references(self):
        before, after = self.locks()
        unchanged = copy.deepcopy(before)
        maintenance.validate_tls(before, after)
        self.assertEqual(before, unchanged)

    def test_unapproved_resolver_changes_fail(self):
        before, after = self.locks()
        mutations = [
            lambda doc: doc["package"].append({"name": "transitive", "version": "2"}),
            lambda doc: doc["package"][-1].update(checksum="changed"),
            lambda doc: doc["package"][-1]["dependencies"].append("unapproved"),
            lambda doc: doc.update(version=3),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(after)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                maintenance.validate_tls(before, changed)

    def test_exact_tls_inventory_cannot_be_removed_or_rebound(self):
        before, after = self.locks()
        mutations = [
            lambda doc: doc["package"].pop(0),
            lambda doc: doc["package"].append(copy.deepcopy(doc["package"][0])),
            lambda doc: doc["package"][0].update(source="git+unapproved"),
            lambda doc: doc["package"][0].update(version="0.23.47"),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(after)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                maintenance.validate_tls(before, changed)

    def test_later_exact_update_uses_actual_intermediate_lock_identity(self):
        out = self.output()
        (out / "payload/before").mkdir()
        (self.root / "codex-rs").mkdir()
        before, after = self.locks()
        state = copy.deepcopy(before)
        lock = self.root / maintenance.LOCKS[0]

        def encode(document):
            parts = ["version = 4"]
            for package in document["package"]:
                parts.append("[[package]]")
                parts.extend(
                    f"{key} = {json.dumps(value)}" for key, value in package.items()
                )
            return "\n".join(parts) + "\n"

        lock.write_text(encode(before))
        (out / "payload/before/Cargo.lock").write_text(encode(before))
        observed = []

        def fake_command(rec, output, root, label, argv, **kwargs):
            if argv[:2] == ["cargo", "update"]:
                spec, target = argv[3], argv[5]
                name, version = spec.split("@")
                current = next(p for p in state["package"] if p["name"] == name)
                self.assertEqual(current["version"], version)
                observed.append(spec)
                current["version"], current["checksum"] = target, "new"
                if name == "rustls":
                    webpki = next(
                        p for p in state["package"] if p["name"] == "rustls-webpki"
                    )
                    webpki["version"] = maintenance.TLS["rustls-webpki"][1]
                    state["package"][-1]["dependencies"] = after["package"][-1][
                        "dependencies"
                    ]
                lock.write_text(encode(state))
            return ""

        rec = {"mode": "locks", "generation_passed": False}
        with patch.object(maintenance, "command", side_effect=fake_command):
            maintenance.execute(self.root, out, rec)
        self.assertEqual(observed[1], "rustls-webpki@0.103.16")
        self.assertTrue(rec["generation_passed"])

    def test_paths_reject_traversal_and_platform_aliases(self):
        for name in (
            "",
            ".",
            "..",
            "a/../b",
            "/absolute",
            "a//b",
            "a/./b",
            "C:/x",
            "a\\b",
            "bad\0path",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                maintenance.safe_name(name)
        self.assertEqual(str(maintenance.safe_name("v2/Tiny.ts")), "v2/Tiny.ts")

    def test_inventory_rejects_links_and_byte_file_count_caps(self):
        tree = self.root / "tree"
        tree.mkdir()
        (tree / "a").write_bytes(b"12345")
        with patch.object(maintenance, "FILE_CAP", 4), self.assertRaises(ValueError):
            maintenance.inventory(tree)
        (tree / "b").write_bytes(b"x")
        with patch.object(maintenance, "RAW_CAP", 5), self.assertRaises(ValueError):
            maintenance.inventory(tree)
        with patch.object(maintenance, "FILE_COUNT", 1), self.assertRaises(ValueError):
            maintenance.inventory(tree)
        (tree / "link").symlink_to(tree / "a")
        with self.assertRaises(ValueError):
            maintenance.inventory(tree)

    def test_fresh_bundle_literal_expansion_and_no_overwrite(self):
        raw = json.dumps(self.exports()).encode()
        bundle = self.compressed(raw)
        destination = self.root / "experimental"
        with patch.object(maintenance, "FILE_CAP", 65536):
            result = maintenance.expand_bundle(bundle, destination)
            self.assertEqual(result["decoded_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(
                (destination / "typescript/v2/Tiny.ts").read_bytes(),
                b"export type Tiny = string;\n",
            )
            with self.assertRaises(FileExistsError):
                maintenance.expand_bundle(bundle, destination)

    def test_bundle_rejects_unsafe_and_nonstring_exports_before_writes(self):
        for path, value in (
            ("../escape.ts", "x"),
            ("C:/escape.ts", "x"),
            ("v2/Tiny.ts", 7),
        ):
            exports = self.exports()
            exports["typescript"] = {path: value}
            bundle = self.compressed(json.dumps(exports).encode())
            destination = self.root / "unwritten"
            with (
                patch.object(maintenance, "FILE_CAP", 65536),
                self.assertRaises(ValueError),
            ):
                maintenance.expand_bundle(bundle, destination)
            self.assertFalse(destination.exists())

    def test_bundle_rejects_duplicate_json_and_decompression_bomb(self):
        for raw in (
            b'{"typescript":{},"typescript":{},"json_schema":{},"internal_json_schema":{}}',
            b"x" * 70000,
        ):
            bundle = self.compressed(raw)
            with (
                patch.object(maintenance, "FILE_CAP", 65536),
                self.assertRaises(ValueError),
            ):
                maintenance.expand_bundle(bundle, self.root / "unwritten")
            self.assertFalse((self.root / "unwritten").exists())

    def test_archive_manifest_and_deterministic_literal_members(self):
        out = self.output()
        (out / "payload/bytes.bin").write_bytes(bytes(range(256)))
        rec = {"source_head": "a" * 40}
        maintenance.package(out, rec, {"evidence": out / "payload"})
        first = (out / "delivery/maintenance.tar.gz").read_bytes()
        os.utime(out / "payload/bytes.bin", (100, 200))
        maintenance.package(out, rec, {"evidence": out / "payload"})
        self.assertEqual(first, (out / "delivery/maintenance.tar.gz").read_bytes())
        manifest = json.loads((out / "delivery/MANIFEST.json").read_text())
        with tarfile.open(out / "delivery/maintenance.tar.gz") as archive:
            self.assertEqual(
                set(archive.getnames()), {"MANIFEST.json", *manifest["files"]}
            )
            for name, expected in manifest["files"].items():
                data = archive.extractfile(name).read()
                self.assertEqual(
                    {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                    expected,
                )

    def test_archive_rejects_raw_and_compressed_caps(self):
        out = self.output()
        (out / "payload/tiny").write_bytes(b"a")
        for name, value in (("RAW_CAP", 1024), ("ARCHIVE_CAP", 1)):
            with patch.object(maintenance, name, value), self.assertRaises(ValueError):
                maintenance.package(
                    out, {"source_head": "a" * 40}, {"evidence": out / "payload"}
                )
            self.assertFalse((out / "delivery/maintenance.tar.gz").exists())

    def test_command_failure_retains_real_exit_and_checkpoint(self):
        out = self.output()
        rec = {"commands": []}
        with self.assertRaises(RuntimeError):
            maintenance.command(
                rec,
                out,
                self.root,
                "tiny_failure",
                [sys.executable, "-c", "import sys; print('fixture'); sys.exit(7)"],
                timeout=5,
                limit=128,
            )
        stored = json.loads((out / "delivery/receipt.json").read_text())
        self.assertEqual(stored["commands"][0]["exit_code"], 7)
        self.assertEqual(stored["phase"], "tiny_failure_finished")
        self.assertEqual(
            (out / "payload/tiny_failure.stdout.log").read_bytes(), b"fixture\n"
        )

    def test_unexpected_worktree_change_still_retains_actual_locks(self):
        out = self.output()
        (self.root / "codex-rs").mkdir()
        for name in maintenance.LOCKS:
            (self.root / name).write_bytes(b"actual failed attempt\n")
        rec = {"source_head": "a" * 40, "mode": "locks", "generation_passed": False}
        with patch.object(maintenance, "git", return_value=" M unapproved.txt\n"):
            maintenance.finalize(self.root, out, rec, "failure")
        self.assertFalse(rec["generation_passed"])
        self.assertIn("unexpected worktree", rec["finalize_error"])
        with tarfile.open(out / "delivery/maintenance.tar.gz") as archive:
            for name in maintenance.LOCKS:
                member = "evidence/after/" + Path(name).name
                self.assertEqual(
                    archive.extractfile(member).read(), b"actual failed attempt\n"
                )

    def test_oversized_generated_tree_keeps_failure_logs_in_fallback(self):
        out = self.output()
        (out / "generated").mkdir()
        (out / "generated/padding.json").write_bytes(b"x" * 18000)
        (out / "payload/failure.stderr.log").write_bytes(b"real diagnostic\n")
        rec = {"source_head": "a" * 40, "mode": "schemas", "generation_passed": False}
        with (
            patch.object(maintenance, "git", return_value=""),
            patch.object(maintenance, "RAW_CAP", 20480),
        ):
            maintenance.finalize(self.root, out, rec, "failure")
        self.assertFalse(rec["generation_passed"])
        self.assertEqual(rec["generated_outputs_omitted_from_fallback"], ["generated"])
        with tarfile.open(out / "delivery/maintenance.tar.gz") as archive:
            self.assertNotIn("generated/padding.json", archive.getnames())
            self.assertEqual(
                archive.extractfile("evidence/failure.stderr.log").read(),
                b"real diagnostic\n",
            )

    def test_lock_copy_rejects_source_symlinks(self):
        (self.root / "codex-rs").mkdir()
        (self.root / "actual").write_bytes(b"bytes")
        (self.root / "codex-rs/Cargo.lock").symlink_to(self.root / "actual")
        with self.assertRaises(ValueError):
            maintenance.copy_locks(self.root, self.root / "copies")

    def test_initialize_refuses_other_events_before_creating_output(self):
        out = self.root / "unwritten"
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": maintenance.BRANCH},
        ):
            with self.assertRaises(ValueError):
                maintenance.initialize(self.root, out, "locks")
        self.assertFalse(out.exists())

    def test_clean_worktree_does_not_accept_a_different_final_commit(self):
        out = self.output()
        rec = {
            "source_head": "a" * 40,
            "source_tree": "b" * 40,
            "mode": "schemas",
            "generation_passed": True,
        }
        actual = "c" * 40 + "\n" + "d" * 40 + "\n"
        with patch.object(maintenance, "git", side_effect=[actual, ""]):
            maintenance.finalize(self.root, out, rec, "success")
        self.assertTrue(rec["worktree_clean_after"])
        self.assertFalse(rec["source_identity_unchanged"])
        self.assertFalse(rec["generation_passed"])
        self.assertEqual(rec["source_identity_after"], actual.splitlines())
        self.assertIn("commit/tree differs", rec["finalize_error"])


if __name__ == "__main__":
    unittest.main()
