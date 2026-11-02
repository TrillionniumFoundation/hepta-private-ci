"""Synthetic contract fixtures only; these are not recovered v6/new AV evidence."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from admission import KNOWN_PRIOR_CAMPAIGNS, V6_COMMIT, strict_json, validate


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.submission = {"schema": "hcsn-frontend-admission.v1", "artifacts": {}}
        self.old = {"source_recording_id": "old-recording", "acquisition_session_id": "old-session",
                    "original_capture_sha256": "a" * 64}
        self.new = {"source_recording_id": "new-recording", "acquisition_session_id": "new-session",
                    "original_capture_sha256": hashlib.sha256(b"new original recording").hexdigest(),
                    "independent_capture": True, "derivation_ancestors": []}
        self.put("original_v6_head", b"synthetic original-v6 head fixture")
        self.put("strong_audio_head", b"synthetic strong-audio head fixture")
        self.protocol = {"campaign": "v6", "minimum_independent_recordings": 1,
                         "head_sha256": {k: self.submission["artifacts"][k]["sha256"] for k in
                                         ("original_v6_head", "strong_audio_head")},
                         "tasks": {"fixture": {"classes": 2, "minimum_av_accuracy": .8,
                                               "minimum_audio_accuracy": .8}}}
        self.put("original_v6_protocol", self.protocol)
        self.catalog = {"campaigns": sorted(KNOWN_PRIOR_CAMPAIGNS), "all_prior_uses_through_v8": True}
        self.ledger = {"campaigns": {c: {"complete": True, "recordings": [self.old]}
                                     for c in self.catalog["campaigns"]}}
        self.history()
        self.new["media"] = self.record("media", b"new original recording")
        self.receipt = {k: self.new[k] for k in ("source_recording_id", "acquisition_session_id", "original_capture_sha256")}
        self.receipt.update(record_kind="independent_recording", recorded_at="2026-11-01T00:00:00Z")
        self.new["acquisition_receipt"] = self.record("receipt", self.receipt)
        self.confirmation()

    def record(self, name, data, commit=V6_COMMIT):
        if not isinstance(data, bytes):
            data = json.dumps(data, sort_keys=True, allow_nan=False).encode()
        path = self.root / name
        path.write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "source_commit": commit,
                "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

    def put(self, role, data):
        self.submission["artifacts"][role] = self.record(role, data)

    def history(self):
        self.put("history_catalog", self.catalog)
        self.put("history_ledger", self.ledger)
        self.put("history_reconciliation", {
            "complete": True, "campaigns": self.catalog["campaigns"],
            "includes_exploration_and_failed_runs": True,
            "artifact_sha256": {k: self.submission["artifacts"][k]["sha256"] for k in
                                ("history_catalog", "history_ledger")}})

    def confirmation(self):
        self.put("confirmation_index", {"recordings": [self.new], "cases": [
            {"task": "fixture", "case_id": "case", "source_recording_id": self.new["source_recording_id"], "label": 1}]})
        for role, head in (("av_evaluation", "original_v6_head"), ("audio_evaluation", "strong_audio_head")):
            self.put(role, {"protocol_sha256": self.submission["artifacts"]["original_v6_protocol"]["sha256"],
                            "confirmation_index_sha256": self.submission["artifacts"]["confirmation_index"]["sha256"],
                            "head_sha256": self.submission["artifacts"][head]["sha256"],
                            "predictions": [{"task": "fixture", "case_id": "case",
                                             "source_recording_id": self.new["source_recording_id"],
                                             "label": 1, "probabilities": [.1, .9]}]})

    def result(self):
        return validate(self.submission, self.root)

    def rejected(self, fragment):
        result = self.result()
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(fragment in e for e in result["errors"]), result["errors"])

    def test_fully_bound_synthetic_fixture_passes_contract_only(self):
        result = self.result()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["production_authorized"])

    def test_missing_assets_and_null_metadata_fail_closed(self):
        self.submission = {"schema": "hcsn-frontend-admission.v1", "artifacts": None}
        self.rejected("missing artifact")

    def test_original_v3_head_cannot_substitute_for_original_v6(self):
        self.submission["artifacts"]["original_v6_head"]["source_commit"] = "1" * 40
        self.rejected("original v6 commit")

    def test_missing_strong_audio_head_is_not_silently_waived(self):
        self.submission["artifacts"]["strong_audio_head"] = None
        self.rejected("strong_audio_head: missing artifact")

    def test_changed_bytes_rejected_even_with_unchanged_metadata(self):
        (self.root / "original_v6_head").write_bytes(b"modified")
        self.rejected("content hash/size mismatch")

    def test_wrong_git_blob_rejected(self):
        self.submission["artifacts"]["original_v6_head"]["git_blob_sha1"] = "0" * 40
        self.rejected("Git blob mismatch")

    def test_absolute_path_and_path_escape_rejected(self):
        self.submission["artifacts"]["original_v6_head"]["path"] = str(self.root / "original_v6_head")
        self.rejected("relative")
        self.submission["artifacts"]["original_v6_head"]["path"] = "../outside"
        self.rejected("outside root")

    def test_empty_historical_exclusion_list_rejected(self):
        self.ledger["campaigns"]["v6"]["recordings"] = []
        self.history()
        self.rejected("empty recording exclusion")

    def test_v3_only_catalog_cannot_claim_complete_history(self):
        self.catalog["campaigns"] = ["v3"]
        self.ledger["campaigns"] = {"v3": self.ledger["campaigns"]["v3"]}
        self.history()
        self.rejected("omits known prior")

    def test_omitted_exploration_or_stale_reconciliation_rejected(self):
        self.put("history_reconciliation", {"complete": True, "campaigns": self.catalog["campaigns"]})
        self.rejected("reconciliation")

    def test_renamed_or_recoded_original_recording_is_not_new(self):
        self.new["original_capture_sha256"] = self.old["original_capture_sha256"]
        self.confirmation()
        self.rejected("overlaps history")

    def test_same_acquisition_session_is_not_independent(self):
        self.new["acquisition_session_id"] = self.old["acquisition_session_id"]
        self.confirmation()
        self.rejected("overlaps history")

    def test_cropped_resplit_history_ancestor_rejected(self):
        self.new["derivation_ancestors"] = [self.old]
        self.confirmation()
        self.rejected("overlaps history")

    def test_no_ancestry_or_acquisition_metadata_does_not_pass(self):
        del self.new["derivation_ancestors"]
        self.new["acquisition_receipt"] = None
        self.confirmation()
        self.rejected("ancestry must be explicitly declared")

    def test_duplicate_confirmation_captures_rejected(self):
        self.put("confirmation_index", {"recordings": [self.new, copy.deepcopy(self.new)]})
        self.rejected("duplicate recording/session/capture")

    def test_failed_strong_audio_quality_cannot_hide_behind_av(self):
        data = strict_json((self.root / "audio_evaluation").read_bytes())
        data["predictions"][0]["probabilities"] = [.9, .1]
        self.put("audio_evaluation", data)
        self.rejected("strong quality gate failed")

    def test_omitted_easy_subset_or_changed_cross_head_labels_rejected(self):
        index = strict_json((self.root / "confirmation_index").read_bytes())
        index["cases"].append(dict(index["cases"][0], case_id="second"))
        self.put("confirmation_index", index)
        self.rejected("frozen case coverage incomplete")
        self.confirmation()
        data = strict_json((self.root / "audio_evaluation").read_bytes())
        data["predictions"][0]["label"] = 0
        self.put("audio_evaluation", data)
        self.rejected("differs from frozen case/label")

    def test_missing_or_zero_original_threshold_rejected(self):
        self.protocol["tasks"]["fixture"]["minimum_av_accuracy"] = 0
        self.put("original_v6_protocol", self.protocol)
        self.confirmation()
        self.rejected("positive quality threshold missing")

    def test_invalid_predictions_never_raise_or_pass(self):
        for changes in ({"task": []}, {"source_recording_id": []}, {"probabilities": [0, 0]},
                        {"label": True}, {"probabilities": [1.1, -.1]}):
            self.confirmation()
            data = strict_json((self.root / "av_evaluation").read_bytes())
            data["predictions"][0].update(changes)
            self.put("av_evaluation", data)
            self.assertEqual(self.result()["status"], "FAIL")

    def test_json_nan_and_duplicate_keys_rejected(self):
        for data in ('{"x":NaN}', '{"x":1,"x":2}'):
            with self.assertRaises(ValueError):
                strict_json(data)

    def test_quality_results_bound_to_exact_index(self):
        self.new["source_recording_id"] = "different"
        self.put("confirmation_index", {"recordings": [self.new]})
        self.rejected("identities are unbound")


if __name__ == "__main__":
    unittest.main()
