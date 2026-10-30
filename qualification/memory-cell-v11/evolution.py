"""Measured structural experiments with executable model adapters.

Actions train shadow experts and cannot mutate the incumbent.  Validation cases
must be distinct from fitting data; held evaluation belongs after selection.
Migration here is an actual local checkpoint round trip, not a network claim.
"""

import copy
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import sqlite3
import statistics
import time
import uuid

from maintenance import artifact_identity


@dataclass
class Expert:
    cell_id: str
    model: object
    host: str = "local"
    checkpoint: str | None = None
    artifact_sha256: str | None = None
    artifact_bytes: int = 0

    @property
    def awake(self):
        return self.model is not None


@dataclass
class Network:
    experts: dict
    routes: dict = field(default_factory=dict)
    training_seconds: float = 0.0
    transfer_bytes: int = 0
    maintenance_seconds: float = 0.0


@dataclass(frozen=True)
class Action:
    kind: str
    sources: tuple
    outputs: tuple = ()
    assignments: dict = field(default_factory=dict)
    target_host: str = "local"
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Budget:
    max_active_experts: int = 8
    max_active_bytes: int = 512 * 1024 * 1024
    max_training_seconds: float = 60.0
    max_transfer_bytes: int = 512 * 1024 * 1024


@dataclass(frozen=True)
class Prices:
    storage_per_byte: float = 0.0
    active_memory_per_byte: float = 0.0
    latency_per_second: float = 0.0
    training_per_second: float = 0.0
    transfer_per_byte: float = 0.0
    maintenance_per_second: float = 0.0
    horizon_queries: int = 1000
    minimum_gain: float = 0.0
    confidence_z: float = 1.645


@dataclass
class Evaluation:
    case_ids: tuple
    rewards: tuple
    hard_errors: int = 0
    retained_rewards: tuple = ()
    ablation_credit: dict = field(default_factory=dict)
    wall_seconds: float = 0.0

    def validate(self):
        if not self.case_ids or len(set(self.case_ids)) != len(self.case_ids) or len(self.case_ids) != len(self.rewards):
            raise ValueError("evaluation requires unique, aligned case IDs")
        if any(not math.isfinite(float(x)) for x in self.rewards + self.retained_rewards):
            raise ValueError("non-finite evaluation reward")


@dataclass
class Candidate:
    action: Action
    network: Network
    report: dict


class EvolutionExecutor:
    """Callbacks use real model fit/predict/save/load implementations.

    train_model(model, records, deadline=<monotonic seconds>, options=dict) must
    check the deadline in its training loop and return a serializable receipt.
    evaluate_network(network, validation)->Evaluation computes actual outcomes.
    model_factory(parent_expert, output_id, action) may change model capacity;
    its default is a deepcopy.  save_model(model,path), load_model(path), and
    model_bytes(model) bind the adapter to a specific implementation.
    """

    def __init__(self, output, *, train_model, evaluate_network, save_model,
                 load_model, model_bytes, model_factory=None, budget=Budget(), prices=Prices()):
        if prices.horizon_queries <= 0:
            raise ValueError("amortization horizon must be positive")
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.train, self.evaluate = train_model, evaluate_network
        self.save, self.load, self.model_bytes = save_model, load_model, model_bytes
        self.factory = model_factory or (lambda parent, cell_id, action: copy.deepcopy(parent.model))
        self.budget, self.prices = budget, prices
        self.ledger = sqlite3.connect(self.output / "evolution.sqlite")
        self.ledger.execute("""CREATE TABLE IF NOT EXISTS decisions(
            id TEXT PRIMARY KEY, action TEXT NOT NULL, admitted INTEGER NOT NULL,
            measured_gain REAL, report TEXT NOT NULL)""")
        self.ledger.commit()

    def resources(self, network):
        active = [e for e in network.experts.values() if e.awake]
        active_bytes = sum(int(self.model_bytes(e.model)) for e in active)
        artifacts, complete, valid = {}, True, True
        for expert in network.experts.values():
            if not expert.checkpoint:
                complete = False
                continue
            path = str(Path(expert.checkpoint).resolve())
            try:
                digest, size = artifact_identity(path)
                artifacts[path] = size
                if expert.artifact_sha256 and expert.artifact_sha256 != digest:
                    valid = False
            except (OSError, ValueError):
                complete, valid = False, False
        return dict(active_experts=len(active), active_bytes=active_bytes,
                    stored_model_bytes=active_bytes + sum(e.artifact_bytes for e in network.experts.values() if not e.awake),
                    checkpoint_disk_bytes=sum(artifacts.values()), storage_accounting_complete=complete,
                    checkpoint_identity_valid=valid,
                    training_seconds=network.training_seconds, transfer_bytes=network.transfer_bytes,
                    maintenance_seconds=network.maintenance_seconds)

    def _evaluate(self, network, validation):
        started = time.perf_counter()
        result = self.evaluate(network, validation)
        result.wall_seconds = time.perf_counter() - started
        result.validate()
        return result

    def _cost(self, resources, evaluation):
        p = self.prices
        return (p.storage_per_byte * resources["checkpoint_disk_bytes"]
                + p.active_memory_per_byte * resources["active_bytes"]
                + p.latency_per_second * evaluation.wall_seconds / len(evaluation.rewards)
                + p.training_per_second * resources["training_seconds"] / p.horizon_queries
                + p.transfer_per_byte * resources["transfer_bytes"] / p.horizon_queries
                + p.maintenance_per_second * resources["maintenance_seconds"] / p.horizon_queries)

    def _budget_rejection(self, action_id, directory, action, incumbent, candidate, reason, receipts, started):
        report = dict(schema="hepta.memory.v11.evolution.v1", action_id=action_id,
                      action=asdict(action), admitted=False, rejection_reasons=[reason],
                      resources=self.resources(candidate), training_receipts=receipts,
                      attempt_training_seconds=candidate.training_seconds - incumbent.training_seconds,
                      structural_wall_seconds=time.perf_counter() - started, validation_wall_seconds=0.0,
                      evaluation=None, comparisons={}, budget=asdict(self.budget), prices=asdict(self.prices))
        self.ledger.execute("INSERT INTO decisions VALUES (?,?,?,?,?)", (action_id, action.kind, 0, None, json.dumps(report, sort_keys=True)))
        self.ledger.commit()
        (directory / "DECISION.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return incumbent, Candidate(action, candidate, report)

    def execute(self, action, incumbent, records, *, validation, controls=None):
        """Execute and evaluate a candidate; return incumbent unless admitted.

        controls maps names to independently trained fixed-expert/capacity
        baselines.  Splits require both controls; the gate cannot silently omit
        them.  Their fit costs must be present in Network.training_seconds.
        """
        action_id = uuid.uuid4().hex
        directory = self.output / action_id
        directory.mkdir()
        controls = dict(controls or {})
        if action.kind not in {"split", "merge", "sleep", "wake", "migrate", "capacity"}:
            raise ValueError("unknown structural action")
        if not action.sources or any(name not in incumbent.experts for name in action.sources):
            raise ValueError("action sources must exist")
        if len(set(action.outputs)) != len(action.outputs) or any(name in incumbent.experts and name not in action.sources for name in action.outputs):
            raise ValueError("output IDs collide")
        candidate = Network({key: copy.copy(expert) for key, expert in incumbent.experts.items()},
                            dict(incumbent.routes), incumbent.training_seconds, incumbent.transfer_bytes,
                            incumbent.maintenance_seconds)
        started, receipts = time.perf_counter(), []
        deadline = started + self.budget.max_training_seconds
        source = incumbent.experts[action.sources[0]]
        if action.kind in {"split", "merge", "capacity"}:
            wanted = 2 if action.kind == "split" else 1
            if len(action.outputs) != wanted or not all(incumbent.experts[s].awake for s in action.sources):
                raise ValueError("invalid output count or sleeping training source")
            if action.kind in {"split", "capacity"} and len(action.sources) != 1:
                raise ValueError("split/capacity require one source")
            if action.kind == "merge" and len(action.sources) < 2:
                raise ValueError("merge requires at least two experts")
            if action.kind == "split" and (set(action.assignments) != {str(r["key"]) for r in records}
                                           or set(action.assignments.values()) != set(action.outputs)):
                raise ValueError("split requires a nonempty disjoint training-key partition")
            for name in action.sources:
                candidate.experts.pop(name)
            for name in action.outputs:
                rows = [r for r in records if action.assignments[str(r["key"])] == name] if action.kind == "split" else list(records)
                model = self.factory(source, name, action)
                if model is source.model:
                    raise ValueError("model factory must isolate the shadow model")
                candidate.experts[name] = Expert(name, model, source.host)
                preliminary = self.resources(candidate)
                if preliminary["active_experts"] > self.budget.max_active_experts or preliminary["active_bytes"] > self.budget.max_active_bytes:
                    return self._budget_rejection(action_id, directory, action, incumbent, candidate, "candidate_allocation_exceeds_model_budget", receipts, started)
                if time.perf_counter() >= deadline:
                    return self._budget_rejection(action_id, directory, action, incumbent, candidate, "candidate_training_budget_exhausted", receipts, started)
                fit_started = time.perf_counter()
                try:
                    receipt = self.train(model, rows, deadline=deadline, options=dict(action.options))
                except TimeoutError:
                    candidate.training_seconds += time.perf_counter() - fit_started
                    return self._budget_rejection(action_id, directory, action, incumbent, candidate, "training_callback_deadline", receipts, started)
                fit_seconds = time.perf_counter() - fit_started
                candidate.training_seconds += fit_seconds
                receipts.append(dict(cell_id=name, records=len(rows), wall_seconds=fit_seconds, fit=receipt))
                checkpoint = directory / name
                self.save(model, checkpoint)
                digest, byte_count = artifact_identity(checkpoint)
                candidate.experts[name].checkpoint = str(checkpoint)
                candidate.experts[name].artifact_sha256 = digest
                candidate.experts[name].artifact_bytes = byte_count
                for row in rows:
                    candidate.routes[str(row["key"])] = name
            for key, name in list(candidate.routes.items()):
                if name in action.sources and name not in action.outputs:
                    candidate.routes.pop(key)
        else:
            if len(action.sources) != 1 or action.outputs:
                raise ValueError("lifecycle action requires one source and no outputs")
            expert = candidate.experts[action.sources[0]]
            if action.kind in {"sleep", "migrate"}:
                if not expert.awake:
                    raise ValueError("sleep/migrate require an awake expert")
                checkpoint = directory / expert.cell_id
                self.save(expert.model, checkpoint)
                digest, byte_count = artifact_identity(checkpoint)
                expert.checkpoint, expert.artifact_sha256, expert.artifact_bytes = str(checkpoint), digest, byte_count
                if action.kind == "sleep":
                    expert.model = None
                else:
                    if byte_count > self.budget.max_transfer_bytes:
                        return self._budget_rejection(action_id, directory, action, incumbent, candidate, "checkpoint_exceeds_transfer_budget", receipts, started)
                    expert.model = self.load(checkpoint)
                    expert.host = action.target_host
                    candidate.transfer_bytes += byte_count
            elif action.kind == "wake":
                if expert.awake or not expert.checkpoint:
                    raise ValueError("wake requires a persisted sleeping expert")
                if artifact_identity(expert.checkpoint)[0] != expert.artifact_sha256:
                    raise ValueError("sleeping checkpoint identity changed")
                expert.model = self.load(expert.checkpoint)
        structural_seconds = time.perf_counter() - started
        evaluated = self._evaluate(candidate, validation)
        references = {"incumbent": incumbent, **controls}
        reference_evaluations = {name: self._evaluate(network, validation) for name, network in references.items()}
        candidate.maintenance_seconds += (structural_seconds - (candidate.training_seconds - incumbent.training_seconds)
                                          + evaluated.wall_seconds + sum(e.wall_seconds for e in reference_evaluations.values()))
        resources = self.resources(candidate)
        comparisons, reasons = {}, []
        if action.kind == "split" and not {"fixed_experts", "capacity"}.issubset(controls):
            reasons.append("required_fixed_expert_and_capacity_controls_missing")
        if evaluated.hard_errors:
            reasons.append("candidate_hard_errors")
        if not resources["checkpoint_identity_valid"]:
            reasons.append("candidate_checkpoint_identity_invalid")
        if self.prices.storage_per_byte and not resources["storage_accounting_complete"]:
            reasons.append("candidate_storage_accounting_incomplete")
        if resources["active_experts"] > self.budget.max_active_experts or resources["active_bytes"] > self.budget.max_active_bytes:
            reasons.append("active_resource_budget_exceeded")
        if candidate.training_seconds - incumbent.training_seconds > self.budget.max_training_seconds:
            reasons.append("training_budget_exceeded")
        if candidate.transfer_bytes - incumbent.transfer_bytes > self.budget.max_transfer_bytes:
            reasons.append("transfer_budget_exceeded")
        for name, reference in references.items():
            baseline = reference_evaluations[name]
            reference_resources = self.resources(reference)
            if not reference_resources["checkpoint_identity_valid"]:
                reasons.append(f"{name}_checkpoint_identity_invalid")
            if self.prices.storage_per_byte and not reference_resources["storage_accounting_complete"]:
                reasons.append(f"{name}_storage_accounting_incomplete")
            if baseline.case_ids != evaluated.case_ids:
                raise ValueError("candidate and baseline cases are not aligned")
            differences = [float(a) - float(b) for a, b in zip(evaluated.rewards, baseline.rewards, strict=True)]
            gain = statistics.mean(differences)
            error = statistics.stdev(differences) / math.sqrt(len(differences)) if len(differences) > 1 else None
            quality_lower = gain - self.prices.confidence_z * error if error is not None else None
            cost_delta = self._cost(resources, evaluated) - self._cost(reference_resources, baseline)
            lower_net = quality_lower - cost_delta if quality_lower is not None else None
            retention_ok = (not baseline.retained_rewards or
                            len(baseline.retained_rewards) == len(evaluated.retained_rewards)
                            and statistics.mean(evaluated.retained_rewards) >= statistics.mean(baseline.retained_rewards))
            comparisons[name] = dict(mean_quality_gain=gain, approximate_quality_lower_bound=quality_lower,
                                     measured_cost_delta=cost_delta, lower_net_gain=lower_net,
                                     retention_ok=retention_ok, baseline_resources=reference_resources,
                                     baseline_evaluation=asdict(baseline))
            if lower_net is None or not lower_net > self.prices.minimum_gain:
                reasons.append(f"no_measured_net_gain_over_{name}")
            if not retention_ok:
                reasons.append(f"retention_regression_against_{name}")
        admitted = not reasons
        report = dict(schema="hepta.memory.v11.evolution.v1", action_id=action_id, action=asdict(action),
                      admitted=admitted, rejection_reasons=reasons, resources=resources,
                      structural_wall_seconds=structural_seconds, training_receipts=receipts,
                      attempt_training_seconds=candidate.training_seconds - incumbent.training_seconds,
                      validation_wall_seconds=evaluated.wall_seconds + sum(e.wall_seconds for e in reference_evaluations.values()),
                      evaluation=asdict(evaluated), comparisons=comparisons,
                      budget=asdict(self.budget), prices=asdict(self.prices),
                      routing_scope="explicit training-key routes; evaluator owns held-query routing",
                      confidence_scope="paired normal approximation, conditional on these validation cases",
                      credit_scope="measured action comparison; cell credit only from supplied ablation outcomes",
                      storage_cost_scope="actual unique persisted expert checkpoints; active weight memory priced separately",
                      exploration_cost_scope="all attempts including rejection are available separately via exploration_resources; excluded from a serving-only benefit claim",
                      migration_scope="local checkpoint serialization and reload; no cross-host transfer claimed")
        finite_gains = [v["lower_net_gain"] for v in comparisons.values()
                        if v["lower_net_gain"] is not None and math.isfinite(v["lower_net_gain"])]
        self.ledger.execute("INSERT INTO decisions VALUES (?,?,?,?,?)", (action_id, action.kind, int(admitted),
                            min(finite_gains) if finite_gains else None, json.dumps(report, sort_keys=True)))
        self.ledger.commit()
        (directory / "DECISION.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return (candidate if admitted else incumbent), Candidate(action, candidate, report)

    def exploration_resources(self):
        """Account for every retained attempt, including rejected shadow models.

        These are actual cumulative exploration resources, not a serving-cost
        estimate.  The report caller must include them in any lifecycle claim.
        Shared external base assets and external baseline directories are outside
        this executor directory and must be accounted for by the experiment.
        """
        reports = [json.loads(row[0]) for row in self.ledger.execute("SELECT report FROM decisions")]
        files = [p for p in self.output.rglob("*") if p.is_file()]
        decisions = [p for p in files if p.name == "DECISION.json"]
        ledgers = [p for p in files if p.name.startswith("evolution.sqlite")]
        other = [p for p in files if p not in decisions and p not in ledgers]
        return dict(schema="hepta.memory.v11.exploration-cost.v1", attempted_actions=len(reports),
                    rejected_actions=sum(not r["admitted"] for r in reports),
                    training_seconds=sum(r.get("attempt_training_seconds", 0.0) for r in reports),
                    structural_wall_seconds=sum(r.get("structural_wall_seconds", 0.0) for r in reports),
                    validation_wall_seconds=sum(r.get("validation_wall_seconds", 0.0) for r in reports),
                    total_action_wall_seconds=sum(r.get("structural_wall_seconds", 0.0) + r.get("validation_wall_seconds", 0.0) for r in reports),
                    retained_shadow_artifact_bytes=sum(p.stat().st_size for p in other),
                    decision_receipt_bytes=sum(p.stat().st_size for p in decisions),
                    sqlite_ledger_bytes=sum(p.stat().st_size for p in ledgers),
                    total_retained_directory_bytes=sum(p.stat().st_size for p in files),
                    external_shared_base_and_control_bytes_included=False,
                    rejected_attempt_costs_included=True)

    def close(self):
        self.ledger.close()
