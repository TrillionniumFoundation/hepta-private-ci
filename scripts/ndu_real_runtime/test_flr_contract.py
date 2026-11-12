"""Independent F/L/R contract fixtures; no runner or real owner qualification."""

from copy import deepcopy
import hashlib
import json
import unittest

from ._causal_checks import ACEValidationError
from .flr_contract import summarize_campaign
from .flr_plan import source_mean, validate_plan


UNITS = ("wall_seconds", "cpu_seconds", "energy_joules", "provider_charges")
STAGES = (
    "preparation",
    "collection",
    "training",
    "search",
    "controller",
    "messages",
    "reencoding",
    "graph_compile",
    "evaluation",
    "migration",
    "recovery",
    "io",
)


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def costs(charge):
    result = {
        stage: {
            "status": "not_applicable",
            "values": {},
            "evidence": "explicit synthetic fixture scope",
        }
        for stage in STAGES
    }
    result["training"] = {
        "status": "measured",
        "values": dict.fromkeys(UNITS, charge),
        "evidence": "synthetic disjoint run total, including failed work",
    }
    return result


class ContractFixture:
    """Build original rows directly, independently of flr_reference initialization."""

    def __init__(self):
        sources = {
            f"{split}{g}": {
                "group": f"source-family-{split}",
                "split": split,
                "digest": digest([split, g]),
            }
            for g in range(2)
            for split in ("A", "B", "C")
        }
        sources.update(
            {
                name: {"group": name, "split": "D", "digest": digest(name)}
                for name in ("D-left", "D-right")
            }
        )
        self.plan = {
            "schema": "hepta.flr.plan.v1",
            "campaign_id": "independent-contract-fixture",
            "source": {"commit": "1" * 40, "tree": "2" * 40},
            "initial_model": digest("initial-model"),
            "initial_learner": digest("initial-learner"),
            "generations": 2,
            "information": digest("shared-information"),
            "budget": {
                "candidate_attempts": 2,
                "learner_trials": 2,
                "b_queries": 2,
                "limits": dict.fromkeys(UNITS, 100.0),
            },
            "minimum_gain": 0.1,
            "sources": sources,
            "schedule": [
                {split: [f"{split}{g}"] for split in ("A", "B", "C")} for g in range(2)
            ],
            "audit_sources": ["D-left", "D-right"],
            "evaluation_owner": "fixture-independent-owner",
            "ordinary_entrypoint": "fixture-existing-ordinary-entry",
        }
        self.plan["information"] = digest(
            {key: self.plan[key] for key in ("sources", "schedule")}
        )
        self.originals, self.sequence = {}, 0
        self.records = {
            "schema": "hepta.flr.run.v1",
            "plan_digest": digest(self.plan),
            "rounds": [],
            "seal": None,
            "audits": dict.fromkeys("FLR"),
            "publication_costs": costs(0.5),
        }
        states = {
            arm: (self.plan["initial_model"], self.plan["initial_learner"])
            for arm in "FLR"
        }
        for generation in range(2):
            for arm in "FLR":
                model, learner = states[arm]
                run = f"original-{generation}-{arm}"
                row = {
                    "run_id": run,
                    "arm": arm,
                    "generation": generation,
                    "information": self.plan["information"],
                    "model_before": model,
                    "learner_before": learner,
                    "learner_search": [],
                    "attempts": [],
                    "decision": {
                        "kind": "FROZEN_CONTROL",
                        "selected_attempt": None,
                        "model_after": model,
                        "learner_after": learner,
                        "evidence_ref": None,
                    },
                    "use_ref": None,
                    "costs": costs(1.0),
                }
                if arm == "R":
                    row["learner_search"].append(
                        {
                            "trial_id": run + "/learner-trial",
                            "operation_id": run + "/learner-operation",
                            "training_sources": self.plan["schedule"][generation]["A"],
                            "training_model": model,
                            "training_learner": learner,
                            "status": "SUCCEEDED",
                            "result_model": digest([run, "search-result"]),
                            "utility": 0.7,
                        }
                    )
                if arm != "F":
                    attempt = {
                        "attempt_id": run + "/attempt",
                        "operation_id": run + "/operation",
                        "candidate_model": digest([run, "model"]),
                        "candidate_learner": learner
                        if arm == "L"
                        else digest([run, "learner"]),
                        "training_sources": self.plan["schedule"][generation]["A"],
                        "training_model": model,
                        "training_learner": learner,
                        "status": "SUCCEEDED",
                        "b_queries": 1,
                        "evaluation_ref": None,
                    }
                    row["attempts"].append(attempt)
                    no_update = arm == "L" and generation == 0
                    attempt["evaluation_ref"] = self.emit(
                        "B",
                        run,
                        source_ids=self.plan["schedule"][generation]["B"],
                        attempt_id=attempt["attempt_id"],
                        operation_id=attempt["operation_id"],
                        model=attempt["candidate_model"],
                        learner=attempt["candidate_learner"],
                        baseline_model=model,
                        utility=0.55 if no_update else 0.8,
                        baseline_utility=0.5,
                    )
                    row["decision"]["kind"] = "NO_UPDATE" if no_update else "ADOPT"
                    if not no_update:
                        row["decision"].update(
                            selected_attempt=attempt["attempt_id"],
                            model_after=attempt["candidate_model"],
                            learner_after=attempt["candidate_learner"],
                        )
                decision = row["decision"]
                decision["evidence_ref"] = self.emit(
                    "selection",
                    run,
                    attempts_digest=digest(row["attempts"]),
                    learner_search_digest=digest(row["learner_search"]),
                    decision=decision["kind"],
                    selected_attempt=decision["selected_attempt"],
                    model=decision["model_after"],
                    learner=decision["learner_after"],
                )
                row["use_ref"] = self.emit(
                    "C",
                    run,
                    source_ids=self.plan["schedule"][generation]["C"],
                    model=decision["model_after"],
                    learner=decision["learner_after"],
                    entrypoint=self.plan["ordinary_entrypoint"],
                    scores={f"C{generation}": {"F": 0.2, "L": 0.6, "R": 0.9}[arm]},
                )
                self.records["rounds"].append(row)
                states[arm] = decision["model_after"], decision["learner_after"]
        self.sequence += 5
        self.records["seal"] = {
            "rounds_digest": digest(self.records["rounds"]),
            "sequence": self.sequence,
        }
        for arm in "FLR":
            self.records["audits"][arm] = self.emit(
                "D",
                self.plan["campaign_id"] + "/" + arm,
                source_ids=self.plan["audit_sources"],
                model=states[arm][0],
                learner=states[arm][1],
                scores={"D-left": 0.2, "D-right": 0.8},
            )

    def emit(self, kind, run_id, **fields):
        self.sequence += 10
        value = {
            "kind": kind,
            "run_id": run_id,
            "actor_id": self.plan["evaluation_owner"],
            "plan_digest": self.records["plan_digest"],
            "sequence": self.sequence,
            **fields,
        }
        reference = digest(value)
        self.originals[(kind, reference)] = value
        return reference

    def row(self, arm, generation=0):
        return next(
            row
            for row in self.records["rounds"]
            if row["arm"] == arm and row["generation"] == generation
        )

    def reseal(self):
        if self.records["seal"] is not None:
            self.records["seal"]["rounds_digest"] = digest(self.records["rounds"])

    def rewrite(self, kind, pointer, key, **fields):
        value = deepcopy(self.originals[(kind, pointer[key])])
        value.update(fields)
        pointer[key] = digest(value)
        self.originals[(kind, pointer[key])] = value
        self.reseal()

    def bind_plan(self, *, refresh_evidence=True):
        self.plan["information"] = digest(
            {key: self.plan[key] for key in ("sources", "schedule")}
        )
        self.records["plan_digest"] = digest(self.plan)
        pointers = []
        for row in self.records["rounds"]:
            row["information"] = self.plan["information"]
            pointers.extend(
                ("B", item, "evaluation_ref")
                for item in row["attempts"]
                if item["evaluation_ref"] is not None
            )
            pointers.extend(
                (("selection", row["decision"], "evidence_ref"), ("C", row, "use_ref"))
            )
        pointers.extend(("D", self.records["audits"], arm) for arm in "FLR")
        if refresh_evidence:
            for kind, pointer, key in pointers:
                if pointer[key] is not None:
                    self.rewrite(
                        kind, pointer, key, plan_digest=self.records["plan_digest"]
                    )
            for row in self.records["rounds"]:
                if row["decision"]["evidence_ref"] is not None:
                    self.rewrite(
                        "selection",
                        row["decision"],
                        "evidence_ref",
                        attempts_digest=digest(row["attempts"]),
                        learner_search_digest=digest(row["learner_search"]),
                    )
        self.reseal()

    def assess(self, **ports):
        callbacks = {
            "read_evidence": lambda kind, ref: self.originals.get((kind, ref)),
            "verify_evidence": lambda kind, value, owner: value["actor_id"] == owner,
        }
        return summarize_campaign(self.plan, self.records, **(callbacks | ports))


class FlrContractChecks(unittest.TestCase):
    def test_complete_original_fixture_preserves_frozen_arms_and_no_authority(self):
        report = ContractFixture().assess()
        self.assertEqual(
            (
                report["status"],
                report["registered_rounds"],
                report["complete_rounds"],
                report["unresolved_rounds"],
            ),
            ("DESCRIPTIVE_PROTOCOL_COMPLETE", 6, 6, 0),
        )
        self.assertEqual(
            report["decisions"],
            {
                "F": ["FROZEN_CONTROL"] * 2,
                "L": ["NO_UPDATE", "ADOPT"],
                "R": ["ADOPT"] * 2,
            },
        )
        self.assertEqual(report["b_queries"], {"F": 0, "L": 2, "R": 2})
        self.assertEqual(report["learner_trials"], {"F": 0, "L": 0, "R": 2})
        self.assertEqual(report["declared_audit_source_groups"], 2)
        for key in (
            "authority_granted",
            "scientific_efficacy_qualified",
            "recursive_self_improvement_qualified",
            "production_adoption_qualified",
            "independent_external_audit_verified",
        ):
            self.assertIs(report[key], False)

    def test_f_cannot_train_or_change_state_and_l_cannot_change_learner(self):
        for mutation in (
            "F-training",
            "F-model",
            "F-learner",
            "F-search",
            "L-search",
            "L-candidate",
            "L-selected",
        ):
            with self.subTest(mutation=mutation):
                fixture = ContractFixture()
                row = fixture.row(mutation[0])
                if mutation == "F-training":
                    row["attempts"] = deepcopy(fixture.row("L")["attempts"])
                elif mutation in ("F-search", "L-search"):
                    row["learner_search"] = deepcopy(fixture.row("R")["learner_search"])
                elif mutation == "L-candidate":
                    row["attempts"][0]["candidate_learner"] = digest("unfrozen-rule")
                else:
                    row["decision"][
                        "model_after" if mutation == "F-model" else "learner_after"
                    ] = digest("drift")
                fixture.reseal()
                with self.assertRaises(ACEValidationError):
                    fixture.assess()

    def test_each_attempt_binds_training_a_and_the_actual_previous_model_and_learner(
        self,
    ):
        for operation in ("attempts", "learner_search"):
            for field, value in (
                ("training_sources", ["B0"]),
                ("training_sources", ["C0"]),
                ("training_model", digest("other-model")),
                ("training_learner", digest("other-learner")),
            ):
                with self.subTest(operation=operation, field=field, value=value):
                    fixture = ContractFixture()
                    fixture.row("R")[operation][0][field] = value
                    fixture.reseal()
                    with self.assertRaisesRegex(
                        ACEValidationError, "FLR_TRAINING_BINDING"
                    ):
                        fixture.assess()

    def test_b_budget_is_cumulative_and_one_query_is_required_per_successful_attempt(
        self,
    ):
        fixture = ContractFixture()
        fixture.plan["budget"]["b_queries"] = 1
        fixture.bind_plan()
        with self.assertRaisesRegex(ACEValidationError, "FLR_B_QUERY_BUDGET"):
            fixture.assess()
        for count in (0, 2, -1, True):
            with self.subTest(count=count):
                fixture = ContractFixture()
                fixture.row("L")["attempts"][0]["b_queries"] = count
                fixture.reseal()
                with self.assertRaises(ACEValidationError):
                    fixture.assess()

    def test_failed_and_unknown_attempts_keep_queries_and_all_incurred_costs(self):
        for status in ("FAILED", "CANCELLED", "UNKNOWN"):
            with self.subTest(status=status):
                fixture = ContractFixture()
                row = fixture.row("L")
                failure = deepcopy(row["attempts"][0])
                failure.update(
                    attempt_id="additional-attempt",
                    operation_id="additional-operation",
                    status=status,
                    evaluation_ref=None,
                    b_queries=1,
                )
                row["attempts"].append(failure)
                row["costs"]["training"]["values"] = dict.fromkeys(UNITS, 8.0)
                fixture.plan["budget"]["b_queries"] = 3
                fixture.bind_plan()
                report = fixture.assess()
                reported = report["costs"]["standalone_by_arm"]["L"]
                self.assertEqual(report["b_queries"]["L"], 3)
                self.assertEqual(
                    reported["known_lower_bounds"], dict.fromkeys(UNITS, 9.5)
                )
                self.assertEqual(
                    reported["totals"],
                    dict.fromkeys(UNITS, None if status == "UNKNOWN" else 9.5),
                )
                fixture.plan["budget"]["limits"] = dict.fromkeys(UNITS, 9.0)
                fixture.bind_plan()
                with self.assertRaisesRegex(
                    ACEValidationError, "FLR_TOTAL_BUDGET_EXCEEDED"
                ):
                    fixture.assess()

    def test_learner_change_requires_successful_search_and_trials_have_a_budget(self):
        for status in (None, "FAILED", "CANCELLED"):
            with self.subTest(status=status):
                fixture = ContractFixture()
                row = fixture.row("R")
                if status is None:
                    row["learner_search"].clear()
                else:
                    row["learner_search"][0].update(
                        status=status, result_model=None, utility=None
                    )
                fixture.reseal()
                with self.assertRaisesRegex(
                    ACEValidationError, "FLR_LEARNER_CHANGED_WITHOUT_SEARCH"
                ):
                    fixture.assess()
        for field, value in (
            ("result_model", None),
            ("utility", None),
            ("utility", -0.1),
            ("utility", 1.1),
            ("utility", True),
        ):
            with self.subTest(field=field, value=value):
                fixture = ContractFixture()
                fixture.row("R")["learner_search"][0][field] = value
                fixture.reseal()
                with self.assertRaisesRegex(
                    ACEValidationError, "FLR_LEARNER_TRIAL_RESULT"
                ):
                    fixture.assess()
        fixture = ContractFixture()
        row = fixture.row("R")
        failure = deepcopy(row["learner_search"][0])
        failure.update(
            trial_id="failed-meta-trial",
            operation_id="failed-meta-operation",
            status="FAILED",
            result_model=None,
            utility=None,
        )
        row["learner_search"].append(failure)
        fixture.plan["budget"]["learner_trials"] = 1
        fixture.bind_plan()
        with self.assertRaisesRegex(ACEValidationError, "FLR_LEARNER_SEARCH_BUDGET"):
            fixture.assess()

    def test_failed_and_unknown_learner_trials_keep_costs_and_bind_selection(self):
        for status in ("FAILED", "CANCELLED", "UNKNOWN"):
            with self.subTest(status=status):
                fixture = ContractFixture()
                row = fixture.row("R")
                failure = deepcopy(row["learner_search"][0])
                failure.update(
                    trial_id="additional-meta-trial",
                    operation_id="additional-meta-operation",
                    status=status,
                    result_model=None,
                    utility=None,
                )
                row["learner_search"].append(failure)
                row["costs"]["search"] = {
                    "status": "measured",
                    "values": dict.fromkeys(UNITS, 7.0),
                    "evidence": "synthetic incurred cost of failed or unknown meta search",
                }
                fixture.rewrite(
                    "selection",
                    row["decision"],
                    "evidence_ref",
                    learner_search_digest=digest(row["learner_search"]),
                )
                report = fixture.assess()
                self.assertEqual(report["learner_trials"], {"F": 0, "L": 0, "R": 3})
                reported = report["costs"]["standalone_by_arm"]["R"]
                self.assertEqual(
                    reported["known_lower_bounds"], dict.fromkeys(UNITS, 9.5)
                )
                self.assertEqual(
                    reported["totals"],
                    dict.fromkeys(UNITS, None if status == "UNKNOWN" else 9.5),
                )
                self.assertEqual(
                    report["decisions"]["R"],
                    ["UNAVAILABLE"] * 2 if status == "UNKNOWN" else ["ADOPT"] * 2,
                )
                if status == "UNKNOWN":
                    self.assertTrue(
                        all(g["R"] is None for g in report["future_generations"])
                    )
                    self.assertEqual(report["status"], "HOLD_INCOMPLETE_EVIDENCE")
                row["learner_search"].pop()
                fixture.reseal()
                with self.assertRaisesRegex(ACEValidationError, "FLR_EVIDENCE_BINDING"):
                    fixture.assess()

    def test_b_receipt_cannot_migrate_to_an_identical_candidate_attempt(self):
        for field in ("attempt_id", "operation_id"):
            with self.subTest(field=field):
                fixture = ContractFixture()
                row = fixture.row("L")
                row["attempts"][0][field] = "different-original-operation"
                fixture.rewrite(
                    "selection",
                    row["decision"],
                    "evidence_ref",
                    attempts_digest=digest(row["attempts"]),
                )
                with self.assertRaisesRegex(ACEValidationError, "FLR_EVIDENCE_BINDING"):
                    fixture.assess()

    def test_unconfirmed_no_update_and_missing_ports_remain_unavailable(self):
        for missing in ("B", "selection", "C", "unknown-attempt"):
            with self.subTest(missing=missing):
                fixture = ContractFixture()
                row = fixture.row("L")
                if missing == "B":
                    del fixture.originals[("B", row["attempts"][0]["evaluation_ref"])]
                elif missing == "selection":
                    del fixture.originals[
                        ("selection", row["decision"]["evidence_ref"])
                    ]
                elif missing == "C":
                    del fixture.originals[("C", row["use_ref"])]
                else:
                    row["attempts"][0].update(status="UNKNOWN", evaluation_ref=None)
                    fixture.rewrite(
                        "selection",
                        row["decision"],
                        "evidence_ref",
                        attempts_digest=digest(row["attempts"]),
                    )
                report = fixture.assess()
                self.assertEqual(report["decisions"]["L"][0], "UNAVAILABLE")
                self.assertIsNone(report["future_generations"][0]["L"])
                self.assertGreaterEqual(report["unresolved_rounds"], 1)
                self.assertEqual(report["status"], "HOLD_INCOMPLETE_EVIDENCE")
        fixture = ContractFixture()
        report = summarize_campaign(fixture.plan, fixture.records)
        self.assertEqual(
            (report["complete_rounds"], report["unresolved_rounds"]), (0, 6)
        )

    def test_missing_original_predecessor_cannot_qualify_a_later_generation(self):
        for kind in ("B", "selection", "C"):
            with self.subTest(kind=kind):
                fixture = ContractFixture()
                row = fixture.row("R")
                reference = {
                    "B": row["attempts"][0]["evaluation_ref"],
                    "selection": row["decision"]["evidence_ref"],
                    "C": row["use_ref"],
                }[kind]
                del fixture.originals[(kind, reference)]
                report = fixture.assess()
                self.assertEqual(
                    report["decisions"]["R"], ["UNAVAILABLE", "UNAVAILABLE"]
                )
                self.assertTrue(
                    all(g["R"] is None for g in report["future_generations"])
                )

    def test_broken_model_or_learner_inheritance_is_rejected(self):
        for field in ("model_before", "learner_before"):
            with self.subTest(field=field):
                fixture = ContractFixture()
                fixture.row("R", 1)[field] = digest("unrelated-predecessor")
                fixture.reseal()
                with self.assertRaisesRegex(
                    ACEValidationError, "FLR_BROKEN_INHERITANCE"
                ):
                    fixture.assess()

    def test_source_groups_and_actual_bytes_cannot_cross_splits_or_repeat_future_samples(
        self,
    ):
        for mutation in ("group", "bytes", "C-repeat", "D-repeat", "wrong-split"):
            with self.subTest(mutation=mutation):
                fixture = ContractFixture()
                sources = fixture.plan["sources"]
                if mutation == "group":
                    sources["B0"]["group"] = sources["A0"]["group"]
                elif mutation == "bytes":
                    sources["B0"]["digest"] = sources["A0"]["digest"]
                elif mutation == "C-repeat":
                    sources["C1"]["digest"] = sources["C0"]["digest"]
                elif mutation == "D-repeat":
                    sources["D-right"] = deepcopy(sources["D-left"])
                else:
                    fixture.plan["schedule"][0]["A"] = ["B0"]
                with self.assertRaises(ACEValidationError):
                    validate_plan(fixture.plan)

    def test_seed_or_template_variants_do_not_add_independent_source_groups(self):
        fixture = ContractFixture()
        fixture.plan["sources"]["D-left-seed-2"] = {
            "group": "D-left",
            "split": "D",
            "digest": digest("same-source-new-variant"),
        }
        fixture.plan["audit_sources"].append("D-left-seed-2")
        fixture.bind_plan()
        for arm in "FLR":
            fixture.rewrite(
                "D",
                fixture.records["audits"],
                arm,
                source_ids=fixture.plan["audit_sources"],
                scores={"D-left": 0.2, "D-right": 0.8, "D-left-seed-2": 0.2},
            )
        report = fixture.assess()
        self.assertEqual(report["declared_audit_source_groups"], 2)
        self.assertEqual(report["final_audit"], dict.fromkeys("FLR", 0.5))
        self.assertEqual(report["independent_real_sources_verified"], 0)
        self.assertEqual(
            source_mean(
                {"D-left": 0.2, "D-right": 0.8, "D-left-seed-2": 0.2},
                fixture.plan["sources"],
            ),
            0.5,
        )

    def test_original_receipts_cannot_be_reused_after_source_or_plan_substitution(self):
        for mutation in ("source-bytes", "source-commit", "budget"):
            with self.subTest(mutation=mutation):
                fixture = ContractFixture()
                if mutation == "source-bytes":
                    fixture.plan["sources"]["B0"]["digest"] = digest(
                        "substituted-real-bytes"
                    )
                elif mutation == "source-commit":
                    fixture.plan["source"]["commit"] = "3" * 40
                else:
                    fixture.plan["budget"]["b_queries"] = 3
                fixture.bind_plan(refresh_evidence=False)
                with self.assertRaisesRegex(ACEValidationError, "FLR_EVIDENCE_BINDING"):
                    fixture.assess()

    def test_c_requires_selection_and_d_requires_the_unchanged_search_seal(self):
        fixture = ContractFixture()
        row = fixture.row("L")
        selection = fixture.originals[("selection", row["decision"]["evidence_ref"])]
        fixture.rewrite("C", row, "use_ref", sequence=selection["sequence"] - 1)
        with self.assertRaisesRegex(ACEValidationError, "FLR_USE_BEFORE_SELECTION"):
            fixture.assess()
        fixture = ContractFixture()
        fixture.records["seal"] = None
        with self.assertRaisesRegex(ACEValidationError, "FLR_D_BEFORE_SEAL"):
            fixture.assess()
        fixture = ContractFixture()
        fixture.rewrite(
            "D",
            fixture.records["audits"],
            "F",
            sequence=fixture.records["seal"]["sequence"] - 1,
        )
        with self.assertRaisesRegex(ACEValidationError, "FLR_D_BEFORE_SEAL"):
            fixture.assess()
        fixture = ContractFixture()
        fixture.records["seal"]["rounds_digest"] = digest("different-search")
        with self.assertRaisesRegex(ACEValidationError, "FLR_SEARCH_NOT_SEALED"):
            fixture.assess()

    def test_authentication_requires_exact_true_and_retained_bytes(self):
        for answer in (False, None, 1, "yes"):
            with self.subTest(answer=answer):
                fixture = ContractFixture()
                with self.assertRaisesRegex(
                    ACEValidationError, "FLR_EVIDENCE_AUTHENTICATION"
                ):
                    fixture.assess(verify_evidence=lambda *_: answer)
        fixture = ContractFixture()
        reference = fixture.row("F")["use_ref"]
        fixture.originals[("C", reference)]["scores"]["C0"] = 0.99
        with self.assertRaisesRegex(ACEValidationError, "FLR_EVIDENCE_AUTHENTICATION"):
            fixture.assess()

    def test_authenticated_but_wrong_source_model_or_entrypoint_is_rejected(self):
        for kind, field, value in (
            ("B", "source_ids", ["C0"]),
            ("B", "baseline_model", digest("unrelated-baseline")),
            ("C", "model", digest("stale-model")),
            ("C", "entrypoint", "different-entry"),
            ("D", "source_ids", ["C1"]),
        ):
            with self.subTest(kind=kind, field=field):
                fixture = ContractFixture()
                row = fixture.row("L")
                pointer, key = (
                    (row["attempts"][0], "evaluation_ref")
                    if kind == "B"
                    else (
                        (row, "use_ref")
                        if kind == "C"
                        else (fixture.records["audits"], "F")
                    )
                )
                fixture.rewrite(kind, pointer, key, **{field: value})
                with self.assertRaisesRegex(ACEValidationError, "FLR_EVIDENCE_BINDING"):
                    fixture.assess()

    def test_missing_round_keeps_planned_denominators_and_unknown_costs(self):
        fixture = ContractFixture()
        fixture.records["rounds"].pop()
        fixture.records.update(seal=None, audits=dict.fromkeys("FLR"))
        report = fixture.assess()
        self.assertEqual(
            (
                report["registered_rounds"],
                report["complete_rounds"],
                report["unresolved_rounds"],
            ),
            (6, 5, 1),
        )
        self.assertEqual(len(report["future_generations"]), 2)
        self.assertIsNone(report["future_generations"][1]["R_minus_L"])
        self.assertEqual(
            report["costs"]["standalone_by_arm"]["R"]["totals"], dict.fromkeys(UNITS)
        )
        self.assertEqual(report["status"], "HOLD_INCOMPLETE_EVIDENCE")

    def test_duplicate_run_attempt_and_operation_identities_are_rejected(self):
        for field in (
            "run_id",
            "attempt_id",
            "operation_id",
            "trial_id",
            "trial-operation",
            "trial-as-candidate",
            "trial-operation-as-candidate",
        ):
            with self.subTest(field=field):
                fixture = ContractFixture()
                left, right = fixture.row("L"), fixture.row("R")
                if field == "run_id":
                    right[field] = left[field]
                elif field == "trial_id":
                    right["learner_search"][0]["trial_id"] = left["attempts"][0][
                        "attempt_id"
                    ]
                elif field == "trial-operation":
                    right["learner_search"][0]["operation_id"] = left["attempts"][0][
                        "operation_id"
                    ]
                elif field == "trial-as-candidate":
                    right["attempts"][0]["attempt_id"] = right["learner_search"][0][
                        "trial_id"
                    ]
                elif field == "trial-operation-as-candidate":
                    right["attempts"][0]["operation_id"] = right["learner_search"][0][
                        "operation_id"
                    ]
                else:
                    right["attempts"][0][field] = left["attempts"][0][field]
                fixture.reseal()
                with self.assertRaisesRegex(ACEValidationError, "FLR_REUSED_EXECUTION"):
                    fixture.assess()


if __name__ == "__main__":
    unittest.main()
