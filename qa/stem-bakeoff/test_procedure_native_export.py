"""Real frozen artifacts and adversarial export inputs; no training or native claim."""

import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from procedure_native_export import build_envelopes, export
from procedure_native_format import canonical, sha, verify_weights
from procedure_native_validation import load_frozen_run


EVIDENCE = Path(__file__).parent / "evidence/20261022-procedural-memory-replay"
PLAN = "7c4fc2bb251d1c6f897e336dcc82adad3780511b6f353e7b672dc9fca8f471bf"
RESULT = "84e12378b548dd8f105d8f94881ec3b4ffc1d69bef1155b8398e2413f3caf56b"


class ProcedureNativeExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = {str(path.relative_to(EVIDENCE)): path.read_bytes()
                        for path in EVIDENCE.rglob("*") if path.is_file()}
        cls.valid_run = load_frozen_run(cls.original.__getitem__, PLAN, RESULT)

    def setUp(self):
        self.files = dict(self.original)

    def rewrite_result(self, change):
        result = json.loads(self.files["result.json"])
        change(result)
        self.files["result.json"] = canonical(result)
        return sha(self.files["result.json"])

    def test_real_three_seed_envelopes_have_native_framing_and_original_weights(self):
        members = build_envelopes(self.valid_run)
        for seed in (7, 17, 29):
            prefix = f"seed-{seed}/"
            blob = members[prefix + "head.bundle"]
            pins = json.loads(members[prefix + "pins.json"])
            # Independent offsets follow the native Decoder: five digests,
            # three u64s, eight digests, then the two payload lengths.
            magic = b"HEPTA-CELL-HEAD-BUNDLE-V1\0"
            self.assertTrue(blob.startswith(magic))
            offset = len(magic) + 5 * 32
            self.assertEqual(struct.unpack_from("<QQQ", blob, offset), (1, 0, 384))
            offset += 24
            fields = ("manifest_digest", "weights_digest", "source_frontier_digest",
                      "training_dataset_digest", "calibration_dataset_digest",
                      "training_code_digest", "runtime_tuple_digest", "trained_tensor_digest")
            for field in fields:
                self.assertEqual(blob[offset:offset + 32].hex(), pins[field])
                offset += 32
            manifest_size, weights_size = struct.unpack_from("<QQ", blob, offset)
            offset += 16
            self.assertEqual(len(blob), offset + manifest_size + weights_size)
            self.assertEqual(blob[offset:offset + manifest_size], members[prefix + "manifest.json"])
            self.assertEqual(blob[offset + manifest_size:], self.original[f"head-seed-{seed}/weights.npz"])
            self.assertEqual(sha(blob), pins["artifact_digest"])
            self.assertEqual(members[prefix + "original_manifest.json"],
                             self.original[f"head-seed-{seed}/manifest.json"])
            manifest = json.loads(members[prefix + "manifest.json"])
            original = json.loads(members[prefix + "original_manifest.json"])
            provenance = manifest.pop("procedure_replay_provenance_v1")
            self.assertEqual(manifest, original)
            self.assertEqual(provenance["complete_learning_ancestor_digests"],
                             self.valid_run["learning_ancestor_digests"])
            self.assertEqual(provenance["ancestor_count"], 526)
            self.assertFalse(provenance["source_validation_policy"]["native_expands_or_revalidates_learning_ancestor_closure"])
            self.assertTrue(provenance["source_validation_policy"]["requires_external_current_source_validation"])
            self.assertFalse(pins["production_activation_allowed"])

    def test_actual_heldout_features_and_ordered_sources_are_separately_pinned(self):
        members = build_envelopes(self.valid_run)
        batch = json.loads(members["heldout.batch.json"])
        self.assertEqual(batch["rows"], 64)
        self.assertEqual(len(members["heldout.features.f32le"]), 64 * 384 * 4)
        self.assertEqual(sha(members["heldout.features.f32le"]), batch["input_pins"]["feature_bytes_digest"])
        source_bytes = (b"hepta.cell-head-input-sources.v1\0" + struct.pack("<Q", 64)
                        + b"".join(bytes.fromhex(value) for value in batch["source_record_digests"]))
        self.assertEqual(sha(source_bytes), batch["input_pins"]["source_records_digest"])
        self.assertEqual(batch["maximum_multiply_adds"], 98304)
        self.assertNotIn("observed_classes", batch)
        self.assertEqual(json.loads(members["heldout.scorer.json"])["query_ids"], batch["query_ids"])

    def test_unpinned_plan_and_result_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "plan/result pins"):
            load_frozen_run(self.files.__getitem__, "0" * 64, RESULT)
        self.files["result.json"] += b" "
        with self.assertRaisesRegex(ValueError, "plan/result pins"):
            load_frozen_run(self.files.__getitem__, PLAN, RESULT)

    def test_missing_ancestor_is_rejected_even_when_new_owner_and_result_hashes_agree(self):
        name = "head-seed-7/replay_owner.json"
        owner = json.loads(self.files[name])
        owner["learned_source_digests"].pop()
        self.files[name] = canonical(owner)
        changed_result = self.rewrite_result(lambda result: result["arms"]["head_seed_7"].update(
            owner_manifest_sha256=sha(self.files[name])))
        with self.assertRaisesRegex(ValueError, "complete learning ancestor closure"):
            load_frozen_run(self.files.__getitem__, PLAN, changed_result)

    def test_query_source_reorder_is_rejected_even_with_rebound_encoder_hash(self):
        encoder = json.loads(self.files["encoder_manifest.json"])
        encoder["source_record_digests"][0:2] = encoder["source_record_digests"][0:2][::-1]
        self.files["encoder_manifest.json"] = canonical(encoder)
        changed_result = self.rewrite_result(lambda result: result.update(
            feature_manifest_sha256=sha(self.files["encoder_manifest.json"])))
        with self.assertRaisesRegex(ValueError, "ordered actual query/source-record"):
            load_frozen_run(self.files.__getitem__, PLAN, changed_result)

    def test_frozen_input_file_tamper_is_rejected(self):
        name = next(name for name in self.files if name.startswith("inputs/"))
        self.files[name] += b" "
        with self.assertRaisesRegex(ValueError, "procedure input bytes changed"):
            load_frozen_run(self.files.__getitem__, PLAN, RESULT)

    def rewrite_npz(self, member, transform, compression=zipfile.ZIP_STORED):
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.original["head-seed-7/weights.npz"])) as source:
            with zipfile.ZipFile(output, "w", compression=compression) as target:
                for name in source.namelist():
                    raw = source.read(name)
                    target.writestr(name, transform(raw) if name == member else raw)
        return output.getvalue()

    def test_nonzero_adapter_cannot_enter_native_linear_profile(self):
        weights = self.rewrite_npz("up.weight.npy", lambda raw: raw[:-4] + struct.pack("<f", 1.0))
        with self.assertRaisesRegex(ValueError, "exactly zero up.weight"):
            verify_weights(weights, self.valid_run["heads"][7]["manifest"]["report"])

    def test_finite_parameter_tamper_still_fails_tensor_digest(self):
        weights = self.rewrite_npz("task_head.bias.npy", lambda raw: raw[:-4] + struct.pack("<f", 2.0))
        with self.assertRaisesRegex(ValueError, "trained tensor digest"):
            verify_weights(weights, self.valid_run["heads"][7]["manifest"]["report"])

    def test_nonfinite_and_compressed_weights_are_rejected_by_native_profile(self):
        report = self.valid_run["heads"][7]["manifest"]["report"]
        weights = self.rewrite_npz("task_head.bias.npy", lambda raw: raw[:-4] + struct.pack("<f", float("nan")))
        with self.assertRaisesRegex(ValueError, "finite values"):
            verify_weights(weights, report)
        compressed = self.rewrite_npz("task_head.bias.npy", lambda raw: raw, zipfile.ZIP_DEFLATED)
        with self.assertRaisesRegex(ValueError, "ZIP flags or storage"):
            verify_weights(compressed, report)

    def test_export_writes_once_without_modifying_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "native-export"
            summary = export(EVIDENCE, target, PLAN, RESULT)
            self.assertFalse(summary["native_execution_performed"])
            self.assertFalse(summary["artifact_owner_admission_performed"])
            self.assertEqual(set(summary["seeds"]), {"7", "17", "29"})
            with self.assertRaises(FileExistsError):
                export(EVIDENCE, target, PLAN, RESULT)
        self.assertEqual((EVIDENCE / "result.json").read_bytes(), self.original["result.json"])


if __name__ == "__main__":
    unittest.main()
