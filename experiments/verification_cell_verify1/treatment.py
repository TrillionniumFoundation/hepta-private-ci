"""Host-owned checker treatment receipts; append order is not a trusted clock.

This journal records dispatch intent before host execution. A missing reply stays
pending; recovery never dispatches again. Hashes do not authenticate execution,
gate evidence or terminal truth, and no record grants production authority.
"""

from dataclasses import asdict
import json

from .checker_effects import CheckerSpec, EffectsModel, OUTCOMES
from .contracts import _number, _pairs, _require, _sha, _text, canonical_json, digest
from .prospective import MAX_BODY, MAX_EVENTS, ShadowJournal
from .shadow_risk import DISPOSITIONS, Prediction, evaluate_shadow
from .shadow_schedule import CheckObservation, select_shadow_check


COST_FIELDS = ("wall_seconds", "cpu_seconds", "energy_joules")


class TreatmentJournal:
    """Companion tables in one ShadowJournal, with optional external root pins."""

    def __init__(
        self, shadow, *, expected_registry_sha256=None, expected_ledger_sha256=None
    ):
        _require(type(shadow) is ShadowJournal, "exact ShadowJournal required")
        self.shadow = shadow
        self.registry_sha256 = expected_registry_sha256
        for value in (expected_registry_sha256, expected_ledger_sha256):
            if value is not None:
                _sha(value, "expected root")
        with shadow._transaction() as connection:
            registry, _, _, _, root, _ = self._read(connection)
        _require(
            expected_ledger_sha256 is None or root == expected_ledger_sha256,
            "treatment ledger root changed",
        )
        self.registry_sha256 = digest(registry)

    @classmethod
    def create(cls, shadow, checkers):
        _require(type(shadow) is ShadowJournal, "exact ShadowJournal required")
        _require(
            type(checkers) in (tuple, list)
            and 0 < len(checkers) <= 8
            and all(type(item) is CheckerSpec for item in checkers),
            "one to eight checker specifications required",
        )
        _require(
            len({item.checker_id for item in checkers}) == len(checkers),
            "duplicate checker registration",
        )
        with shadow._transaction() as connection:
            manifest, *_, count = shadow._read(connection)
            _require(count == 0, "freeze treatment registry before shadow events")
            registry = dict(
                schema="hepta.verify.treatment-registry.v1",
                shadow_manifest_sha256=digest(manifest),
                checkers=[asdict(item) for item in checkers],
            )
            connection.execute(
                "CREATE TABLE treatment_frozen (body TEXT NOT NULL, sha TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE treatment_events (seq INTEGER PRIMARY KEY, body TEXT NOT NULL, sha TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO treatment_frozen VALUES (?, ?)",
                (canonical_json(registry), digest(registry)),
            )
        return cls(shadow, expected_registry_sha256=digest(registry))

    def _read(self, connection):
        base = self.shadow._read(connection)
        manifest, predictions, finishes, labels, base_root, base_count = base
        rows = connection.execute(
            "SELECT body, sha FROM treatment_frozen LIMIT 2"
        ).fetchall()
        _require(len(rows) == 1 and len(rows[0][0]) <= MAX_BODY, "invalid registry")
        registry = json.loads(rows[0][0], object_pairs_hook=_pairs)
        _require(
            type(registry) is dict
            and set(registry) == {"schema", "shadow_manifest_sha256", "checkers"}
            and registry["schema"] == "hepta.verify.treatment-registry.v1"
            and registry["shadow_manifest_sha256"] == digest(manifest)
            and digest(registry) == rows[0][1]
            and (self.registry_sha256 is None or rows[0][1] == self.registry_sha256),
            "frozen treatment registry changed",
        )
        specs = registry["checkers"]
        _require(type(specs) is list and 0 < len(specs) <= 8, "invalid registry size")
        checkers = tuple(CheckerSpec(**item) for item in specs)
        _require(
            len({item.checker_id for item in checkers}) == len(checkers),
            "duplicate registry checker",
        )
        raw = [
            (seq, json.loads(body, object_pairs_hook=_pairs), sha)
            for seq, body, sha in connection.execute(
                "SELECT seq, body, sha FROM events ORDER BY seq"
            )
        ]
        roots = [digest(manifest)] + [row[2] for row in raw]
        forecast_sequences = [
            seq for seq, event, _ in raw if event["kind"] == "prediction"
        ]
        finish_sequences = {
            event["value"]["trajectory_id"]: seq
            for seq, event, _ in raw
            if event["kind"] == "finish"
        }
        context = (
            manifest,
            list(zip(forecast_sequences, predictions)),
            finish_sequences,
            roots,
        )
        state = dict(
            choices={},
            starts={},
            completions={},
            dispositions={},
            exposures={},
            shadow_seq=0,
        )
        root = digest(registry)
        events = connection.execute(
            "SELECT seq, body, sha FROM treatment_events ORDER BY seq LIMIT ?",
            (MAX_EVENTS + 1,),
        ).fetchall()
        _require(len(events) <= MAX_EVENTS, "treatment event limit exceeded")
        for expected, (seq, body, sha) in enumerate(events, 1):
            _require(
                seq == expected and len(body) <= MAX_BODY,
                "invalid treatment sequence/size",
            )
            event = json.loads(body, object_pairs_hook=_pairs)
            _require(
                type(event) is dict
                and set(event)
                == {"kind", "value", "previous_sha256", "shadow_seq", "shadow_sha256"}
                and event["previous_sha256"] == root
                and digest(event) == sha,
                "treatment event digest mismatch",
            )
            self._apply(registry, context, event, state)
            root = sha
        return registry, base, context, state, root, len(events)

    @staticmethod
    def _apply(registry, context, event, state):
        manifest, forecasts, finishes, roots = context
        anchor, value, kind = event["shadow_seq"], event["value"], event["kind"]
        _require(
            type(anchor) is int
            and state["shadow_seq"] <= anchor < len(roots)
            and event["shadow_sha256"] == roots[anchor]
            and type(value) is dict,
            "invalid shadow ledger anchor",
        )
        state["shadow_seq"] = anchor
        current = {
            prediction.snapshot.trajectory_id: prediction
            for seq, prediction in forecasts
            if seq <= anchor
        }
        closed = {trajectory for trajectory, seq in finishes.items() if seq <= anchor}
        versions = {
            item["checker_id"]: item["version_sha256"] for item in registry["checkers"]
        }
        if kind == "choice":
            _require(
                set(value) == {"prediction_sha256", "scheduler_sha256", "result"},
                "invalid choice fields",
            )
            prediction = next(
                (
                    row
                    for row in current.values()
                    if digest(asdict(row)) == value["prediction_sha256"]
                ),
                None,
            )
            _require(
                prediction is not None, "choice requires latest recorded prediction"
            )
            snapshot = prediction.snapshot
            trajectory, snapshot_sha = snapshot.trajectory_id, digest(asdict(snapshot))
            _require(
                trajectory not in closed and trajectory not in state["dispositions"],
                "choice after host decision/completion",
            )
            result = value["result"]
            _require(
                type(result) is dict
                and result.get("record_sha256")
                == digest(
                    {
                        key: item
                        for key, item in result.items()
                        if key != "record_sha256"
                    }
                )
                and result["snapshot_sha256"] == snapshot_sha
                and result["risk_model_sha256"] == manifest["risk_model_sha256"]
                and result["checker_model_sha256"] == manifest["checker_model_sha256"]
                and value["scheduler_sha256"] == manifest["scheduler_sha256"],
                "choice model/snapshot binding mismatch",
            )
            history = []
            for prior_operation, start in state["starts"].items():
                if start["snapshot_sha256"] == snapshot_sha:
                    _require(
                        prior_operation in state["completions"],
                        "checker reply still pending",
                    )
                    reply = state["completions"][prior_operation]
                    history.append(
                        asdict(
                            CheckObservation(
                                start["checker_id"],
                                versions[start["checker_id"]],
                                snapshot_sha,
                                reply["outcome"],
                                reply["evidence_sha256"],
                            )
                        )
                    )
            _require(
                result["history_sha256"] == digest(history),
                "checker history differs from actual receipts",
            )
            _require(
                set(result["decision_contract"]["actions"]).issubset(DISPOSITIONS),
                "repair/target-changing action unsupported",
            )
            key = result["record_sha256"]
            _require(key not in state["choices"], "duplicate choice")
            state["choices"][key] = dict(
                **value, trajectory_id=trajectory, snapshot_sha256=snapshot_sha
            )
        elif kind == "start":
            _require(
                set(value) == {"choice_sha256", "operation_id"}, "invalid start fields"
            )
            operation = value["operation_id"]
            _text(operation, "operation_id")
            _require(
                len(operation) <= 256
                and operation.isprintable()
                and operation not in state["starts"],
                "duplicate/invalid operation",
            )
            choice = state["choices"].get(value["choice_sha256"])
            _require(choice is not None, "unrecorded checker choice")
            trajectory, snapshot_sha = (
                choice["trajectory_id"],
                choice["snapshot_sha256"],
            )
            result = choice["result"]
            selection = result["selection"]
            _require(
                trajectory not in closed
                and trajectory not in state["dispositions"]
                and trajectory in current
                and digest(asdict(current[trajectory].snapshot)) == snapshot_sha,
                "start after frontier/host decision/completion",
            )
            _require(
                result["status"] == "check"
                and type(selection) is dict
                and selection["checker_id"] in versions,
                "choice did not select a registered checker",
            )
            checker = selection["checker_id"]
            prior = [
                row
                for row in state["starts"].values()
                if row["snapshot_sha256"] == snapshot_sha
            ]
            _require(
                all(row["checker_id"] != checker for row in prior),
                "checker/snapshot retry forbidden",
            )
            latest = [
                key
                for key, row in state["choices"].items()
                if row["snapshot_sha256"] == snapshot_sha
            ]
            _require(latest[-1] == value["choice_sha256"], "stale checker choice")
            history = []
            for prior_operation, start in state["starts"].items():
                if start["snapshot_sha256"] == snapshot_sha:
                    _require(
                        prior_operation in state["completions"],
                        "checker reply still pending",
                    )
                    reply = state["completions"][prior_operation]
                    history.append(
                        asdict(
                            CheckObservation(
                                start["checker_id"],
                                versions[start["checker_id"]],
                                snapshot_sha,
                                reply["outcome"],
                                reply["evidence_sha256"],
                            )
                        )
                    )
            _require(
                result["history_sha256"] == digest(history),
                "choice checker history is stale",
            )
            state["starts"][operation] = dict(
                **value,
                trajectory_id=trajectory,
                snapshot_sha256=snapshot_sha,
                checker_id=checker,
            )
        elif kind == "complete":
            _require(
                set(value) == {"operation_id", "outcome", "evidence_sha256", "costs"},
                "invalid completion fields",
            )
            operation = value["operation_id"]
            _require(
                operation in state["starts"] and operation not in state["completions"],
                "unstarted or duplicate completion",
            )
            _require(
                type(value["outcome"]) is str and value["outcome"] in OUTCOMES,
                "invalid checker outcome",
            )
            _sha(value["evidence_sha256"], "checker evidence")
            _require(
                type(value["costs"]) is dict
                and set(value["costs"]) == set(COST_FIELDS),
                "invalid physical cost fields",
            )
            for name, cost in value["costs"].items():
                if cost is not None:
                    _number(cost, name, maximum=1e12)
            state["completions"][operation] = value
        elif kind == "disposition":
            _require(
                set(value)
                == {
                    "trajectory_id",
                    "disposition",
                    "hard_checks_complete",
                    "gate_evidence_sha256",
                },
                "invalid disposition fields",
            )
            trajectory = value["trajectory_id"]
            _require(
                trajectory in {row["trajectory_id"] for row in manifest["roster"]}
                and trajectory not in closed
                and trajectory not in state["dispositions"],
                "late/duplicate/unplanned disposition",
            )
            _require(
                type(value["hard_checks_complete"]) is bool
                and value["disposition"] in DISPOSITIONS,
                "invalid host decision",
            )
            _sha(value["gate_evidence_sha256"], "gate evidence")
            if value["disposition"] == "accept":
                _require(
                    value["hard_checks_complete"]
                    and all(
                        operation in state["completions"]
                        for operation, start in state["starts"].items()
                        if start["trajectory_id"] == trajectory
                    ),
                    "acceptance has pending checker or mandatory gate",
                )
            state["dispositions"][trajectory] = value
            operations = {
                key
                for key, row in state["starts"].items()
                if row["trajectory_id"] == trajectory
            }
            completed = operations.intersection(state["completions"])
            pending = operations - completed
            current_sha = (
                digest(asdict(current[trajectory].snapshot))
                if trajectory in current
                else None
            )
            current_completed = {
                key
                for key in completed
                if state["starts"][key]["snapshot_sha256"] == current_sha
            }
            choices = [
                row
                for row in state["choices"].values()
                if row["trajectory_id"] == trajectory
                and row["snapshot_sha256"] == current_sha
            ]
            last_status = choices[-1]["result"]["status"] if choices else None
            if pending:
                status = "pending"
            elif completed:
                status = "checked"
            elif last_status == "defer":
                status = "unchecked"
            elif last_status in ("blocked", "unsupported"):
                status = "abstained"
            else:
                status = "missing"
            state["exposures"][trajectory] = dict(
                status=status,
                completed_operation_ids=sorted(completed),
                pending_operation_ids=sorted(pending),
                completed_current_frontier_count=len(current_completed),
                stale_completed_operation_count=len(completed - current_completed),
            )
        else:
            raise ValueError("unknown treatment event kind")

    def _append(self, kind, value=None, build=None):
        with self.shadow._transaction() as connection:
            registry, base, context, state, root, count = self._read(connection)
            _require(count < MAX_EVENTS, "treatment event limit exceeded")
            if build is not None:
                value = build(registry, base, state)
            event = dict(
                kind=kind,
                value=value,
                previous_sha256=root,
                shadow_seq=base[5],
                shadow_sha256=base[4],
            )
            self._apply(registry, context, event, state)
            body = canonical_json(event)
            _require(len(body) <= MAX_BODY, "treatment body too large")
            connection.execute(
                "INSERT INTO treatment_events VALUES (?, ?, ?)",
                (count + 1, body, digest(event)),
            )
        return value

    def choose(
        self,
        prediction,
        effects,
        observations,
        actions,
        losses,
        remaining_budget,
        *,
        hard_checks_complete,
    ):
        _require(
            type(prediction) is Prediction and type(effects) is EffectsModel,
            "exact prediction and effects model required",
        )

        def build(registry, base, state):
            _require(
                [asdict(item) for item in effects.checkers] == registry["checkers"],
                "checker registry changed",
            )
            result = select_shadow_check(
                prediction,
                effects,
                observations,
                actions,
                losses,
                remaining_budget,
                hard_checks_complete=hard_checks_complete,
            )
            return dict(
                prediction_sha256=digest(asdict(prediction)),
                scheduler_sha256=base[0]["scheduler_sha256"],
                result=result,
            )

        return self._append("choice", build=build)["result"]

    def start(self, choice_sha256, operation_id):
        _sha(choice_sha256, "choice_sha256")
        self._append(
            "start", dict(choice_sha256=choice_sha256, operation_id=operation_id)
        )

    def complete(self, operation_id, outcome, evidence_sha256, costs):
        self._append(
            "complete",
            dict(
                operation_id=operation_id,
                outcome=outcome,
                evidence_sha256=evidence_sha256,
                costs=costs,
            ),
        )

    def record_disposition(
        self, trajectory_id, disposition, *, hard_checks_complete, gate_evidence_sha256
    ):
        self._append(
            "disposition",
            dict(
                trajectory_id=trajectory_id,
                disposition=disposition,
                hard_checks_complete=hard_checks_complete,
                gate_evidence_sha256=gate_evidence_sha256,
            ),
        )

    def report(self, *, authenticate=None):
        with self.shadow._transaction() as connection:
            registry, base, _, state, root, count = self._read(connection)
        manifest, predictions, finishes, labels, base_root, base_count = base
        roster = {row["trajectory_id"] for row in manifest["roster"]}
        _require(
            set(finishes) == roster and set(labels) == roster,
            "incomplete roster; retain explicit missing labels",
        )
        _require(
            all(
                finishes[key] == row["disposition"]
                for key, row in state["dispositions"].items()
            ),
            "treatment and host dispositions differ",
        )
        result = evaluate_shadow(predictions, list(labels.values()))
        for step in manifest["frontiers"]:
            result["by_step"].setdefault(str(step), {})["missing_prediction_count"] = (
                len(roster)
                - sum(row.snapshot.observed_step == step for row in predictions)
            )
        exposures = {
            key: state["exposures"].get(
                key,
                dict(
                    status="missing",
                    completed_operation_ids=[],
                    pending_operation_ids=[],
                    completed_current_frontier_count=0,
                    stale_completed_operation_count=0,
                ),
            )
            for key in sorted(roster)
        }
        check_statuses = ("checked", "unchecked", "abstained", "pending", "missing")
        label_authentication = self.shadow.authentication_report(
            authenticate=authenticate, expected_ledger_sha256=base_root
        )
        with self.shadow._transaction() as connection:
            current = self._read(connection)
            _require(
                current[4] == root and current[1][4] == base_root,
                "treatment ledger changed during authentication",
            )
        result.update(
            manifest=manifest,
            manifest_sha256=digest(manifest),
            ledger_sha256=base_root,
            event_count=base_count,
            registry_sha256=digest(registry),
            treatment_ledger_sha256=root,
            treatment_event_count=count,
            treatments={
                key: {
                    "choices": [
                        row
                        for row in state["choices"].values()
                        if row["trajectory_id"] == key
                    ],
                    "operations": [
                        dict(**row, completion=state["completions"].get(operation))
                        for operation, row in state["starts"].items()
                        if row["trajectory_id"] == key
                    ],
                    "disposition": state["dispositions"].get(key),
                    "check_exposure_at_disposition": exposures[key],
                }
                for key in sorted(roster)
            },
            missing_disposition_count=len(roster - set(state["dispositions"])),
            check_denominators={
                status: sum(row["status"] == status for row in exposures.values())
                for status in check_statuses
            },
            check_denominators_by_source_group={
                group: {
                    status: sum(
                        exposures[row["trajectory_id"]]["status"] == status
                        for row in manifest["roster"]
                        if row["source_group"] == group
                    )
                    for status in check_statuses
                }
                for group in sorted({row["source_group"] for row in manifest["roster"]})
            },
            label_authentication=label_authentication,
            missing_choice_count=len(
                roster - {row["trajectory_id"] for row in state["choices"].values()}
            ),
            pending_operation_ids=[
                key for key in state["starts"] if key not in state["completions"]
            ],
            measured_checker_costs={
                name: {
                    "known_sum": sum(
                        row["costs"][name]
                        for row in state["completions"].values()
                        if row["costs"][name] is not None
                    ),
                    "missing_count": len(state["starts"])
                    - sum(
                        row["costs"][name] is not None
                        for row in state["completions"].values()
                    ),
                }
                for name in COST_FIELDS
            },
            prospective_order_enforced=True,
            wall_clock_prospectiveness_proved=False,
            independent_evaluation_established=False,
            full_physical_cost_complete=False,
            scientific_admission="HOLD",
            production_authority="NONE",
        )
        return result
