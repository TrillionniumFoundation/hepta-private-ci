"""Adversarial checks for archival Qwen CPU-runtime cost accounting."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

import strong_rag_host_cost_audit as audit


def cpu_record(flags, *, threads=2, model="Test AMD"):
    return {
        "schema": "hepta.memory.runtime-preflight.v1",
        "commands": {
            "lscpu": {
                "returncode": 0,
                "stdout": f"Model name: {model}\nFlags: avx2 {flags}\n",
            }
        },
        "torch": {"intra_op_threads": threads},
    }


def make_zip(destination, *, entries=None, extra=None, corrupt=False, symlink=False):
    entries = entries or {"payload.json": b'{"ok":true}\n'}
    manifest = "".join(
        f"{hashlib.sha256(raw).hexdigest()}  ./{name}\n"
        for name, raw in sorted(entries.items())
    ).encode()
    with zipfile.ZipFile(destination, "w") as out:
        for name, raw in entries.items():
            if symlink:
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                out.writestr(info, raw)
            else:
                out.writestr(name, raw + (b"x" if corrupt else b""))
        out.writestr("SHA256SUMS", manifest)
        if extra:
            out.writestr("unknown.json", b"{}")
    return audit.sha(destination.read_bytes())


class HostCostProvenanceTests(unittest.TestCase):
    def test_native_bf16_instruction_advertisement_and_cpu_id(self):
        for flag in ("avx512_bf16", "amx_bf16"):
            self.assertEqual(
                audit.flags_from_preflight(cpu_record(flag)), (True, "Test AMD")
            )
        self.assertEqual(
            audit.flags_from_preflight(cpu_record("avx2")), (False, "Test AMD")
        )

    def test_unpinned_runtime_or_unsupported_threads_rejected(self):
        for raw in (
            cpu_record("amx_bf16", threads=1),
            cpu_record("amx_bf16", threads=True),
            {**cpu_record("avx2"), "schema": "wrong"},
            {**cpu_record("avx2"), "commands": {}},
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    audit.flags_from_preflight(raw)

    def test_strict_json_rejects_duplicates_and_nonfinite(self):
        self.assertEqual(audit.strict_json(b'{"a":1}'), {"a": 1})
        for payload in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(ValueError):
                audit.strict_json(payload)

    def test_archive_complete_hash_and_census(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "x.zip"
            pin = make_zip(archive)
            body, count = audit.verified_zip(archive, pin)
            self.assertEqual(count, 1)
            self.assertEqual(body, {"payload.json": b'{"ok":true}\n'})
            with self.assertRaisesRegex(ValueError, "outer ZIP"):
                audit.verified_zip(archive, "0" * 64)

    def test_archive_member_replacement_rejected_after_resealing_outer(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "x.zip"
            pin = make_zip(archive, corrupt=True)
            with self.assertRaisesRegex(ValueError, "sealed archive member"):
                audit.verified_zip(archive, pin)

    def test_archive_extras_or_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "x.zip"
            pin = make_zip(archive, extra=True)
            with self.assertRaisesRegex(ValueError, "missing/extra archive member"):
                audit.verified_zip(archive, pin)
            pin = make_zip(archive, symlink=True)
            with self.assertRaisesRegex(ValueError, "unsafe"):
                audit.verified_zip(archive, pin)

    def test_nonexistent_shards_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                audit.audit(Path(temp))

    def test_pinned_original_three_run_replay(self):
        directory = os.environ.get("HEPTA_MEMORY_BF16_COST_ARCHIVES")
        if not directory:
            self.skipTest("Original GitHub Actions ZIPs not provided")
        result = audit.audit(Path(directory))
        self.assertEqual(result["original_model_calls"], 336)
        self.assertEqual(result["distinct_original_prompts"], 112)
        self.assertEqual(result["host_groups"]["reported_native_bf16"]["calls"], 95)
        self.assertEqual(result["host_groups"]["no_reported_native_bf16"]["calls"], 241)
        self.assertEqual(
            result["same_prompt_cross_host"]["matched_prompt_positions"], 77
        )
        self.assertFalse(result["same_prompt_cross_host"]["ratio_is_causal_estimate"])
        self.assertFalse(result["production_accepted"])
        for item in result["per_run"].values():
            self.assertEqual(item["entity_time_correct"], 8)
            self.assertEqual(item["organized_correct"], 8)
            self.assertEqual(item["entity_time_input_tokens"], 5752)
            self.assertEqual(item["organized_input_tokens"], 5179)


if __name__ == "__main__":
    unittest.main()
