"""Fresh-component exclusion, source identity and label-boundary checks."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cell_field_retention_data as data
from prepare_news_cohorts import publisher_is_ood


class RetentionDataTests(unittest.TestCase):
    def setUp(self):
        self.publisher = next(f"publisher-{i}" for i in range(20) if not publisher_is_ood(f"publisher-{i}"))
        self.plan = tuple((role, month, 4) for role, month, _ in data.ROLE_PLAN)
        self.rows = [self.row(f"{month}-{label}-{i}", month, label)
                     for month in ("2014-03", "2014-04", "2014-05", "2014-06")
                     for label in range(4) for i in range(10)]

    def row(self, key, month, label, *, story=None, title=None):
        timestamp = int(datetime.fromisoformat(month + "-10").replace(tzinfo=timezone.utc).timestamp() * 1000)
        return {"source_id": key, "source_group_id": story or "story-" + key,
                "text": title or "title " + key, "timestamp_ms": timestamp,
                "label": label, "publisher": self.publisher, "source_row_sha256": "0" * 64}

    def prior(self, key, members):
        ids = sorted(members)
        return {"raw_source_id": key, "component_id": "news-group:" + data.sha(ids),
                "component_member_count": len(ids), "component_members_sha256": data.sha(ids)}

    def test_all_roles_are_disjoint_and_row_order_invariant(self):
        first, audit = data.build_cohorts(self.rows, {}, [], role_plan=self.plan)
        second, _ = data.build_cohorts(list(reversed(self.rows)), {}, [], role_plan=self.plan)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 28)
        self.assertEqual(len({s["component_id"] for s in first}), 28)
        self.assertEqual({s["role"] for s in first}, data.TRAIN_ROLES | data.FINAL_ROLES)
        self.assertEqual(audit["selected_v1_overlap"], 0)

    def test_excludes_entire_transitive_v1_component_and_legacy_component(self):
        extra = [self.row("link-a", "2014-03", 0, story="story-a", title="Title A"),
                 self.row("link-b", "2014-03", 0, story="story-a", title=" shared TITLE "),
                 self.row("link-c", "2014-03", 0, story="story-b", title="Shared title")]
        members = [r["source_id"] for r in extra]
        legacy = self.rows[0]
        selected, audit = data.build_cohorts(self.rows + extra, {"legacy": [legacy]},
            [self.prior("link-c", members)], role_plan=self.plan)
        self.assertEqual(audit["excluded_components_by_reason"]["v1_experiment_component"], 1)
        self.assertEqual(audit["excluded_components_by_reason"]["legacy_cohort_component"], 1)
        self.assertFalse(any(set(s["members"]) & set(members + [legacy["source_id"]]) for s in selected))

    def test_prior_component_identity_and_raw_source_census_fail_closed(self):
        source = self.rows[0]["source_id"]
        wrong = self.prior(source, [source, "invented-member"])
        with self.assertRaisesRegex(ValueError, "component membership differs"):
            data.build_cohorts(self.rows, {}, [wrong], role_plan=self.plan)
        with self.assertRaisesRegex(ValueError, "outside this archive"):
            data.build_cohorts(self.rows, {}, [self.prior("absent", ["absent"])], role_plan=self.plan)
        with self.assertRaisesRegex(ValueError, "duplicate raw"):
            data.build_cohorts(self.rows, {}, [self.prior(source, [source])] * 2, role_plan=self.plan)

    def test_cross_month_conflict_and_insufficient_support_are_not_relaxed(self):
        extra = [self.row("conflict-a", "2014-03", 0, story="conflict"),
                 self.row("conflict-b", "2014-04", 1, story="conflict")]
        selected, audit = data.build_cohorts(self.rows + extra, {}, [], role_plan=self.plan)
        self.assertEqual(audit["excluded_components_by_reason"]["cross_month"], 1)
        self.assertEqual(audit["excluded_components_by_reason"]["label_conflict"], 1)
        self.assertFalse(any("conflict-a" in s["members"] for s in selected))
        with self.assertRaisesRegex(ValueError, "insufficient independent"):
            data.build_cohorts([r for r in self.rows if r["label"] != 3], {}, [], role_plan=self.plan)

    def test_preparation_writes_compatible_predictors_and_disjoint_label_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, protocol = root / "archive.zip", root / "protocol.json"
            archive.write_bytes(b"source fixture")
            protocol.write_bytes(data.canonical({"source_counts": {r: n for r, _, n in self.plan},
                "source_split_salt": data.SALT, "source_archive_sha256": data.ARCHIVE_SHA256,
                "previous_data_receipt_sha256": data.PREVIOUS_RECEIPT_SHA256,
                "previous_sources_sha256": data.PREVIOUS_SOURCES_SHA256}))
            with patch.object(data, "_read_archive", return_value=self.rows), \
                    patch.object(data, "select_rows", return_value={}), \
                    patch.object(data, "prior_sources", return_value=([], {"mode": "fixture"})), \
                    patch.object(data, "ROLE_PLAN", self.plan):
                receipt = data.prepare(archive, root / "previous", root / "data", protocol)
            output = root / "data"
            predictors = json.loads((output / "predictors.json").read_bytes())
            training = json.loads((output / "train_labels.json").read_bytes())["roles"]
            final = json.loads((output / "final_labels.json").read_bytes())["roles"]
            self.assertTrue(all(set(r) == {"source_id", "source_version", "text"} for r in predictors["rows"]))
            self.assertEqual(set(training), data.TRAIN_ROLES)
            self.assertEqual(set(final), data.FINAL_ROLES)
            train_ids = {i for r in training.values() for i in r["indices"]}
            final_ids = {i for r in final.values() for i in r["indices"]}
            self.assertFalse(train_ids & final_ids)
            self.assertEqual(train_ids | final_ids, set(range(28)))
            self.assertEqual(receipt["protocol_sha256"], data.sha(protocol.read_bytes()))
            for name, identity in receipt["files"].items():
                payload = (output / name).read_bytes()
                self.assertEqual(identity, {"sha256": data.sha(payload), "bytes": len(payload)})
            with self.assertRaises(FileExistsError):
                data.prepare(archive, root / "previous", output, protocol)

    def test_protocol_mismatch_preserves_failed_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.json"
            protocol.write_text(json.dumps({"source_counts": {}, "source_split_salt": data.SALT,
                                            "source_archive_sha256": data.ARCHIVE_SHA256}))
            with self.assertRaisesRegex(ValueError, "frozen protocol"):
                data.prepare(root / "unused.zip", root / "unused-prior", root / "attempt", protocol)
            failure = json.loads((root / "attempt/preparation_failure.json").read_bytes())
            self.assertEqual(failure["error_type"], "ValueError")
            self.assertFalse(failure["model_outputs_observed"])
            self.assertEqual(list((root / "attempt").iterdir()), [root / "attempt/preparation_failure.json"])

    def prior_fixture(self, root):
        sources = [{"index": i, "raw_source_id": str(i), "source_id": f"uci-news:{i}",
                    "component_id": f"component-{i}"} for i in range(512)]
        source_bytes = data.canonical({"rows": sources}) + b"\n"
        source_identity = {"sha256": data.sha(source_bytes), "bytes": len(source_bytes)}
        receipt_bytes = data.canonical({"files": {"sources.json": source_identity},
            "source_archive_sha256": data.ARCHIVE_SHA256}) + b"\n"
        receipt_identity = {"sha256": data.sha(receipt_bytes), "bytes": len(receipt_bytes)}
        seal = {"files": {"inputs/sources.json": source_identity,
                          "inputs/data_receipt.json": receipt_identity}, "final_labels_opened": False}
        seal_bytes = data.canonical(seal) + b"\n"
        (root / "sources.json").write_bytes(source_bytes)
        (root / "pre_evaluation_seal.json").write_bytes(seal_bytes)
        pins = {"PREVIOUS_SOURCES_SHA256": source_identity["sha256"],
                "PREVIOUS_SOURCES_BYTES": source_identity["bytes"],
                "PREVIOUS_RECEIPT_SHA256": receipt_identity["sha256"],
                "PREVIOUS_RECEIPT_BYTES": receipt_identity["bytes"],
                "PREVIOUS_SEAL_SHA256": data.sha(seal_bytes)}
        return sources, receipt_bytes, seal_bytes, pins

    def test_published_seal_authenticates_sources_without_recreating_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected, receipt_bytes, _, pins = self.prior_fixture(root)
            with patch.multiple(data, **pins):
                rows, provenance = data.prior_sources(root)
                self.assertEqual(rows, expected)
                self.assertEqual(provenance["mode"], "published_pre_evaluation_seal")
                self.assertFalse(provenance["original_receipt_present"])
                self.assertEqual(provenance["seal_sha256"], pins["PREVIOUS_SEAL_SHA256"])
                self.assertFalse((root / "data_receipt.json").exists())
                (root / "data_receipt.json").write_bytes(receipt_bytes)
                same_rows, original = data.prior_sources(root)
                self.assertEqual(same_rows, rows)
                self.assertEqual(original["mode"], "original_receipt")
                self.assertTrue(original["original_receipt_present"])

    def test_recovery_rejects_changed_source_seal_and_invalid_present_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, seal_bytes, pins = self.prior_fixture(root)
            source_bytes = (root / "sources.json").read_bytes()
            with patch.multiple(data, **pins):
                (root / "sources.json").write_bytes(source_bytes + b"\n")
                with self.assertRaisesRegex(ValueError, "source census does not match"):
                    data.prior_sources(root)
                (root / "sources.json").write_bytes(source_bytes)
                (root / "pre_evaluation_seal.json").write_bytes(seal_bytes + b"\n")
                with self.assertRaisesRegex(ValueError, "published source seal"):
                    data.prior_sources(root)
                (root / "pre_evaluation_seal.json").write_bytes(seal_bytes)
                (root / "data_receipt.json").write_bytes(b"{}")
                with self.assertRaisesRegex(ValueError, "receipt does not match"):
                    data.prior_sources(root)

    def test_recovery_requires_seal_records_to_bind_both_historical_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, seal_bytes, pins = self.prior_fixture(root)
            seal = json.loads(seal_bytes)
            seal["files"]["inputs/data_receipt.json"]["bytes"] += 1
            altered = data.canonical(seal) + b"\n"
            (root / "pre_evaluation_seal.json").write_bytes(altered)
            pins["PREVIOUS_SEAL_SHA256"] = data.sha(altered)
            with patch.multiple(data, **pins):
                with self.assertRaisesRegex(ValueError, "published source seal"):
                    data.prior_sources(root)


if __name__ == "__main__":
    unittest.main()
