"""Adversarial retained-evidence tests; fixtures do not execute a native model."""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from environment import Owner, panels, schedule
from verify_results import verify


def dump(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


class EvidenceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.native = self.root / "native-fixture.bin"
        self.native.write_bytes(b"verifier fixture; not an executed binary")
        self.folder = self.root / "rag-seed-0"
        self.folder.mkdir()
        plan = schedule(0)
        owner, seen = Owner(0), set()
        owner_change = getattr(self, "owner_change", True)
        dump(
            self.root / "inputs.json",
            {
                "0": {
                    "schedule": plan,
                    "initial_facts": [asdict(f) for f in owner.facts.values()],
                }
            },
        )

        def answer(query):
            facts = [owner.resolve(source) for source in query]
            blocked = [
                fact is None or source not in seen for source, fact in zip(query, facts)
            ]
            expected = [fact.label for fact in facts] if all(facts) else None
            output = expected if not any(blocked) else None
            return {
                "output": output,
                "expected": expected,
                "blocked": blocked,
                "correct": output == expected,
                "eligible": all(facts),
                "answered": output is not None,
                "wrong_assertion": False,
                "stale_assertion": False,
                "invalid_assertion": False,
            }

        budget = {
            "kernel_multiplications": 5_000_000,
            "owner_checks": 100_000,
            "state_payload_bytes": 65_536,
            "pool_payload_bytes": 16_384,
        }
        self.manifest = {
            "schema": "hepta-mem1-reference-v1",
            "owner_change": owner_change,
            "arms": ["rag"],
            "seeds": [0],
            "planned_runs": 1,
            "budget": budget,
            "native_binary_sha256": hashlib.sha256(
                self.native.read_bytes()
            ).hexdigest(),
            "inputs_sha256": hashlib.sha256(
                (self.root / "inputs.json").read_bytes()
            ).hexdigest(),
        }
        self.events, summaries, offset = [], {}, 0
        state = b"retained state fixture"
        digest = hashlib.sha256(state).hexdigest()
        for phase, sources in plan:
            generation = 2 if owner_change and phase != "A1" else 1
            base = {"arm": "rag", "seed": 0, "generation": generation, "phase": phase}
            if phase == "B":
                if owner_change:
                    owner.change_rules_and_revoke()
                    seen.difference_update({"A:8", "A:9", "A:10", "A:11"})
                self.events.append(
                    {
                        **base,
                        "event": "owner_change" if owner_change else "owner_stationary",
                        "step": offset,
                    }
                )
            for i, source in enumerate(sources):
                step = offset + i + 1
                self.events.append(
                    {
                        **base,
                        "event": "prequential",
                        "step": step,
                        "sources": [source],
                        "before_update": True,
                        **answer([source]),
                    }
                )
                seen.add(source)
                if i == len(sources) // 2:
                    self.events.append(
                        {
                            **base,
                            "event": "recovery",
                            "step": step,
                            "matched": True,
                            "state": digest,
                        }
                    )
            restart = self.folder / f"restart-{phase}"
            restart.mkdir()
            (restart / "state.bin").write_bytes(state)
            (restart / "owner-witness.txt").write_text(digest + "\n")
            dump(self.folder / f"working-{phase}.json", {"h": [0.0] * 16, "pool": []})
            offset += len(sources)
            summaries[phase] = {}
            for panel, queries in panels().items():
                for query in queries:
                    self.events.append(
                        {
                            **base,
                            "event": "probe",
                            "step": offset,
                            "panel": panel,
                            "sources": list(query),
                            **answer(query),
                        }
                    )
                rows = self.events[-len(queries) :]
                summaries[phase][panel] = {
                    "n": len(queries),
                    "accuracy": sum(row["correct"] for row in rows) / len(rows),
                    "coverage": sum(row["answered"] for row in rows) / len(rows),
                    "wrong_assertions": 0,
                    "stale_assertions": 0,
                    "invalid_assertions": 0,
                }
        self.result = {
            "arm": "rag",
            "seed": 0,
            "status": "completed",
            "owner_change": owner_change,
            "panels": summaries,
            "retention_delta": 0.0,
            "b_prequential_accuracy": sum(
                row["correct"]
                for row in self.events
                if row["event"] == "prequential"
                and row["phase"] == "B"
                and row["sources"][0].startswith("B:")
            )
            / 96,
            "native_recoveries": [True, True, True],
            "coverage_floor_passed": True,
            "common_budget_cap": budget,
            "budget_passed": True,
            "capacity_and_compute": {
                "kernel_multiplications": 768,
                "owner_checks": 0,
                "pool_payload_bytes": 2,
                "state_payload_bytes": 3 * len(state) + 128,
            },
            "counts": {
                "online_updates": 0,
                "sleep_updates": 0,
                "rebuild_updates": 0,
                "owner_checks": 0,
                "recovery_checkpoint_operations": 3,
                "recovery_checkpoint_bytes": 3 * len(state),
                "encoder_multiplications": 0,
            },
        }

    def check(self):
        dump(self.root / "manifest.json", self.manifest)
        dump(self.root / "results.json", [self.result])
        (self.folder / "events.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in self.events)
        )
        return verify(self.root, native=self.native)

    def stabilized_fixture(self):
        """Add the fixed training work to the independent RAG evidence fixture."""
        renamed = self.root / "fast_stabilized-seed-0"
        self.folder.rename(renamed)
        self.folder = renamed
        self.manifest["arms"] = ["fast_stabilized"]
        self.result["arm"] = "fast_stabilized"
        self.result["counts"].update(
            online_updates=240, sleep_updates=128, rebuild_updates=8
        )
        self.result["capacity_and_compute"]["kernel_multiplications"] = 256000
        converted, slept = [], set()
        a1 = schedule(0)[0][1]
        rebuild = sorted(
            (f"A:{i}" for i in range(8)),
            key=lambda source: max(i for i, item in enumerate(a1) if item == source),
        )
        for row in self.events:
            base = {
                "arm": "fast_stabilized",
                "seed": 0,
                "step": row["step"],
                "generation": row["generation"],
            }
            if row["event"] == "owner_change":
                converted.extend(
                    {**base, "event": "update", "kind": "rebuild", "source": source}
                    for source in rebuild
                )
            elif row["event"] == "prequential":
                converted.append(
                    {
                        **base,
                        "event": "update",
                        "kind": "online",
                        "source": row["sources"][0],
                    }
                )
            elif row["event"] == "probe" and row["phase"] in {"A1", "B"} - slept:
                phase = row["phase"]
                slept.add(phase)
                converted.extend(
                    {
                        **base,
                        "event": "update",
                        "kind": "sleep",
                        "source": "A:0",
                        "source_version": 1,
                    }
                    for _ in range(64)
                )
                candidate = b"candidate fixture"
                (self.folder / f"candidate-{phase}.bin").write_bytes(candidate)
                receipt = {
                    "sha256": hashlib.sha256(candidate).hexdigest(),
                    "model_adoption": "NoUpdate",
                    "updates": 64,
                    "owner_generation": row["generation"],
                    "capacity_expansion": False,
                    "selected_shared_model_changed": False,
                    "source_lineage": [
                        {"source": "A:0", "version": 1} for _ in range(64)
                    ],
                }
                converted.append(
                    {**base, "event": "sleep_candidate", "phase": phase, **receipt}
                )
                dump(self.folder / f"candidate-{phase}.json", receipt)
            converted.append({**row, "arm": "fast_stabilized"})
        self.events = converted

    def test_stabilized_reference_charges_rebuild_and_teacher_work(self):
        self.stabilized_fixture()
        report = self.check()
        self.assertEqual(
            report["cost_audit"]["runs"][0]["recomputed"]["kernel_multiplications"],
            256000,
        )

    def test_review_underreporting_attacks_are_rejected(self):
        self.stabilized_fixture()
        events, result = copy.deepcopy(self.events), copy.deepcopy(self.result)
        for attack, cost in [
            ("late_boundary", 229376),
            ("deleted_rebuild", 252672),
            ("relocated_sleep", 247808),
        ]:
            with self.subTest(attack=attack):
                self.events, self.result = copy.deepcopy(events), copy.deepcopy(result)
                if attack == "late_boundary":
                    boundary = next(
                        row for row in self.events if row["event"] == "owner_change"
                    )
                    self.events.remove(boundary)
                    self.events.append(boundary)
                elif attack == "deleted_rebuild":
                    self.events = [
                        row for row in self.events if row.get("kind") != "rebuild"
                    ]
                    self.result["counts"]["rebuild_updates"] = 0
                else:
                    moved = [
                        row
                        for row in self.events
                        if row.get("kind") == "sleep" and row["step"] == 200
                    ]
                    self.events = [
                        row
                        for row in self.events
                        if not (row.get("kind") == "sleep" and row["step"] == 200)
                    ]
                    for row in moved:
                        row.update(step=96, generation=1)
                    index = next(
                        i
                        for i, row in enumerate(self.events)
                        if row["event"] == "sleep_candidate"
                    )
                    self.events[index:index] = moved
                self.result["capacity_and_compute"]["kernel_multiplications"] = cost
                with self.assertRaisesRegex(ValueError, "raw operation roster"):
                    self.check()

    def test_same_step_boundary_must_follow_a1_probes_and_rebuild(self):
        self.stabilized_fixture()
        boundary = next(row for row in self.events if row["event"] == "owner_change")
        self.events.remove(boundary)
        index = next(i for i, row in enumerate(self.events) if row["event"] == "probe")
        self.events.insert(index, boundary)
        with self.assertRaisesRegex(ValueError, "raw operation roster"):
            self.check()

    def test_rebuild_must_use_the_frozen_eligible_sources(self):
        self.stabilized_fixture()
        next(row for row in self.events if row.get("kind") == "rebuild")["source"] = (
            "B:0"
        )
        with self.assertRaisesRegex(ValueError, "raw operation roster"):
            self.check()

    def test_replay_candidate_json_cannot_be_removed(self):
        self.stabilized_fixture()
        (self.folder / "candidate-A1.json").unlink()
        (self.folder / "candidate-B.json").unlink()
        with self.assertRaisesRegex(ValueError, "candidate artifact roster"):
            self.check()

    def test_candidate_bytes_lineage_and_adoption_are_bound(self):
        self.stabilized_fixture()
        event = next(row for row in self.events if row["event"] == "sleep_candidate")
        path = self.folder / "candidate-A1.json"
        original = path.read_text()
        for field, value, message in [
            ("sha256", "0" * 64, "candidate bytes, receipt and event"),
            ("source_lineage", [], "candidate lineage"),
            ("model_adoption", "Update", "unqualified shared-model adoption"),
        ]:
            with self.subTest(field=field):
                receipt = json.loads(original)
                old = event[field]
                event[field] = receipt[field] = value
                dump(path, receipt)
                with self.assertRaisesRegex(ValueError, message):
                    self.check()
                event[field] = old

    def test_candidate_lineage_cannot_count_a_probe_as_training(self):
        self.stabilized_fixture()
        probe = next(row for row in self.events if row["event"] == "probe")
        probe.update(kind="sleep", source="A:0", source_version=1)
        event = next(row for row in self.events if row["event"] == "sleep_candidate")
        event["source_lineage"].append({"source": "A:0", "version": 1})
        path = self.folder / "candidate-A1.json"
        receipt = json.loads(path.read_text())
        receipt["source_lineage"] = event["source_lineage"]
        dump(path, receipt)
        with self.assertRaisesRegex(ValueError, "candidate lineage"):
            self.check()

    def test_reference_checks_remain_explicitly_partial(self):
        report = self.check()
        self.assertEqual(
            report["raw_events"],
            {"prequential": 240, "recovery": 3, "probe": 60, "owner_change": 1},
        )
        self.assertEqual(
            report["native_binary"],
            {
                "verified": True,
                "bytes": len(self.native.read_bytes()),
                "sha256": self.manifest["native_binary_sha256"],
                "scope": "supplied artifact bytes; not execution attestation",
            },
        )
        self.assertEqual(
            (
                report["verified_runs"],
                report["cost_audit"]["status"],
                report["cost_audit"]["complete_cost_verified"],
                report["scientific_qualification"],
                report["production_adoption"],
            ),
            (1, "PARTIAL", False, "HOLD", "NoUpdate"),
        )

    def test_zero_costs_do_not_pass_the_budget_check(self):
        self.result["capacity_and_compute"] = dict.fromkeys(
            self.result["capacity_and_compute"], 0
        )
        with self.assertRaisesRegex(ValueError, "kernel_multiplications differs"):
            self.check()

    def test_recomputed_counters_reject_underreporting_and_nonintegers(self):
        original = copy.deepcopy(self.result)
        for section, key in [
            ("capacity_and_compute", "state_payload_bytes"),
            ("counts", "recovery_checkpoint_operations"),
            ("counts", "recovery_checkpoint_bytes"),
            ("counts", "encoder_multiplications"),
        ]:
            with self.subTest(counter=key):
                self.result = copy.deepcopy(original)
                self.result[section][key] = self.result[section][key] + 1
                with self.assertRaisesRegex(ValueError, key + " differs"):
                    self.check()
        for value in [False, -1, float("nan")]:
            with self.subTest(value=value):
                self.result = copy.deepcopy(original)
                self.result["capacity_and_compute"]["kernel_multiplications"] = value
                with self.assertRaisesRegex(ValueError, "nonnegative integers"):
                    self.check()

    def test_recovery_summary_requires_three_actual_booleans(self):
        for flags in [[], [True, True], [True] * 4, [1, 1, 1], [True, False, True]]:
            with self.subTest(flags=flags):
                self.result["native_recoveries"] = flags
                with self.assertRaisesRegex(ValueError, "exact nonempty roster"):
                    self.check()

    def test_duplicate_recovery_phase_is_not_three_recoveries(self):
        rows = [row for row in self.events if row["event"] == "recovery"]
        rows[1]["phase"] = rows[0]["phase"]
        with self.assertRaisesRegex(ValueError, "raw operation roster"):
            self.check()

    def test_recovery_requires_the_exact_step(self):
        next(row for row in self.events if row["event"] == "recovery")["step"] += 1
        with self.assertRaisesRegex(ValueError, "raw operation roster"):
            self.check()

    def test_recovery_state_bytes_must_match_despite_true_flags(self):
        (self.folder / "restart-A1/state.bin").write_bytes(b"different bytes")
        with self.assertRaisesRegex(
            ValueError, "state bytes, owner witness and event disagree"
        ):
            self.check()

    def test_missing_witness_cannot_pass(self):
        (self.folder / "restart-A1/owner-witness.txt").unlink()
        with self.assertRaises(FileNotFoundError):
            self.check()

    def test_binary_identity_is_checked_against_actual_bytes(self):
        self.manifest["native_binary_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "native binary bytes differ"):
            self.check()

    def test_replaced_binary_cannot_reuse_the_original_identity(self):
        self.native.write_bytes(b"replacement")
        with self.assertRaisesRegex(ValueError, "native binary bytes differ"):
            self.check()

    def test_pool_peak_cannot_undercut_a_retained_snapshot(self):
        dump(
            self.folder / "working-B.json",
            {"h": [0.0] * 16, "pool": [{"source": "retained"}]},
        )
        with self.assertRaisesRegex(ValueError, "pool peak is below"):
            self.check()

    def test_duplicate_probe_does_not_preserve_the_registered_roster(self):
        probes = [row for row in self.events if row["event"] == "probe"]
        probes[1]["sources"] = probes[0]["sources"]
        with self.assertRaisesRegex(ValueError, "raw operation roster"):
            self.check()

    def test_cli_requires_explicit_native_artifact(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("verify_results.py")),
                str(self.root),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--native", result.stderr)


if __name__ == "__main__":
    unittest.main()
