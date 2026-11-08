"""Pilot persistence/provenance tests; synthetic execution grants no adoption."""

from contextlib import redirect_stdout
import hashlib
import io
from itertools import count
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import evolve1_pilot as pilot
from . import evolve1_reference as reference


class EvolvePilotChecks(unittest.TestCase):
    def test_adjacent_lineages_use_distinct_actual_data_including_discovery(self):
        samples, original = [], reference.dataset

        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            samples.append(pilot.data_pin(result))
            return result

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(pilot.time, "time", side_effect=count(1700000000).__next__),
            patch.object(reference, "dataset", side_effect=capture),
            patch.object(pilot, "dataset", side_effect=capture),
        ):
            groups = []
            for seed in (1, 2):
                block = pilot.run_block(seed, 1, Path(directory), {}, [])
                groups.extend(
                    group.rsplit(":", 1)[1]
                    for group_list in block["source_groups"].values()
                    for group in group_list
                )
        self.assertEqual(len(samples), 14)
        self.assertEqual(len(set(samples)), 14)
        self.assertEqual(sorted(groups), sorted(samples))

    def test_partial_serialization_or_failed_replace_preserves_old_checkpoint(self):
        def interrupted_dump(_value, stream, **_kwargs):
            stream.write('{"partial":')
            raise OSError("injected interrupted serialization")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            original = {"registry": {"sealed": False}, "attempts": ["registered"]}
            pilot.save_json(path, original)
            old_bytes = path.read_bytes()
            failures = (
                patch.object(reference.json, "dump", side_effect=interrupted_dump),
                patch.object(
                    reference.os, "replace", side_effect=OSError("replace failed")
                ),
            )
            for failure in failures:
                with failure, self.assertRaises(OSError):
                    pilot.save_json(path, {"replacement": True})
                self.assertEqual(path.read_bytes(), old_bytes)
                self.assertEqual(json.loads(path.read_text()), original)

    def test_short_pilot_persists_sealed_and_resolvable_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "pilot"
            with (
                patch(
                    "sys.argv",
                    ["pilot", "--output", str(out), "--seeds", "3", "--attempts", "1"],
                ),
                patch.object(
                    pilot.time, "time", side_effect=count(1700000000).__next__
                ),
                redirect_stdout(io.StringIO()),
            ):
                pilot.main()
            campaign = json.loads((out / "campaign.json").read_text())
            journal = json.loads((out / "lineage-3-journal.json").read_text())
            preregistered = json.loads((out / "preregistration.json").read_text())
            block = campaign["blocks"][0]
            for field in ("plan", "registry", "attempts"):
                self.assertEqual(journal[field], block[field])
            self.assertTrue(journal["registry"]["sealed"])
            entries = {
                entry["attempt_id"]: entry for entry in journal["registry"]["entries"]
            }
            self.assertEqual(len(entries), 4)
            self.assertEqual(len(journal["attempts"]), 4)
            self.assertEqual(len(journal["registry"]["finals"]), 4)
            records = journal["evaluation_records"]
            self.assertEqual(records, campaign["evaluation_records"])
            for reference, record in records.items():
                self.assertEqual(reference, pilot._sha(record))
            for attempt in journal["attempts"]:
                entry = entries[attempt["attempt_id"]]
                self.assertEqual(
                    (attempt["operation_id"], attempt["request_sha256"]),
                    (entry["operation_id"], entry["request_sha256"]),
                )
                self.assertEqual(
                    records[attempt["evaluation_reference"]]["candidate_bundle"],
                    attempt["candidate_digest"],
                )
            artifacts = journal["prepared_artifacts"]
            self.assertEqual(artifacts["source_groups"], block["source_groups"])
            self.assertEqual(
                artifacts["S1_origin"], "fixed_preparation_update_not_evolved_solver"
            )
            self.assertEqual(
                artifacts, json.loads((out / "lineage-3-improvers.json").read_text())
            )
            for run in journal["plan"]["runs"]:
                solver = run["pair_id"].rsplit(":", 1)[1]
                self.assertEqual(
                    pilot.bind(np.asarray(artifacts[solver])),
                    run["common_start"]["initial_bundle"],
                )
                self.assertEqual(
                    pilot._sha(artifacts[run["role"]]), run["improver_digest"]
                )
                selected = json.loads(
                    (
                        out / f"lineage-3-{solver}-{run['role']}-selection.json"
                    ).read_text()
                )
                final = journal["registry"]["finals"][run["run_id"]]
                self.assertEqual(pilot._sha(selected), final["selection_digest"])
                self.assertEqual(
                    pilot.bind(np.asarray(selected["weights"])),
                    final["candidate_bundle"],
                )
                observed = records[final["evaluation_reference"]]
                self.assertEqual(
                    observed["candidate_bundle"], final["candidate_bundle"]
                )
                self.assertLess(
                    selected["committed_unix_seconds"],
                    observed["observed_unix_seconds"],
                )
            for name, digest in preregistered["source_sha256"].items():
                self.assertEqual(
                    hashlib.sha256(
                        Path(pilot.__file__).with_name(name).read_bytes()
                    ).hexdigest(),
                    digest,
                )
            self.assertFalse(preregistered["independent_owner"])
            self.assertFalse(campaign["scientific_efficacy_qualified"])
            self.assertFalse(campaign["production_adoption_qualified"])
            self.assertFalse(campaign["report"]["authority_granted"])


if __name__ == "__main__":
    unittest.main()
