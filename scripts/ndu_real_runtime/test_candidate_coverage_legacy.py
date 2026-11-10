from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import candidate_coverage as coverage
from . import candidate_coverage_legacy as legacy


class LegacyCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / "scripts"
        (scripts / "ndu_real_materials").mkdir(parents=True)
        normalizer = scripts / "ndu_real_materials/evaluator.py"
        normalizer.write_text(
            "raise AssertionError('whole evaluator must not execute')\ndef canonical(text, field):\n    return text.strip().upper()\n"
        )
        paths = [normalizer]
        for number in range(59):
            path = scripts / f"frozen_{number}.py"
            path.write_text(f"VALUE = {number}\n")
            paths.append(path)
        self.pins = [self.pin(p) for p in paths]
        self.sources = [f"private-source-{i}" for i in range(40)]
        self.rows = []
        for source in self.sources:
            for step, field_index in enumerate((0, 1, 2, 3, 0)):
                self.rows.append(
                    dict(
                        schema="ndu.real.training-transition.v1",
                        source_group=source,
                        split="train",
                        record_id=source + "/" + str(step),
                        candidate_features=[[float(field_index)] + [0.0] * 125],
                        candidate_metadata=[
                            dict(
                                text="RIGHT" if field_index < 2 else "WRONG",
                                bbox=[0, 0, 2, 2],
                                origin="pixel_ocr",
                            )
                        ],
                        source_size=dict(width=10, height=10),
                        reference_field=legacy.FIELDS[field_index],
                        expected_text="RIGHT",
                        public_metadata=[float(i == field_index) for i in range(4)]
                        + [0.0] * 12,
                    )
                )
        self.plan = dict(
            schema="ndu.ctrl.answer-repair-plan.v1",
            original_fit_sources=self.sources,
            inner_train_sources=self.sources[:32],
            inner_tune_sources=self.sources[32:],
            future_sources=[f"future-{i}" for i in range(37)],
            excluded_sources=[f"excluded-{i}" for i in range(20)],
            normalizer_sha256=legacy.sha(normalizer.read_bytes()),
            source_inventory_sha256=legacy.sha(
                json.dumps(self.pins, sort_keys=True).encode()
            ),
        )
        self.config = dict(scripts_root=str(scripts))
        self.refresh()

    def pin(self, path):
        raw = path.read_bytes()
        return dict(path=str(path), bytes=len(raw), sha256=legacy.sha(raw))

    def refresh(self):
        self.data = self.root / "training.jsonl"
        self.data.write_bytes(
            b"".join((json.dumps(r) + "\n").encode() for r in self.rows)
        )
        pin = self.pin(self.data)
        self.plan["fit_records_sha256"] = pin["sha256"]
        collection = self.root / "collection.json"
        collection.write_text(
            json.dumps(
                dict(
                    schema="ndu.real.stopped-collection-plan.v1",
                    source_pins=self.pins,
                    original_pins=[pin],
                    execution_config=self.config,
                )
            )
        )
        self.request = self.root / "request.json"
        self.request.write_text(
            json.dumps(
                dict(
                    schema="ndu.ctrl.answer-repair-native-request.v1",
                    plan=self.plan,
                    records=str(self.data),
                    collection_plan=str(collection),
                    collection_sha256=legacy.sha(collection.read_bytes()),
                )
            )
        )

    def execute(self):
        return legacy.execute(
            self.request,
            legacy.sha(self.request.read_bytes()),
            coverage.__file__,
            legacy.sha(Path(coverage.__file__).read_bytes()),
            legacy.LOADED_SHA256,
            self.root / "output",
        )

    def test_complete_read_only_projection_and_field_denominators(self):
        original = self.data.read_bytes()
        result = self.execute()
        self.assertEqual(
            result["source_equal_means"],
            dict(oracle_ceiling=0.5, selected_accuracy=None, selection_gap=None),
        )
        self.assertTrue(result["agrees_with_prior_200_rows_160_states_four_per_source"])
        self.assertEqual(
            [result["by_reference_field"][f]["oracle_ceiling"] for f in legacy.FIELDS],
            [1.0, 1.0, 0.0, 0.0],
        )
        self.assertEqual(
            result["execution"]["original_source_files_verified_before_and_after"], 60
        )
        report = (self.root / "output/RESULT.json").read_bytes()
        self.assertNotIn(b"private-source", report)
        self.assertNotIn(b"RIGHT", report)
        self.assertEqual(self.data.read_bytes(), original)
        with self.assertRaises(FileExistsError):
            self.execute()

    def test_missing_field_keeps_all_forty_sources_unknown(self):
        for row in self.rows:
            if row["reference_field"] == "total":
                row["reference_field"] = "address"
                row["candidate_features"][0][0] = 2.0
                row["public_metadata"][:4] = [0.0, 0.0, 1.0, 0.0]
        self.refresh()
        result = self.execute()
        field = result["by_reference_field"]["total"]
        self.assertEqual(
            (
                field["registered_sources"],
                field["missing_sources"],
                field["oracle_ceiling"],
            ),
            (40, 40, None),
        )
        self.assertFalse(
            result["agrees_with_prior_200_rows_160_states_four_per_source"]
        )
        self.assertEqual(result["unique_states_per_source_histogram"], {"3": 40})

    def test_disjoint_partition_refuses_before_dataset_projection(self):
        self.plan["future_sources"][0] = self.sources[0]
        self.refresh()
        with patch.object(
            legacy, "project", side_effect=AssertionError("must not project")
        ) as project:
            with self.assertRaises(ValueError):
                self.execute()
        project.assert_not_called()
        self.assertFalse((self.root / "output").exists())

    def test_before_and_after_source_pin_drift_prevents_publication(self):
        path = Path(self.pins[-1]["path"])
        original = path.read_bytes()
        path.write_bytes(b"changed before")
        with self.assertRaises(ValueError):
            self.execute()
        path.write_bytes(original)
        real_project = legacy.project

        def drift(*args):
            result = real_project(*args)
            path.write_bytes(b"changed after")
            return result

        with patch.object(legacy, "project", side_effect=drift):
            with self.assertRaises(ValueError):
                self.execute()
        self.assertFalse((self.root / "output").exists())

    def test_bad_features_and_conflicting_duplicate_states_are_rejected(self):
        original = deepcopy(self.rows)
        self.rows[0]["candidate_features"][0].pop()
        self.refresh()
        with self.assertRaises(ValueError):
            self.execute()
        self.rows = original
        self.rows[4]["candidate_metadata"][0]["text"] = "CONFLICT"
        self.refresh()
        with self.assertRaises(ValueError):
            self.execute()


if __name__ == "__main__":
    unittest.main()
