"""Pinned TRAIN-only container replay without model or outcome dependencies."""

import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from long_document_sources import canonical, sha
from operational_region_evidence import load_training_evidence, prepared_text_proof
from operational_source_regions import REGRESSION_PREFIX


def fixture(root):
    prepared, features = root / "prepared", root / "features"
    prepared.mkdir(); features.mkdir()
    view = "TEST SOURCE tests.py\ndef test_value():\n    assert value\n"
    context = "IMPLEMENTATION code.py\nvalue=0\n"
    case = {"commands": [{"runner": "pytest", "args": ["tests.py"], "view": {"text": view}}],
            "implementation": {"contexts": {"base": context, "candidate": context.replace("0", "1")}, "diff": "unused"}}
    case_raw = canonical(case)
    (prepared / "case.json").write_bytes(case_raw)
    manifest_raw = canonical({"before_any_upstream_test_execution": True,
        "cases": {"case.json": {"group_id": "group-train", "sha256": sha(case_raw), "bytes": len(case_raw)}}})
    (prepared / "manifest.json").write_bytes(manifest_raw)
    text = REGRESSION_PREFIX + "COMMAND pytest tests.py\n" + context + "\n" + view
    rows = [{"source_id": "row-" + split, "group_id": "group-" + split, "split": split, "repo": "youtube-dl",
        "labels": {"unused": int(split == "holdout")}, "text": text, "source_version": {"prepared_case_sha256": sha(case_raw)},
        "text_utf8_sha256": sha(text.encode()), "text_utf8_bytes": len(text.encode())} for split in ("train", "holdout")]
    dataset = root / "dataset.json"
    dataset.write_bytes(canonical({"rows": rows, "prepared_manifest_sha256": sha(manifest_raw)}))
    documents, source_digests = [], []
    for row in rows:
        core = {"source_utf8_sha256": sha(text.encode()), "source_utf8_bytes": len(text.encode()),
            "source_characters": len(text), "content_tokens": 2, "chunks": [{"content_token_span": [0, 2],
                "char_span": [0, len(text)], "utf8_span": [0, len(text.encode())], "aggregation_weight": 2}]}
        version = "sha256:" + sha(canonical(row["source_version"]))
        document = {**core, "source_id": row["source_id"], "source_version": version,
            "source_version_input": row["source_version"], "document_plan_sha256": sha(canonical(core))}
        documents.append(document)
        source_digests.append(sha(canonical({"event": {"source_id": row["source_id"], "source_version": version,
            "observed_at_ns": 42, "time_start_ms": None, "time_end_ms": None},
            "source_utf8_sha256": sha(text.encode()), "document_plan_sha256": document["document_plan_sha256"]})))
    values = np.asarray([[1, 0], [0, 1]], np.float32)
    np.savez_compressed(features / "features.npz", features=values)
    np.savez_compressed(features / "chunk-features.npz", features=values,
                        document_indices=np.arange(2, dtype=np.int32), chunk_indices=np.zeros(2, np.int32))
    (features / "documents.jsonl.gz").write_bytes(gzip.compress(b"\n".join(canonical(d) for d in documents)))
    (features / "forwards.jsonl").write_bytes(b"{}\n")
    plan = {"dataset_sha256": sha(dataset.read_bytes()), "source_ids": [r["source_id"] for r in rows],
        "document_plan_sha256": [d["document_plan_sha256"] for d in documents],
        "predictor_fields": ["text"], "label_fields_enter_encoder": False, "text_transform": "none",
        "observed_at_ns": 42, "feature_identity": "a" * 64,
        "source_code_sha256": {"long_document_sources.py": sha(Path(__file__).with_name("long_document_sources.py").read_bytes())}}
    (features / "plan.json").write_bytes(canonical(plan))
    (features / "protocol.json").write_bytes(canonical({"schema": "fixture", "predictor_fields": ["text"]}))
    report = {"plan": plan, "feature_identity": "a" * 64, "feature_shape": [2, 2],
              "feature_tensor_sha256": sha(values.tobytes()), "chunk_tensor_sha256": sha(values.tobytes()),
              "source_record_digests": source_digests}
    for key, name in (("feature_archive_sha256", "features.npz"), ("chunk_archive_sha256", "chunk-features.npz"),
                      ("source_span_receipt_sha256", "documents.jsonl.gz"), ("forward_log_sha256", "forwards.jsonl")):
        report[key] = sha((features / name).read_bytes())
    (features / "report.json").write_bytes(canonical(report))
    (features / "manifest.json").write_bytes(canonical({p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
                                                       for p in features.iterdir()}))
    args = {"dataset_sha256": sha(dataset.read_bytes()), "report_sha256": sha((features / "report.json").read_bytes()),
            "training_repositories": ("youtube-dl",)}
    return dataset, features, prepared, args, text, case


class RegionEvidenceTests(unittest.TestCase):
    def test_only_train_rows_reach_immutable_source_bound_views(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset, features, prepared, args, _, _ = fixture(Path(directory))
            bank = load_training_evidence(dataset, features, prepared, **args)
            self.assertEqual([r["source_id"] for r in bank.records()], ["row-train"])
            self.assertNotIn("labels", bank.records()[0])
            np.testing.assert_array_equal(bank.global_features(), [[1, 0]])
            with self.assertRaises(ValueError): bank.chunks(0).setflags(write=True)
            bank.verify_files()

    def test_wrong_source_pin_or_post_capture_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset, features, prepared, args, _, _ = fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "pin"):
                load_training_evidence(dataset, features, prepared, **(args | {"report_sha256": "b" * 64}))
            def mutate(text, case):
                result = prepared_text_proof(text, case)
                dataset.write_bytes(dataset.read_bytes() + b" ")
                return result
            with patch("operational_region_evidence.prepared_text_proof", side_effect=mutate), self.assertRaisesRegex(ValueError, "changed"):
                load_training_evidence(dataset, features, prepared, **args)

    def test_observed_text_or_unprovided_counterpart_cannot_replace_source(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, _, text, case = fixture(Path(directory))
            self.assertFalse(prepared_text_proof(text, case)["outcome_or_selected_role_used"])
            with self.assertRaisesRegex(ValueError, "pre-execution"):
                prepared_text_proof(text.replace("value=0", "observed_result='pass'"), case)


if __name__ == "__main__":
    unittest.main()
