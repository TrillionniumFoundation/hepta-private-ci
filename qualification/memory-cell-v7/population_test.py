"""Actual fits and automatic partitions; no independent held corpus is used."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from population_training import address_partition, load_shards, sha, train_populations
from test_training import fixture
from training import current_rows


CONFIG = {"shard_count": 2, "seed": 29, "steps": 160, "dimension": 32, "total_hidden": 32, "threshold": 0.9}


class PopulationTests(unittest.TestCase):
    def test_actual_split_merge_preserves_exact_sources_and_new_domain_readback(self):
        export = fixture(16)
        for row in export["records"]:
            row["record"]["entity"] = row["record"]["entity"].replace("fresh-cell", "new-domain-sensor")
        for count in (1, 2, 4):
            result = train_populations(export, {**CONFIG, "shard_count": count})
            self.assertEqual(result["receipt"]["fit_calls"], 2 * count)
            for kind, rows in current_rows(export).items():
                wire, cells = load_shards(result["artifacts"][kind])
                lineage = set()
                for cell in cells:
                    self.assertTrue(lineage.isdisjoint(cell.lineage_sources))
                    lineage.update(cell.lineage_sources)
                    self.assertIsNone(cell.training_receipt["parent_parameters"])
                    self.assertNotEqual(cell.training_receipt["initial_parameters"], cell.parameters_digest())
                self.assertEqual(sorted(lineage), sorted(row["source_id"] for row in rows))
                for row in rows:
                    key = row["record"]["entity"]
                    read = cells[wire["routes"][sha(key.encode())]].read(key)
                    self.assertEqual((read["value"], read["support_ids"]), (row["record"]["value"], [row["source_id"]]))
                self.assertNotIn(sha(b"never-written-entity"), wire["routes"])

    def test_partition_ignores_targets_and_clean_rebuild_drops_superseded_lineage(self):
        export = fixture(8)
        first = train_populations(export, CONFIG)
        changed = deepcopy(export)
        row = next(row for row in changed["records"] if row["record"]["kind"] == "semantic")
        old = row["source_id"]
        row["source_id"], row["revision"] = sha(b"replacement-source"), 2
        row["record"]["value"] = {"factor": 23, "label": "new-specialty"}
        changed["current_source_ids"].remove(old)
        changed["current_source_ids"].append(row["source_id"])
        second = train_populations(changed, CONFIG)
        for kind in ("semantic", "procedure"):
            before = json.loads(first["artifacts"][kind]["native"])
            after = json.loads(second["artifacts"][kind]["native"])
            self.assertEqual(before["routes"], after["routes"])
        self.assertNotIn(old, json.loads(second["artifacts"]["semantic"]["native"])["lineage_sources"])
        with self.assertRaisesRegex(ValueError, "count"):
            address_partition(["one"], 2)

    def test_bounded_process_preserves_exact_request_and_rejects_duplicate_fields(self):
        worker = Path(__file__).with_name("population_worker.py")
        raw = json.dumps({"schema": "hepta.memory.population-training-request.v2", "export": fixture(8), "configuration": CONFIG}).encode()
        result = subprocess.run([sys.executable, "-I", "-u", "-B", str(worker)], input=raw, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(json.loads(result.stdout)["request_digest"], sha(raw))
        invalid = subprocess.run([sys.executable, str(worker)], input=b'{"schema":1,"schema":2}', capture_output=True, timeout=10)
        self.assertEqual((invalid.returncode, invalid.stdout), (2, b""))


if __name__ == "__main__":
    unittest.main()
