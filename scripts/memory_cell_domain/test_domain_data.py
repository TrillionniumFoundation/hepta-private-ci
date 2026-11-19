"""Source-shaped local fixtures test contracts, never count as real CI evidence."""

import json
from pathlib import Path
import tempfile
import unittest

from domain_data import (
    TRAIN_TEMPLATES,
    canonical,
    load_dataset,
    partition_cases,
    probes,
    produce,
    sha,
)


class DomainDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        runs, cases = [], []

        def source(name, content):
            payload = (
                content
                if isinstance(content, bytes)
                else json.dumps(content, indent=2).encode()
            )
            (self.root / name).write_bytes(payload)
            return dict(path=name, sha256=sha(payload))

        for i in range(3):
            failed, fixed = str(i + 1) * 40, str(i + 4) * 40
            symptom = f"AssertionError: independent test contract {i}"
            runs.extend(
                [
                    dict(
                        id=2 * i + j,
                        status="completed",
                        conclusion="failure" if j == 0 else "success",
                        head_sha=failed if j == 0 else fixed,
                        path=".github/workflows/tests.yml",
                        repository=dict(full_name="test/fixture"),
                        updated_at=f"2026-01-0{i + 1}T10:0{j}:00Z",
                    )
                    for j in (0, 1)
                ]
            )
            cases.append(
                dict(
                    id=f"case-{i}",
                    root_cause=f"root-{i}",
                    repair_id=f"repair{i}",
                    repair_text="Local contract fixture only",
                    previously_seen=True,
                    failed_run_id=2 * i,
                    success_run_id=2 * i + 1,
                    symptom=symptom,
                    fix=source(
                        f"fix-{i}.json",
                        dict(
                            sha=fixed,
                            parents=[dict(sha=failed)],
                            files=[dict(filename="test.py", patch=f"+fixed_{i}")],
                        ),
                    ),
                    failure_log=source(f"bad-{i}.log", symptom.encode()),
                    success_log=source(f"good-{i}.log", b"all checks passed"),
                )
            )
        manifest = dict(
            schema="hepta.domain.ci-manifest.v1",
            registered_at="2026-02-01T00:00:00Z",
            train_until="2026-01-05T00:00:00Z",
            validation_until="2026-01-10T00:00:00Z",
            runs=source("runs.json", runs),
            cases=cases,
        )
        path = self.root / "manifest.json"
        path.write_bytes(canonical(manifest))
        return path, manifest

    def test_producer_roundtrip_binds_raw_sources_and_history(self):
        manifest, _ = self.fixture()
        receipt = produce(manifest, self.root / "produced")
        data = load_dataset(receipt["dataset"], receipt["sha256"])
        self.assertEqual(
            data["partitions"],
            dict(
                train=["case-0", "case-1", "case-2"],
                validation=[],
                future=[],
                purged=[],
            ),
        )
        self.assertEqual(
            (
                data["independent_groups"],
                data["prospective_cases"],
                data["generalization_established"],
            ),
            (3, [], False),
        )
        for case in data["cases"]:
            raw = (
                self.root / "produced" / "evidence" / case["commit_evidence_sha256"]
            ).read_bytes()
            self.assertEqual(json.loads(raw)["sha"], case["fixed_commit"])

    def test_source_tampering_fails_before_use(self):
        manifest, _ = self.fixture()
        receipt = produce(manifest, self.root / "produced")
        data = load_dataset(receipt["dataset"], receipt["sha256"])
        path = (
            self.root / "produced" / "evidence" / data["cases"][0]["failure_log_sha256"]
        )
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "original source"):
            load_dataset(receipt["dataset"], receipt["sha256"])

    def test_queued_run_cannot_be_success_evidence(self):
        manifest, content = self.fixture()
        path = self.root / content["runs"]["path"]
        runs = json.loads(path.read_bytes())
        runs[1]["status"] = "queued"
        path.write_bytes(canonical(runs))
        content["runs"]["sha256"] = sha(path.read_bytes())
        manifest.write_bytes(canonical(content))
        with self.assertRaisesRegex(ValueError, "completed same-workflow"):
            produce(manifest, self.root / "produced")

    def test_case_digest_cannot_be_relabelled_with_only_a_new_dataset_pin(self):
        manifest, _ = self.fixture()
        receipt = produce(manifest, self.root / "produced")
        path = Path(receipt["dataset"])
        data = json.loads(path.read_bytes())
        data["cases"][0]["repair_id"] = "different_annotation"
        path.write_bytes(canonical(data))
        with self.assertRaisesRegex(ValueError, "case source binding"):
            load_dataset(path, sha(path.read_bytes()))

    def test_root_groups_purge_across_time_and_projects(self):
        cases = [
            dict(
                id="early",
                root_cause="shared",
                project="one",
                observed_at="2026-01-01T00:00:00Z",
                resolved_at="2026-01-02T00:00:00Z",
            ),
            dict(
                id="later",
                root_cause="shared",
                project="two",
                observed_at="2026-01-11T00:00:00Z",
                resolved_at="2026-01-12T00:00:00Z",
            ),
            dict(
                id="middle",
                root_cause="independent",
                project="one",
                observed_at="2026-01-07T00:00:00Z",
                resolved_at="2026-01-08T00:00:00Z",
            ),
        ]
        self.assertEqual(
            partition_cases(cases, "2026-01-05T00:00:00Z", "2026-01-10T00:00:00Z"),
            dict(train=[], validation=["middle"], future=[], purged=["early", "later"]),
        )

    def test_router_wording_is_crossed_without_gold_in_question(self):
        case = dict(
            id="source",
            symptom="original failure",
            repair_id="secret_target",
            source_digest="a" * 64,
        )
        positive = probes([case], TRAIN_TEMPLATES)
        negative = probes([case], TRAIN_TEMPLATES, unknown=True)
        self.assertEqual(
            [p["question"].replace("repair", "RELATION") for p in positive],
            [
                p["question"].replace("unrecorded checksum", "RELATION")
                for p in negative
            ],
        )
        self.assertTrue(
            all(case["repair_id"] not in p["question"] for p in positive + negative)
        )


if __name__ == "__main__":
    unittest.main()
