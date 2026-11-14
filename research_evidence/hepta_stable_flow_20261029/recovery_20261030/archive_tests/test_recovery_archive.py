"""Small synthetic integrity fixtures, not neural-model experiments.

The primary SHA constant is patched only in these in-memory test fixtures.
Opaque fixture payloads exercise archive identity and audit enforcement;
scientific artifact validation remains the independent recovery audit's job.
"""

import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "recovery_archive.py"
SPEC = importlib.util.spec_from_file_location("recovery_archive", SOURCE)
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


class RecoveryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-archive-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for name in A.SCOPE:
            self.write(name + "/fixture.txt", b"synthetic fixture, not scientific data\n")
        predictions, comparisons = [], []
        for task in ("selective_copy", "mqar"):
            for arm in ("analytic", "matched_c1", "sigmoid", "ordinary", "frozen_flow"):
                for seed in (81301, 81302, 81303):
                    for regime in ("cpu30", "updates384"):
                        name = f"predictions/fixture_{len(predictions):02d}.npz"
                        record = self.write(A.P + "/" + name, name.encode())
                        predictions.append({"task": task, "arm": arm, "seed": seed, "regime": regime, "prediction_file": name, "prediction_sha256": record["sha256"]})
                        comparisons.append({**record, "exact_match": True, "reconstructed_sha256": record["sha256"]})
        primary = self.write(A.PRIMARY_RESULT, {"results": predictions})
        comparisons.append({**primary, "exact_match": True, "reconstructed_sha256": primary["sha256"]})
        self.digest_patch = patch.object(A, "PRIMARY_SHA", primary["sha256"])
        self.digest_patch.start()
        self.addCleanup(self.digest_patch.stop)
        self.write(A.PRIMARY, {"all_original_primary_digests_reproduced": True, "original_inputs_unchanged": True, "training_or_selection_executed": False, "comparisons": comparisons})
        records = []
        for i in range(24):
            folder = f"execution/checkpoint_{i:03d}"
            raw = self.write(A.N + "/" + folder + "/raw.npz", f"raw {i}".encode())
            receipt = self.write(A.N + "/" + folder + "/receipt.json", {"fixture": True, "scientific_gate_passed": False})
            row = {"folder": folder, "checkpoint_unchanged": True, "receipt_sha256": receipt["sha256"], "raw_artifacts_sha256": {"raw.npz": raw["sha256"]}}
            if i < 8:
                row["independent_flow"] = {"status": "failed"}
            records.append(row)
        self.write(A.N + "/execution/summary.json", {"registered_aliases": 24, "physical_checkpoints": 24, "dop_aliases": 8, "dop_physical_checkpoints": 8, "execution_errors": 0, "primary_scores_or_selection_modified": False, "test_data_or_scores_read": False, "records": records})
        aliases = [r for r in predictions if r["seed"] == 81301]
        cases = [{"case_id": f"physical_{i:03d}_batch_{batch}", "physical_index": i, "batch_size": batch, "aliases": [alias]} for i, alias in enumerate(aliases) for batch in (1, 32)]
        events = [{"case_index": i, "case_id": case["case_id"], "repetition": rep, "position": i, "cpu_nanoseconds": 11, "wall_nanoseconds": 12} for rep in range(11) for i, case in enumerate(cases)]
        event_file = self.write(A.T + "/execution/raw_events.jsonl", "".join(json.dumps(e) + "\n" for e in events).encode())
        times = self.write(A.T + "/execution/raw_times.npz", b"opaque fixture timing bytes")
        plan = self.write(A.T + "/execution/plan.json", {"fixture": True})
        self.write(A.T + "/execution/summary.json", {"status": "complete", "alias_count": 20, "physical_checkpoint_count": 20, "case_count": 40, "timed_repetitions_per_case": 11, "warmups_per_case": 3, "cases": cases, "raw_times_sha256": times["sha256"], "raw_events_sha256": event_file["sha256"], "execution_plan_sha256": plan["sha256"]})
        report_output = self.write(str(Path(A.REPORT).parent / "report.html"), b"<p>Integrity fixture only.</p>")
        self.write(A.REPORT, {"consumed_inputs": [primary], "outputs": [{**report_output, "path": "report.html"}]})
        self.audit = {"status": "complete", "artifact_integrity_passed": True, "all_research_blockers_closed": False, "original_archive_recovered": False, "bound_artifacts": A.inventory(self.root)}
        self.write(A.AUDIT, self.audit)
        self.output = self.root / A.E / "releases/fixture.tar.gz"

    def write(self, name, value):
        data = value if isinstance(value, bytes) else A.encoded(value)
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": name, "bytes": len(data), "sha256": A.sha(data)}

    def repack(self, mode):
        destination = self.output.with_name(mode + ".tar.gz")
        with tarfile.open(self.output, "r:gz") as source, tarfile.open(destination, "w:gz", format=tarfile.GNU_FORMAT) as target:
            members = [(copy.copy(m), source.extractfile(m).read()) for m in source]
            for index, (member, data) in enumerate(members):
                if mode == "missing" and index == len(members) - 1:
                    continue
                if mode == "tamper" and index == 1:
                    data = bytes([data[0] ^ 1]) + data[1:]
                if mode == "unsafe" and index == 0:
                    manifest = json.loads(data)
                    manifest["files"][0]["path"] = "../escaped"
                    data = A.encoded(manifest)
                    member.size = len(data)
                target.addfile(member, io.BytesIO(data))
                if mode == "duplicate" and index == 1:
                    target.addfile(member, io.BytesIO(data))
        return destination

    def test_roundtrip_determinism_and_no_overwrite(self):
        first = A.create(self.root, self.output)
        other = self.output.with_name("second.tar.gz")
        second = A.create(self.root, other)
        self.assertEqual(first["archive_sha256"], second["archive_sha256"])
        self.assertFalse(first["all_research_blockers_closed"])
        self.assertFalse(first["original_archive_recovered"])
        extracted = self.root / "extracted"
        with tarfile.open(self.output, "r:gz") as archive:
            archive.extractall(extracted, filter="data")
        self.assertEqual(A.verify_tree(extracted)["file_count"], first["file_count"])
        (extracted / "unexpected.txt").write_text("extra")
        with self.assertRaisesRegex(ValueError, "file set differs"):
            A.verify_tree(extracted)
        with self.assertRaisesRegex(ValueError, "overwrite"):
            A.create(self.root, self.output)

    def test_archive_rejects_tamper_missing_duplicate_and_unsafe_paths(self):
        A.create(self.root, self.output)
        for mode in ("tamper", "missing", "duplicate", "unsafe"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                A.verify(self.repack(mode))

    def test_final_audit_gate_and_critical_binding_required(self):
        for change in (
            {"status": "pending"}, {"artifact_integrity_passed": False},
            {"bound_artifacts": []}, {"all_research_blockers_closed": True},
            {"bound_artifacts": [r for r in self.audit["bound_artifacts"] if r["path"] != A.REPORT]},
        ):
            self.write(A.AUDIT, {**self.audit, **change})
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                A.create(self.root, self.output)
            self.assertFalse(self.output.exists())

    def test_missing_bound_artifact_prevents_creation(self):
        (self.root / A.P / "predictions/fixture_00.npz").unlink()
        with self.assertRaises(ValueError):
            A.create(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_changed_bound_artifact_prevents_creation(self):
        self.write(A.P + "/predictions/fixture_00.npz", b"altered")
        with self.assertRaisesRegex(ValueError, "Binding changed"):
            A.create(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_symlink_and_output_recursion_rejected(self):
        link = self.root / A.SCOPE[0] / "outside-link"
        link.symlink_to(self.root / A.REPORT)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            A.inventory(self.root)
        link.unlink()
        with self.assertRaisesRegex(ValueError, "own inventory"):
            A.create(self.root, self.root / A.E / "recursive.tar.gz")


if __name__ == "__main__":
    unittest.main()
