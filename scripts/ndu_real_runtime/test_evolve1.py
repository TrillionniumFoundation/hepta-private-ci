"""Adversarial EVOLVE-1 accounting fixtures; never production owner evidence."""

from copy import deepcopy
import unittest

from ._causal_checks import ACEValidationError, COST_UNITS
from .evolve1 import summarize_transfer
from .test_causal_ace import e_fixture, pin


def transfer_fixture(lineage="lineage-0"):
    plan, registry, attempts, evaluations = None, None, [], {}
    for solver in ("S0", "S1"):
        subplan, subregistry, rows, records = e_fixture()
        tag = lineage + "/" + solver + "/"
        missing = deepcopy(rows[1])
        missing.update(
            {
                key: subregistry["entries"][2][key]
                for key in ("attempt_id", "operation_id", "request_sha256")
            }
        )
        missing.update(
            candidate_digest=pin("parent3"), rolled_back=False, rollback_reference=None
        )
        rows.append(missing)
        subplan["improvers"]["child"]["artifact_digest"] = pin(lineage + "/child")
        for run in subplan["runs"]:
            run.update(
                run_id=tag + run["run_id"],
                pair_id=solver,
                improver_digest=subplan["improvers"][run["role"]]["artifact_digest"],
            )
            run["common_start"]["initial_bundle"] = pin(solver)
        for entry in subregistry["entries"] + rows:
            for key in ("run_id", "attempt_id", "operation_id"):
                entry[key] = tag + entry[key]
        for row in rows:
            row["candidate_digest"] = pin(tag + row["candidate_digest"])
            if row["evaluation_reference"]:
                row["evaluation_reference"] = pin(tag + row["evaluation_reference"])
        for final in subregistry["finals"].values():
            final["attempt_id"] = tag + final["attempt_id"]
            for key in ("candidate_bundle", "selection_digest", "evaluation_reference"):
                final[key] = pin(tag + final[key])
        for key in ("finals", "run_overheads"):
            subregistry[key] = {
                tag + key_: value for key_, value in subregistry[key].items()
            }
        for (kind, reference), record in records.items():
            record.update(
                run_id=tag + record["run_id"],
                baseline_bundle=pin(solver),
                candidate_bundle=pin(tag + record["candidate_bundle"]),
            )
            if kind == "acceptance":
                for key in ("attempt_id", "operation_id"):
                    record[key] = tag + record[key]
            else:
                record.update(
                    selection_digest=pin(tag + record["selection_digest"]),
                    retention_baseline=0.8,
                    retention_candidate=0.8,
                    retention_data_digest=pin("retention-bytes"),
                )
            evaluations[(kind, pin(tag + reference))] = record
        if plan is None:
            plan, registry = subplan, subregistry
        else:
            plan["runs"].extend(subplan["runs"])
            registry["entries"].extend(subregistry["entries"])
            for key in ("run_overheads", "finals"):
                registry[key].update(subregistry[key])
        attempts.extend(rows)
    return {
        "lineage_id": lineage,
        "plan": plan,
        "registry": registry,
        "attempts": attempts,
        "solver_rows": {pin("S0"): "S0", pin("S1"): "S1"},
        "historical_costs": dict.fromkeys(COST_UNITS, 77.0),
        "source_groups": {
            split: [split + "-group"]
            for split in (
                "training",
                "development",
                "acceptance",
                "holdout",
                "retention",
            )
        },
        "retention_data_digest": pin("retention-bytes"),
    }, evaluations


def remap_identifiers(value, aliases):
    """Rename exact fixture identities, including run-keyed registries."""
    if isinstance(value, dict):
        return {
            aliases.get(key, key): remap_identifiers(item, aliases)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [remap_identifiers(item, aliases) for item in value]
    return aliases.get(value, value) if isinstance(value, str) else value


def retained_fixture():
    block, records = transfer_fixture()
    final = block["registry"]["finals"]["lineage-0/S0/parent"]
    final.update(attempt_id=None, candidate_bundle=pin("S0"))
    records[("heldout_final", final["evaluation_reference"])][
        "candidate_bundle"
    ] = pin("S0")
    return block, records


class EvolveTransferChecks(unittest.TestCase):
    def assess(self, block, records, **options):
        return summarize_transfer(
            [block] if isinstance(block, dict) else block,
            minimum_gain=options.pop("minimum_gain", 0.1),
            maximum_retention_loss=0.05,
            read_evaluation=lambda kind, ref: records.get((kind, ref)),
            verify_evaluation=lambda _kind, record, owner: record["actor_id"] == owner,
            **options,
        )

    def test_four_cells_account_without_granting_scientific_or_owner_authority(self):
        block, records = transfer_fixture()
        report = self.assess(block, records)
        self.assertEqual(set(report["cells"]), {"S0-I0", "S0-I1", "S1-I0", "S1-I1"})
        for cell in report["cells"].values():
            self.assertEqual(
                (
                    cell["registered_runs"],
                    cell["qualified_runs"],
                    cell["unresolved_runs"],
                ),
                (1, 1, 0),
            )
            self.assertEqual(cell["cost_totals"], dict.fromkeys(COST_UNITS, 4.0))
        self.assertFalse(report["scientific_efficacy_qualified"])
        self.assertFalse(report["authority_granted"])
        self.assertEqual(
            report["historical_costs"]["totals"], dict.fromkeys(COST_UNITS, 77.0)
        )
        self.assertFalse(report["historical_costs"]["amortized"])

    def test_missing_arm_wrong_start_budget_or_cross_row_context_is_rejected(self):
        for mutation in ("arm", "start", "budget", "cross_row"):
            with self.subTest(mutation=mutation):
                block, records = transfer_fixture()
                runs = block["plan"]["runs"]
                if mutation == "arm":
                    runs.pop()
                elif mutation == "budget":
                    runs[1]["full_budget_contract"]["limits"]["cpu_seconds"] += 1
                else:
                    for run in runs[2:] if mutation == "cross_row" else [runs[1]]:
                        run["common_start"]["seed"] += 1
                with self.assertRaises(ACEValidationError):
                    self.assess(block, records)

    def test_confirmation_leakage_and_pseudoreplicated_lineages_are_rejected(self):
        for mutation in ("groups", "posthoc", "lineage", "child"):
            with self.subTest(mutation=mutation):
                block, records = transfer_fixture()
                blocks = [block]
                if mutation == "groups":
                    block["source_groups"]["holdout"] = block["source_groups"][
                        "training"
                    ]
                elif mutation == "posthoc":
                    for (kind, _), record in records.items():
                        if kind == "heldout_final":
                            record["selection_committed_unix_seconds"] = 21
                else:
                    other = deepcopy(block)
                    if mutation == "child":
                        other["lineage_id"] = "fake-independent-lineage"
                    blocks.append(other)
                with self.assertRaises(ACEValidationError):
                    self.assess(blocks, records)

    def test_invalid_online_and_historical_costs_are_rejected(self):
        for bad in (True, -1, float("nan"), float("inf"), 10**1000):
            for scope in ("online", "historical"):
                with self.subTest(value=repr(bad)[:20], scope=scope):
                    block, records = transfer_fixture()
                    costs = (
                        block["historical_costs"]
                        if scope == "historical"
                        else block["attempts"][0]["costs"]["training"]["values"]
                    )
                    costs["cpu_seconds"] = bad
                    with self.assertRaises(ACEValidationError):
                        self.assess(block, records)

    def test_noupdate_never_becomes_improvement_from_noisy_positive_score(self):
        block, records = retained_fixture()
        cell = self.assess(block, records)["cells"]["S0-I0"]
        self.assertEqual(
            (cell["registered_runs"], cell["qualified_runs"], cell["unresolved_runs"]),
            (1, 0, 0),
        )
        self.assertEqual(cell["effect_criterion_not_met_runs"], 1)

    def test_unconfirmed_retained_final_remains_unresolved(self):
        for missing in (
            "final", "acceptance", "sealed", "attempt", "terminal", "rollback", "validity_unknown", "all_attempts"
        ):
            with self.subTest(missing=missing):
                block, records = retained_fixture()
                run_id = "lineage-0/S0/parent"
                final = block["registry"]["finals"][run_id]
                if missing == "final":
                    del records[("heldout_final", final["evaluation_reference"])]
                elif missing == "acceptance":
                    del records[("acceptance", block["attempts"][0]["evaluation_reference"])]
                elif missing == "sealed":
                    block["registry"]["sealed"] = False
                elif missing == "attempt":
                    block["attempts"].pop(0)
                elif missing == "terminal":
                    block["attempts"][0]["terminal_status"] = "UNKNOWN"
                elif missing == "rollback":
                    block["attempts"][0]["rolled_back"] = None
                elif missing == "validity_unknown":
                    block["attempts"][0].update(validity="UNKNOWN", evaluation_reference=None)
                else:
                    block["registry"]["entries"] = [
                        row for row in block["registry"]["entries"] if row["run_id"] != run_id
                    ]
                    block["attempts"] = [
                        row for row in block["attempts"] if row["run_id"] != run_id
                    ]
                report = self.assess(block, records)
                observed = report["lineages"]["lineage-0"]["observed_runs"][run_id]
                self.assertEqual(
                    (observed["qualified"], observed["effect_criterion_met"], observed["reason"]),
                    (None, None, "UNRESOLVED_EVIDENCE"),
                )
                cell = report["cells"]["S0-I0"]
                self.assertEqual(
                    (cell["registered_runs"], cell["unresolved_runs"], cell["improvement_probability_bounds"]),
                    (1, 1, [0.0, 1.0]),
                )
                self.assertEqual(report["status"], "HOLD_INCOMPLETE_EVIDENCE")

    def test_retained_final_requires_both_original_evaluation_ports(self):
        block, records = retained_fixture()
        for ports in (
            {},
            {"read_evaluation": lambda kind, ref: records.get((kind, ref))},
            {"verify_evaluation": lambda _kind, record, owner: record["actor_id"] == owner},
        ):
            with self.subTest(ports=list(ports)):
                report = summarize_transfer(
                    [block], minimum_gain=0.1, maximum_retention_loss=0.05, **ports
                )
                cell = report["cells"]["S0-I0"]
                self.assertEqual(
                    (cell["unresolved_runs"], cell["effect_criterion_unknown_runs"]),
                    (1, 1),
                )

    def test_retained_final_rejects_unauthenticated_or_misbound_receipts(self):
        for field, value, code in (
            ("actor_id", "not-the-evaluator", "E_EVALUATION_AUTHENTICATION_REJECTED"),
            ("selection_digest", pin("unrelated-selection"), "E_HOLDOUT_BEFORE_SELECTION_OR_LEAKAGE"),
            ("selection_committed_unix_seconds", 20, "E_HOLDOUT_BEFORE_SELECTION_OR_LEAKAGE"),
        ):
            with self.subTest(field=field):
                block, records = retained_fixture()
                final = block["registry"]["finals"]["lineage-0/S0/parent"]
                records[("heldout_final", final["evaluation_reference"])][field] = value
                with self.assertRaisesRegex(ACEValidationError, code):
                    self.assess(block, records)

    def test_zero_success_has_no_zero_or_finite_cost_per_improvement(self):
        block, records = transfer_fixture()
        for cell in self.assess(block, records, minimum_gain=0.5)["cells"].values():
            self.assertEqual(cell["qualified_runs"], 0)
            self.assertEqual(
                cell["cost_per_effective_improvement"], dict.fromkeys(COST_UNITS)
            )

    def test_missing_outcomes_keep_the_full_denominator_and_unknown_cost(self):
        first, records = transfer_fixture()
        second, other_records = transfer_fixture("lineage-1")
        records.update(other_records)
        second["attempts"] = [
            row
            for row in second["attempts"]
            if row["attempt_id"] != "lineage-1/S0/parent3"
        ]
        cell = self.assess([first, second], records)["cells"]["S0-I0"]
        self.assertEqual(
            (cell["registered_runs"], cell["qualified_runs"], cell["unresolved_runs"]),
            (2, 1, 1),
        )
        self.assertEqual(cell["improvement_probability_bounds"], [0.5, 1.0])
        self.assertEqual(cell["cost_totals"], dict.fromkeys(COST_UNITS))

    def test_retention_failure_and_no_trusted_reader_cannot_qualify(self):
        block, records = transfer_fixture()
        for (kind, _), record in records.items():
            if kind == "heldout_final":
                record["retention_candidate"] = 0.6
        for cell in self.assess(block, records)["cells"].values():
            self.assertEqual(cell["qualified_runs"], 0)
            self.assertEqual(
                (
                    cell["effect_criterion_not_met_runs"],
                    cell["retention_violated_runs"],
                ),
                (1, 1),
            )
        report = summarize_transfer(
            [block], minimum_gain=0.1, maximum_retention_loss=0.05
        )
        for cell in report["cells"].values():
            self.assertEqual((cell["qualified_runs"], cell["unresolved_runs"]), (0, 1))
            self.assertEqual(
                (cell["effect_criterion_unknown_runs"], cell["retention_unknown_runs"]),
                (1, 1),
            )

    def test_failed_or_unknown_selected_attempt_never_qualifies(self):
        for status in ("FAILED", "UNKNOWN"):
            with self.subTest(status=status):
                block, records = transfer_fixture()
                block["attempts"][0]["terminal_status"] = status
                self.assertEqual(
                    self.assess(block, records)["cells"]["S0-I0"]["qualified_runs"], 0
                )

    def test_retention_score_on_other_data_cannot_satisfy_the_constraint(self):
        block, records = transfer_fixture()
        final = block["registry"]["finals"]["lineage-0/S0/parent"]
        records[("heldout_final", final["evaluation_reference"])][
            "retention_data_digest"
        ] = pin("other")
        with self.assertRaises(ACEValidationError):
            self.assess(block, records)

    def test_unknown_history_stays_unknown_separately_from_online_cost(self):
        block, records = transfer_fixture()
        block["historical_costs"]["energy_joules"] = None
        report = self.assess(block, records)
        self.assertIsNone(report["historical_costs"]["totals"]["energy_joules"])
        self.assertEqual(report["cells"]["S0-I0"]["cost_totals"]["energy_joules"], 4.0)

    def test_effect_observation_survives_incomplete_cost_without_qualification(self):
        block, records = transfer_fixture()
        block["attempts"][0]["costs"]["training"]["values"]["energy_joules"] = None
        report = self.assess(block, records)
        run = report["lineages"]["lineage-0"]["observed_runs"]["lineage-0/S0/parent"]
        self.assertEqual(
            (run["effect_criterion_met"], run["retention_violated"], run["qualified"]),
            (True, False, None),
        )
        cell = report["cells"]["S0-I0"]
        self.assertEqual(cell["effect_criterion_probability_bounds"], [1.0, 1.0])
        self.assertEqual(cell["improvement_probability_bounds"], [0.0, 1.0])

    def test_renaming_groups_cannot_hide_cross_lineage_data_leakage(self):
        first, _ = transfer_fixture()
        second, _ = transfer_fixture("lineage-1")
        second["source_groups"] = {
            split: ["renamed-" + split] for split in second["source_groups"]
        }
        for run in second["plan"]["runs"]:
            run["common_start"]["training_data"] = first["plan"]["runs"][0][
                "common_start"
            ]["holdout_data"]
            run["common_start"]["holdout_data"] = pin("different-holdout-data")
        with self.assertRaisesRegex(ACEValidationError, "EVOLVE_DATA_DIGEST_LEAKAGE"):
            self.assess([first, second], {})

    def test_relabelled_lineage_cannot_recount_original_runs(self):
        first, records = transfer_fixture()
        second, other_records = transfer_fixture("lineage-1")
        aliases = {
            new["run_id"]: old["run_id"]
            for old, new in zip(first["plan"]["runs"], second["plan"]["runs"])
        }
        second = remap_identifiers(second, aliases)
        records.update(remap_identifiers(other_records, aliases))
        for changed_owner in (None, "producer_owner", "evaluator_owner"):
            with self.subTest(changed_owner=changed_owner):
                renamed = deepcopy(second)
                if changed_owner is not None:
                    for run in renamed["plan"]["runs"]:
                        run[changed_owner] = "other/" + run[changed_owner]
                with self.assertRaisesRegex(
                    ACEValidationError, "EVOLVE_REUSED_ORIGINAL_RUN"
                ):
                    self.assess([first, renamed], records)

    def test_original_attempt_and_operation_cannot_be_reused_with_new_run_ids(self):
        for key, code in (
            ("attempt_id", "EVOLVE_REUSED_ORIGINAL_ATTEMPT"),
            ("operation_id", "EVOLVE_REUSED_ORIGINAL_OPERATION"),
        ):
            with self.subTest(identity=key):
                first, records = transfer_fixture()
                second, other_records = transfer_fixture("lineage-1")
                aliases = {
                    second["registry"]["entries"][0][key]: first["registry"]["entries"][
                        0
                    ][key]
                }
                second = remap_identifiers(second, aliases)
                records.update(remap_identifiers(other_records, aliases))
                with self.assertRaisesRegex(ACEValidationError, code):
                    self.assess([first, second], records)

    def test_unresolved_registered_operation_remains_an_original_identity(self):
        first, records = transfer_fixture()
        second, other_records = transfer_fixture("lineage-1")
        original = first["registry"]["entries"][2]
        first["attempts"] = [
            row
            for row in first["attempts"]
            if row["attempt_id"] != original["attempt_id"]
        ]
        aliases = {
            second["registry"]["entries"][0]["operation_id"]: original["operation_id"]
        }
        second = remap_identifiers(second, aliases)
        records.update(remap_identifiers(other_records, aliases))
        with self.assertRaisesRegex(
            ACEValidationError, "EVOLVE_REUSED_ORIGINAL_OPERATION"
        ):
            self.assess([first, second], records)

    def test_independent_owner_namespaces_can_reuse_local_identifiers(self):
        first, records = transfer_fixture()
        second, other_records = transfer_fixture("lineage-1")
        aliases = {
            new["run_id"]: old["run_id"]
            for old, new in zip(first["plan"]["runs"], second["plan"]["runs"])
        }
        for old, new in zip(
            first["registry"]["entries"], second["registry"]["entries"]
        ):
            aliases.update(
                {new[key]: old[key] for key in ("attempt_id", "operation_id")}
            )
        for run in second["plan"]["runs"]:
            for key in ("producer_owner", "evaluator_owner"):
                aliases[run[key]] = "independent/" + run[key]
        second = remap_identifiers(second, aliases)
        records.update(remap_identifiers(other_records, aliases))
        report = self.assess([first, second], records)
        self.assertEqual(report["status"], "DESCRIPTIVE_PILOT_COMPLETE")
        self.assertTrue(
            all(cell["qualified_runs"] == 2 for cell in report["cells"].values())
        )
        self.assertFalse(report["independent_lineage_provenance_verified"])
        self.assertFalse(report["scientific_efficacy_qualified"])


if __name__ == "__main__":
    unittest.main()
