"""V3 source exposure, deterministic partition and withheld-label boundaries."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cell_field_action_data as data
from prepare_news_cohorts import publisher_is_ood


class ActionDataTests(unittest.TestCase):
    def setUp(self):
        self.publisher = next(f"publisher-{i}" for i in range(20) if not publisher_is_ood(f"publisher-{i}"))
        self.plan = [
            {"role": role, "month": month, "rows": 4, "access": access}
            for role, month, access in (
                ("old_train", "2014-04", "train"), ("old_probe", "2014-04", "train"),
                ("old_validation", "2014-04", "validation"), ("old_test", "2014-04", "final"),
                ("current_train", "2014-05", "train"), ("current_probe", "2014-05", "train"),
                ("current_validation", "2014-05", "validation"),
                ("future_july", "2014-07", "final"), ("future_august", "2014-08", "final"))]
        self.rows = [self.row(f"{month}-{label}-{i}", month, label)
                     for month in ("2014-04", "2014-05", "2014-07", "2014-08")
                     for label in range(4) for i in range(12)]

    def row(self, key, month, label, *, story=None, title=None):
        stamp = int(datetime.fromisoformat(month + "-10").replace(tzinfo=timezone.utc).timestamp() * 1000)
        return {"source_id": key, "source_group_id": story or "story-" + key,
                "text": title or "title " + key, "timestamp_ms": stamp,
                "label": label, "publisher": self.publisher, "source_row_sha256": "0" * 64}

    def prior(self, key, members):
        ids = sorted(members)
        return {"raw_source_id": key, "component_id": "news-group:" + data.sha(ids),
                "component_member_count": len(ids), "component_members_sha256": data.sha(ids)}

    def protocol(self):
        return {"source_role_plan": self.plan, "source_counts": {r["role"]: r["rows"] for r in self.plan},
                "source_split_salt": data.SALT, "source_archive_sha256": data.ARCHIVE_SHA256,
                "prior_experiments": data.PRIOR_PINS}

    def test_complete_disjoint_partition_is_invariant_to_raw_row_order(self):
        first, audit = data.build_cohorts(self.rows, {}, {"v1": [], "v2": []}, role_plan=self.plan)
        second, _ = data.build_cohorts(list(reversed(self.rows)), {}, {"v1": [], "v2": []}, role_plan=self.plan)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 36)
        self.assertEqual(len({s["component_id"] for s in first}), len(first))
        self.assertEqual({s["role"] for s in first}, {r["role"] for r in self.plan})
        self.assertEqual([audit[k] for k in ("selected_legacy_overlap", "selected_v1_overlap", "selected_v2_overlap")], [0, 0, 0])

    def test_excludes_transitive_v1_and_v2_components_and_legacy(self):
        extra = [self.row("a", "2014-04", 0, story="linked-story", title="first"),
                 self.row("b", "2014-04", 0, story="linked-story", title=" SHARED title "),
                 self.row("c", "2014-04", 0, story="other-story", title="shared TITLE")]
        v2, legacy = self.rows[0], self.rows[-1]
        previous = {"v1": [self.prior("c", ["a", "b", "c"])],
                    "v2": [self.prior(v2["source_id"], [v2["source_id"]])]}
        selected, audit = data.build_cohorts(self.rows + extra, {"known": [legacy]}, previous, role_plan=self.plan)
        forbidden = {"a", "b", "c", v2["source_id"], legacy["source_id"]}
        self.assertFalse(any(forbidden.intersection(s["members"]) for s in selected))
        self.assertEqual({key: audit["excluded_components_by_reason"][key] for key in
                          ("v1_experiment_component", "v2_experiment_component", "legacy_cohort_component")},
                         {"v1_experiment_component": 1, "v2_experiment_component": 1, "legacy_cohort_component": 1})

    def test_prior_membership_and_census_must_match_raw_graph(self):
        source = self.rows[0]["source_id"]
        with self.assertRaisesRegex(ValueError, "membership differs"):
            data.build_cohorts(self.rows, {}, {"v1": [], "v2": [self.prior(source, [source, "missing"])]}, role_plan=self.plan)
        with self.assertRaisesRegex(ValueError, "outside this archive"):
            data.build_cohorts(self.rows, {}, {"v1": [self.prior("absent", ["absent"])], "v2": []}, role_plan=self.plan)
        with self.assertRaisesRegex(ValueError, "duplicate raw"):
            item = self.prior(source, [source])
            data.build_cohorts(self.rows, {}, {"v1": [item], "v2": [item]}, role_plan=self.plan)

    def test_cross_month_label_conflict_and_insufficient_support_are_not_relaxed(self):
        extra = [self.row("bad-a", "2014-04", 0, story="conflict"),
                 self.row("bad-b", "2014-05", 1, story="conflict")]
        selected, audit = data.build_cohorts(self.rows + extra, {}, {"v1": [], "v2": []}, role_plan=self.plan)
        self.assertEqual(audit["excluded_components_by_reason"]["cross_month"], 1)
        self.assertEqual(audit["excluded_components_by_reason"]["label_conflict"], 1)
        self.assertFalse(any("bad-a" in s["members"] for s in selected))
        with self.assertRaisesRegex(ValueError, "insufficient independent"):
            data.build_cohorts([r for r in self.rows if r["label"] != 3], {}, {"v1": [], "v2": []}, role_plan=self.plan)

    def test_validation_cannot_be_reclassified_as_control_and_roles_cannot_duplicate(self):
        changed = [dict(row) for row in self.plan]
        changed[2]["access"] = "train"
        with self.assertRaisesRegex(ValueError, "must remain separate"):
            data.validate_roles(changed)
        changed = [dict(row) for row in self.plan]
        changed[2]["role"] = "old_probe"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            data.validate_roles(changed)

    def test_preparation_writes_three_label_partitions_without_reading_withheld_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, protocol = root / "archive.zip", root / "protocol.json"
            archive.write_bytes(b"source fixture")
            protocol.write_bytes(data.canonical(self.protocol()))
            original = Path.read_bytes

            def guarded(path):
                if path.name in ("validation_labels.json", "final_labels.json"):
                    raise AssertionError("preparation opened withheld label payload")
                return original(path)

            with patch.object(data, "_read_archive", return_value=self.rows), \
                    patch.object(data, "select_rows", return_value={}), \
                    patch.object(data, "previous_sources", return_value=({"v1": [], "v2": []}, {})), \
                    patch.object(Path, "read_bytes", guarded):
                receipt = data.prepare(archive, root / "v1", root / "v2", root / "data", protocol)
            partitions = {}
            for access, name in data.ACCESS_FILES.items():
                rows = json.loads((root / "data" / name).read_bytes())["roles"]
                self.assertEqual(set(rows), {r["role"] for r in self.plan if r["access"] == access})
                partitions[access] = {i for row in rows.values() for i in row["indices"]}
            self.assertEqual(set.union(*partitions.values()), set(range(36)))
            self.assertEqual(sum(map(len, partitions.values())), 36)
            predictors = json.loads((root / "data/predictors.json").read_bytes())["rows"]
            self.assertTrue(all(set(row) == {"source_id", "source_version", "text"} for row in predictors))
            for name, expected in receipt["files"].items():
                payload = (root / "data" / name).read_bytes()
                self.assertEqual(expected, {"sha256": data.sha(payload), "bytes": len(payload)})
            with self.assertRaises(FileExistsError):
                data.prepare(archive, root / "v1", root / "v2", root / "data", protocol)

    def test_invalid_protocol_preserves_failure_without_overwriting_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.protocol()
            plan["source_counts"] = {}
            protocol = root / "protocol.json"
            protocol.write_bytes(data.canonical(plan))
            with self.assertRaisesRegex(ValueError, "frozen protocol"):
                data.prepare(root / "unused.zip", root / "v1", root / "v2", root / "failed", protocol)
            failure = json.loads((root / "failed/preparation_failure.json").read_bytes())
            self.assertEqual(failure["error_type"], "ValueError")
            self.assertFalse(failure["model_outputs_observed"])
            self.assertEqual([p.name for p in (root / "failed").iterdir()], ["preparation_failure.json"])

    def test_pinned_v2_sources_and_original_receipt_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [{"index": i, "raw_source_id": str(i), "source_id": f"uci-news:{i}", "component_id": f"group-{i}"} for i in range(480)]
            payload = data.canonical({"rows": rows}) + b"\n"
            receipt = data.canonical({"files": {"sources.json": {"bytes": len(payload), "sha256": data.sha(payload)}},
                                      "source_archive_sha256": data.ARCHIVE_SHA256}) + b"\n"
            (root / "sources.json").write_bytes(payload)
            (root / "data_receipt.json").write_bytes(receipt)
            pins = {**data.PRIOR_PINS, "v2": {"sources_sha256": data.sha(payload), "data_receipt_sha256": data.sha(receipt)}}
            with patch.object(data, "v1_sources", return_value=([], {"mode": "fixture"})), \
                    patch.object(data, "PRIOR_PINS", pins), \
                    patch.object(data, "V2_SOURCE_BYTES", len(payload)), \
                    patch.object(data, "V2_RECEIPT_BYTES", len(receipt)):
                previous, provenance = data.previous_sources(root, root)
                self.assertEqual(previous, {"v1": [], "v2": rows})
                self.assertTrue(provenance["v2"]["original_receipt_present"])
                (root / "data_receipt.json").write_bytes(receipt + b"\n")
                with self.assertRaisesRegex(ValueError, "differ from the published"):
                    data.previous_sources(root, root)
                (root / "data_receipt.json").write_bytes(receipt)
                (root / "sources.json").write_bytes(payload + b"\n")
                with self.assertRaisesRegex(ValueError, "differ from the published"):
                    data.previous_sources(root, root)


if __name__ == "__main__":
    unittest.main()
