"""Adversarial metadata reconciliation tests; no original tasks or answers used."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .coverage import FAMILIES, ROLES, MetadataError, audit_coverage, read_pinned, strict_json


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fixture(*, full_retention=False):
    sources, cases = [], []
    for role in ROLES:
        sid = "source-" + role
        episode = "episode-" + role
        source = {"source_id": sid, "source_family": "one_real_source_domain",
                  "allowed_split": "retention" if role.startswith("retention_") else role,
                  "text_sha256s": [digest(sid + "/original-transcript")],
                  "image_sha256s": [digest(sid + "/original-image")],
                  "source_evidence_sha256": digest(sid + "/evidence"),
                  "used_in_training": False, "previously_observed": False, "case_bindings": []}
        families = ("text_image_complementary",) if role.startswith("retention_") and not full_retention else FAMILIES
        for family in families:
            cid = role + ":" + family
            text_hash = digest(cid + "/transcript-input") if family == "text_sufficient" else digest(family + "/shared-instruction")
            image_hash, reference_hash = digest(cid + "/image"), digest(cid + "/reference")
            source["text_sha256s"].append(text_hash)
            source["image_sha256s"].append(image_hash)
            source["case_bindings"].append({"case_id": cid, "task_family": family,
                "text_sha256": text_hash, "image_sha256": image_hash, "reference_sha256": reference_hash})
            cases.append({"id": cid, "source_id": sid, "role": role, "task_family": family,
                "episode_group": episode,
                "packet": {"path": "metadata/" + cid + "/case.json", "sha256": digest(cid + "/packet"), "bytes": 17},
                "reference": {"path": "private/references/" + cid + ".json", "sha256": reference_hash, "bytes": 19}})
        sources.append(source)
    return {"registry": {"schema": "hepta.source-use-registry.v2", "sources": sources},
            "catalog": {"cases": cases},
            "exposure": {"schema": "ndu.real.researcher-exposure.v1", "registry_sha256": "",
                         "registration_sha256": "", "quarantined_source_groups": [], "matches": [],
                         "available_future_source_groups": {"confirmation": 1, "retention_test": 1}},
            "registration": {"schema": "ndu.real.registration.v1", "registry_sha256": "",
                "merchant_groups": 5, "eligible_receipts": 5, "excluded_receipts": 0, "original_receipts": 5,
                "case_counts": {role: sum(row["role"] == role for row in cases) for role in ROLES},
                "source_group_counts": {role: 1 for role in ROLES}}}


def audit(documents, *, selected=None):
    registry_hash = hashlib.sha256(encoded(documents["registry"])).hexdigest()
    documents["registration"]["registry_sha256"] = registry_hash
    documents["exposure"]["registry_sha256"] = registry_hash
    documents["exposure"]["registration_sha256"] = hashlib.sha256(encoded(documents["registration"])).hexdigest()
    bindings = {key: {"sha256": hashlib.sha256(encoded(value)).hexdigest(), "bytes": len(encoded(value))}
                for key, value in documents.items()}
    if selected is not None:
        bindings["selected_sources"] = {"sha256": hashlib.sha256(encoded(selected)).hexdigest()}
    return audit_coverage(documents["registry"], documents["catalog"], documents["exposure"],
                          input_bindings=bindings, registration=documents["registration"], selected_sources=selected)


def issue_codes(report):
    return {item["code"] for item in report["issues"]}


def select(documents):
    definitions = {"training": "train", "tuning": None, "pilot_new": "development", "pilot_retention": "retention_validation"}
    return {"schema": "ndu.real.selected-sources.v1",
            "groups": {name: [] if role is None else ["source-" + role] for name, role in definitions.items()},
            "cases": {name: [copy.deepcopy(row) for row in documents["catalog"]["cases"] if row["role"] == role]
                      for name, role in definitions.items()}}


class CoverageTests(unittest.TestCase):
    def test_existing_one_family_retention_remains_scope_gap(self):
        report = audit(fixture())
        self.assertTrue(report["metadata_consistent"], report["issues"])
        self.assertFalse(report["requested_scope_complete"])
        self.assertEqual(report["status"], "METADATA_CONSISTENT_SCOPE_INCOMPLETE")
        self.assertEqual(len(report["coverage_gaps"]), 8)
        self.assertEqual({row["role"] for row in report["coverage_gaps"]}, {"retention_validation", "retention_test"})

    def test_complete_metadata_never_grants_origin_power_or_release(self):
        report = audit(fixture(full_retention=True))
        self.assertTrue(report["metadata_consistent"], report["issues"])
        self.assertTrue(report["requested_scope_complete"])
        self.assertEqual(report["scientific_admission"], "HOLD")
        self.assertFalse(report["confirmation_release"])
        self.assertEqual(report["authenticated_source_origin"], "NOT_ESTABLISHED")
        self.assertEqual(report["independent_task_domains"], "NOT_ESTABLISHED")

    def test_shared_generic_prompts_are_not_independent_source_content(self):
        report = audit(fixture())
        self.assertTrue(report["metadata_consistent"])
        self.assertGreater(report["shared_instruction_hashes_across_sources"], 0)

    def test_retention_validation_and_test_cannot_share_source(self):
        docs = fixture()
        validation, test = docs["registry"]["sources"][-2:]
        validation["case_bindings"].extend(test["case_bindings"])
        validation["text_sha256s"] = sorted(set(validation["text_sha256s"] + test["text_sha256s"]))
        validation["image_sha256s"] = sorted(set(validation["image_sha256s"] + test["image_sha256s"]))
        test["case_bindings"] = []
        for case in docs["catalog"]["cases"]:
            if case["role"] == "retention_test":
                case["source_id"] = validation["source_id"]
        report = audit(docs)
        self.assertIn("source_crosses_exact_roles", issue_codes(report))
        self.assertFalse(report["metadata_consistent"])

    def test_same_episode_under_another_source_is_detected(self):
        docs = fixture()
        for case in docs["catalog"]["cases"]:
            if case["role"] == "confirmation":
                case["episode_group"] = "episode-development"
        self.assertIn("episode_crosses_source_or_role", issue_codes(audit(docs)))

    def test_reused_source_image_even_with_different_case_hashes_is_detected(self):
        docs = fixture()
        docs["registry"]["sources"][2]["image_sha256s"].append(docs["registry"]["sources"][0]["image_sha256s"][0])
        report = audit(docs)
        self.assertIn("source_content_alias", issue_codes(report))
        self.assertTrue(any(row.get("alias_kind") == "source_or_public_image" for row in report["issues"]))

    def test_reused_source_transcript_is_detected(self):
        docs = fixture()
        docs["registry"]["sources"][2]["text_sha256s"].append(docs["registry"]["sources"][0]["text_sha256s"][0])
        report = audit(docs)
        self.assertTrue(any(row.get("alias_kind") == "source_transcript" for row in report["issues"]))

    def test_wrong_reference_pin_rejects_catalog_row(self):
        docs = fixture()
        docs["catalog"]["cases"][0]["reference"]["sha256"] = digest("replacement reference")
        self.assertIn("catalog_registry_binding_mismatch", issue_codes(audit(docs)))

    def test_partial_catalog_does_not_count_as_full_inventory(self):
        docs = fixture()
        docs["catalog"]["cases"].pop()
        self.assertIn("full_catalog_not_closed", issue_codes(audit(docs)))

    def test_duplicate_case_id_is_not_an_extra_independent_case(self):
        docs = fixture()
        docs["catalog"]["cases"].append(copy.deepcopy(docs["catalog"]["cases"][0]))
        self.assertIn("malformed_or_unbound_metadata", issue_codes(audit(docs)))

    def test_noncanonical_packet_path_is_rejected_without_reading_it(self):
        docs = fixture()
        docs["catalog"]["cases"][0]["packet"]["path"] = "public/../private/answer.json"
        self.assertIn("malformed_or_unbound_metadata", issue_codes(audit(docs)))

    def test_previously_trained_source_cannot_be_confirmation(self):
        docs = fixture()
        docs["registry"]["sources"][2]["used_in_training"] = True
        self.assertIn("trained_source_in_evaluation_split", issue_codes(audit(docs)))

    def test_later_exposure_requires_whole_source_quarantine(self):
        docs = fixture()
        source = docs["registry"]["sources"][2]
        docs["exposure"]["matches"] = [{"source_group": source["source_id"], "role": "confirmation",
            "episode_groups": ["episode-confirmation"], "source_evidence_sha256": source["source_evidence_sha256"],
            "all_group_case_count": 5}]
        self.assertIn("exposed_evaluation_source_not_quarantined", issue_codes(audit(docs)))
        docs["exposure"]["quarantined_source_groups"] = [source["source_id"]]
        docs["exposure"]["available_future_source_groups"]["confirmation"] = 0
        report = audit(docs)
        self.assertTrue(report["metadata_consistent"], report["issues"])
        self.assertEqual(report["catalog_cases"], 17)
        self.assertEqual(report["case_counts"]["confirmation"], 5)
        self.assertEqual(report["available_future_source_groups"]["confirmation"], 0)

    def test_selection_must_match_catalog_and_preserve_exposure_exclusion(self):
        docs = fixture()
        selected = select(docs)
        self.assertTrue(audit(docs, selected=selected)["metadata_consistent"])
        docs["exposure"]["quarantined_source_groups"] = ["source-development"]
        self.assertIn("quarantined_source_selected", issue_codes(audit(docs, selected=selected)))

    def test_selection_cannot_swap_reference_or_drop_unfavorable_family(self):
        docs = fixture()
        selected = select(docs)
        selected["cases"]["pilot_new"][0]["reference"]["sha256"] = digest("substituted")
        self.assertIn("selected_case_not_exact_catalog_row", issue_codes(audit(docs, selected=selected)))
        selected = select(docs)
        selected["cases"]["pilot_new"].pop()
        self.assertIn("selected_original_panel_coverage_mismatch", issue_codes(audit(docs, selected=selected)))

    def test_stale_exposure_registry_pin_is_rejected(self):
        docs = fixture()
        bindings = {key: {"sha256": hashlib.sha256(encoded(value)).hexdigest()} for key, value in docs.items()}
        docs["exposure"]["registry_sha256"] = digest("another registry")
        report = audit_coverage(docs["registry"], docs["catalog"], docs["exposure"], input_bindings=bindings)
        self.assertFalse(report["metadata_consistent"])


class PinnedReadTests(unittest.TestCase):
    def test_exact_file_pin_and_replacement_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            raw = b'{"cases":[]}'
            path.write_bytes(raw)
            value, binding = read_pinned(path, hashlib.sha256(raw).hexdigest())
            self.assertEqual(value, {"cases": []})
            self.assertEqual(binding["bytes"], len(raw))
            path.write_bytes(b'{"cases":[1]}')
            with self.assertRaises(MetadataError):
                read_pinned(path, hashlib.sha256(raw).hexdigest())

    def test_symlink_and_duplicate_or_nonfinite_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            path.write_bytes(b"{}")
            link = Path(directory) / "alias.json"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                read_pinned(link, hashlib.sha256(b"{}").hexdigest())
        for raw in (b'{"cases":[],"cases":[1]}', b'{"count":NaN}', b'{"count":Infinity}'):
            with self.assertRaises(MetadataError):
                strict_json(raw)


if __name__ == "__main__":
    unittest.main()
