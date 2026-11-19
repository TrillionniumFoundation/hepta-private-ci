"""Small executable retrieval/router/whole-group partition behavior checks."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from domain_baselines import RetrievalBaselines, dense_nearest
from domain_data import (
    TRAIN_TEMPLATES,
    SELECT_TEMPLATE,
    canonical,
    probes,
    sha,
    source_group_ids,
)
from domain_training import grouped_partition
from learned_router import fit_router, load_router


class DomainControlTests(unittest.TestCase):
    def test_odd_partition_preserves_dependency_groups(self):
        matrix = [[1, 0], [1, 0], [0, 1], [-1, 0], [-1, 0]]
        groups = ["a", "a", "b", "c", "c"]
        for random in (False, True):
            result = grouped_partition(matrix, groups, 20, randomized=random)
            self.assertEqual(sorted(result["sizes"]), [2, 3])
            self.assertEqual(result["slots"][0], result["slots"][1])
            self.assertEqual(result["slots"][3], result["slots"][4])
        three = grouped_partition([[1, 0], [0, 1], [-1, 0]], ["a", "b", "c"], 20)
        self.assertEqual(sorted(three["sizes"]), [1, 2])
        with self.assertRaises(ValueError):
            grouped_partition([[1, 0], [0, 1]], ["same", "same"], 20)

    def test_fission_uses_observed_ancestry_not_renamed_causes(self):
        cases = [
            dict(id="first", root_cause="label-a", project="p", fixed_commit="x"),
            dict(id="repeat", root_cause="label-b", project="p", fixed_commit="x"),
            dict(id="other", root_cause="label-c", project="p", fixed_commit="y"),
        ]
        groups = source_group_ids(cases)
        for randomized in (False, True):
            split = grouped_partition([[1, 0], [0, 1], [-1, 0]], groups, 20, randomized)
            self.assertEqual(split["slots"][0], split["slots"][1])
        with self.assertRaisesRegex(ValueError, "two independent"):
            grouped_partition([[1, 0], [0, 1]], source_group_ids(cases[:2]), 20)

    def test_single_ancestry_is_rejected_before_model_load_or_output_creation(self):
        import domain_training
        import domain_trial

        cases = [
            dict(id=str(i), root_cause=f"label-{i}", project="p", fixed_commit="x")
            for i in range(2)
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            with patch.object(
                domain_training,
                "SourceMemoryCell",
                side_effect=AssertionError("no model load"),
            ):
                with self.assertRaisesRegex(ValueError, "two independent"):
                    domain_training.train("unused", cases, "scope", output, 20, 8)
            with patch.object(
                domain_trial,
                "load_dataset",
                return_value=dict(cases=cases, partitions=dict(train=["0", "1"])),
            ):
                with self.assertRaisesRegex(ValueError, "two independent"):
                    domain_trial.run("unused", "unused", "unused", output)
            self.assertFalse(output.exists())

    def test_source_only_retrieval_recovers_changed_wording(self):
        cases = [
            dict(symptom="alpha certificate expired", repair_id="renew"),
            dict(symptom="beta socket disconnected", repair_id="reconnect"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            baseline = RetrievalBaselines(cases, Path(directory) / "search.sqlite3")
            self.addCleanup(baseline.close)
            self.assertEqual(
                baseline.predict("Recall the repair for beta socket disconnected"),
                dict(exact_source="reconnect", bm25="reconnect", tfidf="reconnect"),
            )
            self.assertEqual(
                baseline.predict("unrecorded checksum for beta socket disconnected")[
                    "exact_source"
                ],
                "unknown",
            )
            baseline.close()
        self.assertEqual(
            dense_nearest([[1, 0], [0, 1]], [[0, 2], [3, 0]], ["renew", "reconnect"]),
            dict(
                dense_nearest=["reconnect", "renew"],
                dense_centroid=["reconnect", "renew"],
            ),
        )

    def test_router_trains_on_actual_utility_contract_and_roundtrips(self):
        cases = [
            dict(
                id="alpha",
                symptom="alpha certificate expired",
                repair_id="renew",
                source_digest="a" * 64,
            ),
            dict(
                id="beta",
                symptom="beta socket disconnected",
                repair_id="reconnect",
                source_digest="b" * 64,
            ),
        ]
        positives = probes(cases, TRAIN_TEMPLATES)
        negatives = probes(cases, TRAIN_TEMPLATES, unknown=True)
        # Local deterministic utility fixtures exercise the adapter interface;
        # the executable trial substitutes actual decoder results here.
        rows = [
            dict(
                question=p["question"],
                reject=p["synthetic_unknown"],
                utilities=[
                    float(p["case_id"] == c["id"] and not p["synthetic_unknown"])
                    for c in cases
                ],
            )
            for p in positives + negatives
        ]
        router = fit_router(
            rows, expert_ids=["left", "right"], source_sha256=sha(canonical(rows))
        )
        questions = probes(cases, [SELECT_TEMPLATE]) + probes(
            cases, [SELECT_TEMPLATE], unknown=True
        )
        with tempfile.TemporaryDirectory() as directory:
            receipt = router.save(Path(directory) / "router.bin")
            loaded = load_router(receipt["path"], expected_sha256=receipt["sha256"])
            self.assertEqual(
                [router.predict({"question": p["question"]}) for p in questions],
                [loaded.predict({"question": p["question"]}) for p in questions],
            )
            with self.assertRaisesRegex(ValueError, "question text only"):
                loaded.predict(dict(question=questions[0]["question"], answer="renew"))
        self.assertEqual(
            [router.predict({"question": p["question"]})["slot"] for p in questions],
            [0, 1, None, None],
        )


if __name__ == "__main__":
    unittest.main()
