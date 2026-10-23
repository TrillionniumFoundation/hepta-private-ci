"""Answer-free capabilities, raw/support separation and actual fresh-reader wiring."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from learned_router import fit_router
from parametric_model import SourceMemoryCell
from parametric_owner import Frontier, ParametricOwner
from population_fixtures import dataset
from population_reads import (
    fresh_read,
    probe_eligibility,
    read_final,
    score_single,
    source_capabilities,
)
import test_parametric_model as tiny_fixture


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)


class CapabilityAndScoringTests(unittest.TestCase):
    def setUp(self):
        self.data = dataset(1907)
        self.capabilities = source_capabilities(self.data["sources"])
        self.version = {
            "roots": [r["source_digest"] for r in self.data["sources"]],
            "manifest_sha256": "a" * 64,
        }

    def test_capability_metadata_has_no_stored_answers_or_program_coefficients(self):
        forbidden = {"value", "location", "multiplier", "offset", "modulus", "question"}
        self.assertTrue(
            all(not forbidden.intersection(row) for row in self.capabilities)
        )
        for probe in self.data["transfer_final"]:
            without_gold = {
                k: v
                for k, v in probe.items()
                if k not in ("value", "question", "family")
            }
            self.assertTrue(
                probe_eligibility(without_gold, self.version, self.capabilities)[
                    "capability_allowed"
                ]
            )

    def test_before_history_unknown_does_not_become_supported_just_from_nonempty_roots(
        self,
    ):
        probe = self.data["ood_final"][-1]
        eligibility = probe_eligibility(probe, self.version, self.capabilities)
        self.assertTrue(eligibility["source_supported"])
        self.assertFalse(eligibility["operation_supported"])
        self.assertFalse(eligibility["capability_allowed"])
        corrupted_gold = {**probe, "value": "arbitrary"}
        self.assertEqual(
            probe_eligibility(corrupted_gold, self.version, self.capabilities),
            eligibility,
        )

    def test_asof_requires_complete_history_and_exact_declared_roots(self):
        probe = self.data["transfer_final"][0]
        incomplete = {**self.version, "roots": probe["source_roots"][:-1]}
        self.assertFalse(
            probe_eligibility(probe, incomplete, self.capabilities)[
                "capability_allowed"
            ]
        )
        forged = {**probe, "source_roots": probe["source_roots"][:1]}
        eligibility = probe_eligibility(forged, self.version, self.capabilities)
        self.assertTrue(eligibility["source_supported"])
        self.assertFalse(eligibility["declared_roots_match"])
        self.assertFalse(eligibility["capability_allowed"])

    def test_raw_lucky_unsupported_output_does_not_count_as_memory(self):
        probe = self.data["retention_final"][0]
        journal = {"rows": [{"question": probe["question"], "text": probe["value"]}]}
        unsupported = {**self.version, "roots": []}
        scored = score_single([probe], journal, unsupported, self.capabilities)
        self.assertEqual(
            (
                scored["metrics"]["retention"]["raw_exact_match"],
                scored["metrics"]["retention"]["accuracy"],
            ),
            (1.0, 0.0),
        )
        journal["rows"][0]["text"] += " "
        scored = score_single([probe], journal, self.version, self.capabilities)
        self.assertEqual(scored["metrics"]["retention"]["raw_exact_match"], 0.0)

    def test_decoded_unknown_is_separate_from_action_abstention(self):
        probe = self.data["ood_final"][-1]
        journal = {"rows": [{"question": probe["question"], "text": "unknown"}]}
        metrics = score_single([probe], journal, self.version, self.capabilities)[
            "metrics"
        ]["unknown"]
        self.assertEqual(
            (
                metrics["correct"],
                metrics["supported_correct"],
                metrics["decoder_unknown"],
                metrics["action_abstentions"],
            ),
            (1, 0, 1, 0),
        )

    def test_final_plan_commits_before_every_worker_and_before_gold_scoring(self):
        data = self.data
        flag = {"allow_gold": False}

        class GuardedProbe(dict):
            def __getitem__(self, key):
                if key == "value" and not flag["allow_gold"]:
                    raise AssertionError(
                        "final gold accessed before all workers completed"
                    )
                return super().__getitem__(key)

        golden = {
            p["question"]: p["value"]
            for name in ("retention_final", "transfer_final", "ood_final")
            for p in data[name]
        }
        for name in ("retention_final", "transfer_final", "ood_final"):
            data[name] = [GuardedProbe(p) for p in data[name]]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            version = {
                **self.version,
                "directory": str(directory / "unused"),
                "rank": 4,
                "seed": 1907,
            }
            versions = {
                "parent": [version],
                "single": [{**version, "rank": 8}],
                "split": [version, version],
            }
            router = fit_router(
                [
                    {
                        "question": p["question"],
                        "utilities": [1.0, 1.0],
                        "reject": False,
                    }
                    for p in data["router_training"]
                ],
                expert_ids=["split-0", "split-1"],
                source_sha256="b" * 64,
            )
            router_path = directory / "router.bin"
            receipt = router.save(router_path)
            selection = {
                "versions": versions,
                "choice": {"chosen_arm": "single"},
                "final_scores_used": False,
                "sources_sha256": data["sources_sha256"],
                "router_path": str(router_path),
                "router_receipt": receipt,
            }
            selection_path = directory / "selection.json"
            write_json(selection_path, selection)
            selection.update(
                selection_path=str(selection_path),
                selection_sha256=hashlib.sha256(
                    selection_path.read_bytes()
                ).hexdigest(),
            )
            seen = []

            def mock_read(
                model,
                selected,
                questions,
                output,
                label,
                owner,
                frontier,
                writer,
                *,
                context=None,
            ):
                self.assertTrue((output / "route-plan-commit.json").is_file())
                self.assertEqual(
                    hashlib.sha256(
                        (output / "route-plan.json").read_bytes()
                    ).hexdigest(),
                    context["route_plan_sha256"],
                )
                self.assertFalse(flag["allow_gold"])
                seen.append((label, len(questions)))
                if label == "final-parent":
                    flag["allow_gold"] = True
                path = output / f"{label}-journal.json"
                journal = {
                    "rows": [
                        {
                            "question": q,
                            "text": golden[q],
                            "input_tokens": 7,
                            "generated_tokens": 1,
                            "seconds": 0.01,
                        }
                        for q in questions
                    ],
                    "fresh_process_wall_seconds": 1.0,
                    "owner_admitted_before_and_after": True,
                    "active_version": selected,
                    "journal_path": str(path),
                }
                writer(path, journal)
                return journal

            with patch("population_reads.fresh_read", side_effect=mock_read):
                result = read_final(
                    "unused",
                    data,
                    {"versions": versions},
                    selection,
                    directory / "final",
                    write_json,
                )
            self.assertEqual(
                seen,
                [
                    ("final-single", 120),
                    ("final-split-0", 120),
                    ("final-split-1", 120),
                    ("final-parent", 16),
                ],
            )
            self.assertEqual(result["work"]["queries"], 376)
            self.assertEqual(result["work"]["fresh_process_wall_seconds"], 4.0)
            self.assertEqual(result["parent_semantic_recall"], 1.0)
            self.assertEqual(
                result["parent_correct_semantic_preserved"]["single"], True
            )
            self.assertEqual(result["metrics"]["oracle"]["known"]["accuracy"], 1.0)
            self.assertEqual(
                result["metrics"]["uniform_random"]["known"]["accuracy"], 1.0
            )
            self.assertEqual(
                result["metrics"]["split_metadata_only"]["known"]["accuracy"], 1.0
            )
            self.assertFalse(result["routing"]["learned_beats_metadata_only_known"])
            self.assertEqual(result["routing"]["guarded_ood_abstention_rate"], 1.0)
            self.assertEqual(result["metrics"]["selected"], result["metrics"]["single"])


class ActualFreshReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny_fixture.SourceMemoryCellTests.setUpClass()
        cls.base = tiny_fixture.SourceMemoryCellTests.base

    @classmethod
    def tearDownClass(cls):
        tiny_fixture.SourceMemoryCellTests.tearDownClass()

    def test_nondefault_rank_seed_and_raw_generation_survive_actual_owner_worker_reload(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            cell = SourceMemoryCell(self.base, rank=4, seed=1907)
            cell.reset("alpha")
            cell.fit_sources(
                [tiny_fixture.fact("one", "red", "a")], 2, 0.001, tiny_fixture.TEMPLATES
            )
            checkpoint = directory / "snapshot"
            manifest = cell.save(checkpoint)
            version = {
                "directory": str(checkpoint),
                "manifest_sha256": manifest,
                "roots": ["a" * 64],
                "rank": 4,
                "seed": 1907,
            }
            questions = ["What is the color of one?", "What is the color of two?"]
            expected = cell.generate(questions)
            output = directory / "reads"
            output.mkdir()
            journal = fresh_read(
                self.base,
                version,
                questions,
                output,
                "tiny-reader",
                ParametricOwner(output / "owner.sqlite3"),
                Frontier("alpha"),
                write_json,
                context={"route_plan_sha256": "c" * 64},
            )
            self.assertEqual(
                [(r["text"], r["token_ids"]) for r in journal["rows"]],
                [(r["text"], r["token_ids"]) for r in expected],
            )
            request = json.loads((output / "tiny-reader-request.json").read_text())
            self.assertEqual(
                set(request),
                {
                    "model",
                    "snapshot",
                    "manifest_sha256",
                    "scope",
                    "allowed_roots",
                    "questions",
                    "rank",
                    "seed",
                    "control",
                },
            )
            self.assertEqual((request["rank"], request["seed"]), (4, 1907))
            self.assertTrue(journal["owner_admitted_before_and_after"])
            self.assertEqual(journal["owner_query_roots"], ["a" * 64])
            self.assertTrue((output / "reader-cwd").is_dir())
            self.assertGreater(journal["fresh_process_wall_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
