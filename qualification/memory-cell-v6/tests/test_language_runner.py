"""Development checks use tiny authored fixtures, never the sealed held corpus."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import prepare_run
import run_language
from v6.runtime import train_snapshot
from v6.study_data import AT, LATEST, SINCE, create_sources


class LanguageRunnerTests(unittest.TestCase):
    def test_unverified_freeze_never_opens_held(self):
        with (
            patch.object(
                run_language, "verify_run", side_effect=ValueError("uncommitted source")
            ),
            patch.object(run_language, "read_held") as opener,
        ):
            with self.assertRaisesRegex(ValueError, "uncommitted"):
                run_language.evaluate(
                    "unused", "unused", "0" * 64, "never-open-this-directory"
                )
            opener.assert_not_called()

    def test_source_admission_requires_commit_bytes_and_complete_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            project = repository / "qualification" / "memory-cell-v6"
            project.mkdir(parents=True)
            (project / "execution.py").write_text("value = 1\n")
            (project / "PROTOCOL.json").write_text("{}\n")
            other = project.parent / "memory-cell-v2"
            other.mkdir()
            (other / "MODEL_SOURCE.json").write_text("{}\n")
            for command in (
                ["init"],
                ["add", "."],
                [
                    "-c",
                    "user.name=V6 Test",
                    "-c",
                    "user.email=v6-test@example.invalid",
                    "commit",
                    "-m",
                    "Synthetic admission fixture",
                ],
            ):
                subprocess.run(
                    ["git", *command],
                    cwd=repository,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            with (
                patch.object(prepare_run, "PROJECT", project),
                patch.object(prepare_run, "REPOSITORY", repository),
            ):
                commit, files = prepare_run.git_head(), prepare_run.code_bindings()
                prepare_run.verify_committed(files, commit)
                (project / "execution.py").write_text("value = 2\n")
                with self.assertRaisesRegex(ValueError, "frozen file"):
                    prepare_run.verify_committed(files, commit)
                (project / "execution.py").write_text("value = 1\n")
                (project / "unsealed.py").write_text("value = 3\n")
                with self.assertRaisesRegex(ValueError, "inventory"):
                    prepare_run.verify_committed(files, commit)
                (project / "unsealed.py").unlink()
                (project / "development").mkdir()
                (project / "development" / "historical.py").write_text(
                    "archived = True\n"
                )
                prepare_run.verify_committed(files, commit)

    def test_request_slots_do_not_carry_grader_targets_and_raw_flags_are_recomputed(
        self,
    ):
        query = {
            "id": "toy-current",
            "text": "Read {entity} at {at}.",
            "operation": "current",
            "language": "en",
            "family": "toy",
            "forbidden_gold": 999,
        }
        record = {
            "entity": "entity-a",
            "scope": "toy",
            "events": [4, 6, 9],
            "semantic": {"factor": 2, "label": "group"},
            "procedure": {"opcode": "identity", "bias": 0, "limit": 20},
            "sources": {
                str(SINCE): "1" * 64,
                str(AT): "2" * 64,
                str(LATEST): "3" * 64,
                "semantic": "4" * 64,
                "procedure": "5" * 64,
            },
        }
        truth = {"scope": "toy", "entities": {"entity-a": record}}
        case = {"seed": 1, "domain": "toy", "snapshot_digest": "6" * 64}
        plan = {
            "time_contract": {"at": AT, "since": SINCE},
            "execution_budget": {"max_read_hops": 4, "max_cells": 3},
        }
        request = run_language.requests_for(
            [query], case, truth, plan, "parameter_actual"
        )[0]
        self.assertEqual(request.entity, "entity-a")
        self.assertNotIn("999", str(request.as_dict()))
        self.assertNotIn("gold_operation", request.as_dict())
        result = {
            "value": 4,
            "source_ids": ["1" * 64],
            "status": "ok",
            "snapshot_digest": "6" * 64,
            "generation": 1,
            "hops": 1,
            "prediction_kind": "source_evidence",
            "reason": None,
            "cell_digests": [],
            "transport": {"rpc_bytes": 30, "validation_attempts": 1, "node_count": 1},
        }
        raw = run_language.make_record(
            query, request, case, truth, "current", result, "7" * 64, "8" * 64, 0.2, 0.1
        )
        self.assertEqual(
            (
                raw["expected_value"],
                raw["actual_value"],
                raw["value_correct"],
                raw["source_correct"],
                raw["source_versions_valid"],
            ),
            (9, 4, False, False, True),
        )
        self.assertEqual(raw["transport"], result["transport"])
        self.assertAlmostEqual(raw["read_plus_amortized_routing_seconds"], 0.3)

    def test_exact_deployment_works_without_parameter_objects_and_charges_validation(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / "case"
            case.mkdir()
            truth = create_sources(
                case / "source.sqlite", seed=37, domain="toy", count=2
            )
            receipt = train_snapshot(
                case / "source.sqlite",
                case / "artifacts",
                scope=truth["scope"],
                seed=37,
                hidden=8,
                steps=15,
            )
            query = {
                "id": "toy",
                "text": "Read {entity}.",
                "operation": "current",
                "language": "en",
                "family": "toy",
            }
            plan = {
                "time_contract": {"at": AT, "since": SINCE},
                "execution_budget": {"max_read_hops": 4, "max_cells": 3},
            }
            case_info = {
                "seed": 37,
                "domain": "toy",
                "snapshot_digest": receipt["snapshot_digest"],
            }
            request = run_language.requests_for(
                [query], case_info, truth, plan, "exact_same_router"
            )[0]
            with run_language.deploy(
                case, root / "deploy", receipt["snapshot_digest"], 3
            ) as (networks, nodes, costs):
                self.assertEqual(len({node.process.pid for node in nodes}), 6)
                self.assertEqual(
                    [row["has_parameter_objects"] for row in costs["deployments"]],
                    [True, True, True, False, False, False],
                )
                result = networks["exact"].read(request, "current")
                self.assertEqual(
                    (result["status"], result["value"]),
                    ("ok", truth["entities"][request.entity]["events"][2]),
                )
                transport = result["transport"]
                self.assertEqual(
                    (
                        transport["rpc_attempts"],
                        transport["read_attempts"],
                        transport["validation_attempts"],
                    ),
                    (2, 1, 1),
                )
                self.assertEqual(
                    transport["rpc_bytes"],
                    transport["attempted_request_bytes"]
                    + transport["received_response_bytes"],
                )
            self.assertGreater(costs["child_cpu_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
