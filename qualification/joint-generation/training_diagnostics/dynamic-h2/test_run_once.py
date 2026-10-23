"""Opaque archive and one-shot failure fixtures; no real data, model or timing."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("h2_worker", Path(__file__).with_name("run_once.py"))
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


def fixture(root):
    protocol = {"models": [], "controllers": [], "cost": {"reference_full_cpu_ns": 7.,
        "historical_NC_build_cpu_seconds": 8., "historical_N_build_cpu_seconds": 6.}}
    blobs, selected = {}, []
    for seed in w.SEEDS:
        for role, system in (("NC", "ndu_control"), ("N", "ndu")):
            name = f"{system}-{seed}.npz"
            payload = ("opaque-" + name).encode()
            digest = hashlib.sha256(payload).hexdigest()
            blobs[name] = payload
            row = {"role": role, "seed": seed, "member": name, "sha256": digest,
                   "model_digest": "opaque-" + name, "updates": seed}
            protocol["models"].append(row)
            choice = {"system": system, "seed": seed, "model_file": name, "model_sha256": digest,
                      "model_digest": row["model_digest"], "updates": seed}
            if role == "NC":
                head = f"head-{seed}.npz"
                blobs[head] = head.encode()
                head_sha = hashlib.sha256(blobs[head]).hexdigest()
                protocol["controllers"].append({"seed": seed, "member": head, "sha256": head_sha})
                choice.update(controller_file=head, controller_sha256=head_sha)
            selected.append(choice)
    blobs["build/native.so"] = b"opaque native bytes, never loaded"
    blobs["selection.json"] = json.dumps({"selected": selected,
        "common": {"reference_full_cpu_ns": 7.},
        "system_cost": {"ndu_control": {"cpu_seconds": 8.}, "ndu": {"cpu_seconds": 6.}},
        "validation_canary_not_for_persistence": "forbidden-statistics-canary"}).encode()
    archive, index = root / "archive.tar.gz", root / "index.json"
    with tarfile.open(archive, "w:gz") as tar:
        for name, payload in blobs.items():
            info = tarfile.TarInfo(name); info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    index.write_text(json.dumps({"files": {name: {"bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest()} for name, payload in blobs.items()}}))
    protocol["archive"] = {"path": archive.name, "sha256": w.sha(archive),
        "original_files_path": index.name, "original_files_sha256": w.sha(index),
        "selection_member": "selection.json", "selection_sha256": hashlib.sha256(blobs["selection.json"]).hexdigest()}
    protocol["native_library"] = {"archive_member": "build/native.so", "sha256": hashlib.sha256(blobs["build/native.so"]).hexdigest()}
    return protocol


class BoundaryTests(unittest.TestCase):
    def test_opaque_restore_binds_all_members_and_does_not_export_selection_statistics(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); out = root / "out"; out.mkdir()
            protocol = fixture(root)
            with patch.object(w, "ROOT", root):
                restored = w.safe_restore(protocol, out)
            self.assertEqual(len(restored), 10)
            self.assertFalse((out / "reused-t11/selection.json").exists())
            self.assertNotIn("forbidden-statistics-canary", (out / "T11-binding.json").read_text())
            self.assertEqual(json.loads((out / "T11-binding.json").read_text())["complete_build_cpu_seconds"], {"NC": 8., "N": 6.})

    def test_historical_build_constant_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); out = root / "out"; out.mkdir()
            protocol = fixture(root)
            protocol["cost"]["historical_NC_build_cpu_seconds"] = 8.1
            with patch.object(w, "ROOT", root), self.assertRaisesRegex(ValueError, "build"):
                w.safe_restore(protocol, out)

    def test_unsettled_work_is_interval_not_a_fabricated_complete_charge(self):
        from independent.accounting import WorkLedger
        ledger = WorkLedger("handmade", total_cap=1000)
        ledger.record("known", units=17)
        attempts = [{"accounting_status": "known_actual", "actual_units": 12,
                     "reserved_operator_units": 99},
                    {"accounting_status": "unsettled", "reserved_operator_units": 80}]
        result = w.accounting_summary(ledger, attempts)
        self.assertFalse(result["accounting_complete"])
        self.assertEqual(result["known_consumed_units"], 17)
        self.assertEqual(result["possible_consumed_units_interval"],
                         {"lower_inclusive": 17, "upper_inclusive": 97})
        self.assertEqual(ledger.consumed_units, 17)
        result = w.accounting_summary(ledger, attempts[:1])
        self.assertTrue(result["accounting_complete"])
        self.assertEqual(result["unsettled_reserved_operator_units_upper_bound"], 0)

    def test_mkdir_failure_consumes_stage_start_and_preserves_original_fault(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); stage = root / "stage"; stage.mkdir()
            out = root / "out"; frozen = stage / "frozen-h2.json"
            frozen.write_text("{}")
            (stage / "protocol.json").write_text("{}")
            real_mkdir = Path.mkdir

            def mkdir(path, *args, **kwargs):
                if path == out:
                    raise PermissionError("handmade pre-import output failure")
                return real_mkdir(path, *args, **kwargs)

            with patch.object(w, "ROOT", root), patch.object(w, "STAGE", stage), \
                 patch.object(w, "OUTPUT", out), \
                 patch.object(w, "source_guard", return_value=({"source_commit": "opaque"}, {})), \
                 patch.object(w, "verify_protected"), patch.object(Path, "mkdir", new=mkdir), \
                 self.assertRaisesRegex(PermissionError, "handmade pre-import"):
                w.collect(frozen)
            self.assertTrue((stage / "START.json").is_file())
            receipt = json.loads((stage / "PARTIAL.json").read_text())
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["error_type"], "PermissionError")
            self.assertEqual(receipt["attempted_calls"], [])
            self.assertEqual(receipt["service_calls"], [])
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
