"""Retained experimental population policy inside the existing SQLite owner.

Host callbacks and components remain trusted. Policy/receipt digests establish
consistency, not source authentication, scientific benefit or native authority.
All writes below run in the caller's existing owner transaction.
"""

from dataclasses import asdict
import json

from .bundle import Bundle, validate_local_update
from .component_types import CellError, ComponentIdentity, _bounded_json
from .population import PopulationPlan


class PopulationPolicy:
    def __init__(self, db, plan):
        self.db = db
        for statement in (
            "CREATE TABLE IF NOT EXISTS population_plan(singleton INTEGER PRIMARY KEY CHECK(singleton=1), digest TEXT NOT NULL, record TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS population_current(cell_id TEXT PRIMARY KEY, identity TEXT NOT NULL, bundle TEXT, epoch INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS population_partitions(partition TEXT PRIMARY KEY, cell_id TEXT NOT NULL, epoch INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS population_consumed(partition TEXT NOT NULL, request TEXT NOT NULL, PRIMARY KEY(partition,request))",
        ):
            db.execute(statement)
        if plan is not None and not isinstance(plan, PopulationPlan):
            raise CellError("population must be a PopulationPlan")
        saved = db.execute("SELECT * FROM population_plan WHERE singleton=1").fetchone()
        if saved:
            retained = PopulationPlan.from_record(json.loads(saved["record"]))
            if retained.digest != saved["digest"] or (plan is not None and plan != retained):
                raise CellError("population differs from the retained owner policy")
            self.plan = retained
        else:
            if any(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in
                   ("population_current", "population_partitions", "population_consumed")):
                raise CellError("retained population rows have lost their original policy")
            if plan is not None:
                if db.execute("SELECT count(*) FROM cells").fetchone()[0]:
                    raise CellError("existing unplanned cells require an explicit migration")
                db.execute("INSERT INTO population_plan VALUES(1,?,?)",
                           (plan.digest, _bounded_json(plan.record())))
            self.plan = plan
        if self.plan is not None:
            missing = db.execute(
                "SELECT 1 FROM cells c LEFT JOIN population_partitions p ON p.partition=c.partition WHERE p.partition IS NULL "
                "UNION ALL SELECT 1 FROM population_partitions p LEFT JOIN cells c ON c.partition=p.partition "
                "LEFT JOIN population_current v ON v.cell_id=p.cell_id WHERE c.partition IS NULL OR v.cell_id IS NULL OR p.epoch>v.epoch "
                "UNION ALL SELECT 1 FROM population_current v LEFT JOIN population_partitions p ON p.cell_id=v.cell_id WHERE p.partition IS NULL LIMIT 1"
            ).fetchone()
            if missing:
                raise CellError("retained population admission rows are incomplete")

    def describe(self, partition, component):
        # Lazy imports avoid the existing component -> lifecycle import cycle.
        from .deterministic import ExactRetriever, NumericAlgorithm, RuleVerifier, ToolCell
        from .semantic_component import SemanticComponent
        from .temporal_component import TemporalComponent

        spec = self.plan.spec(partition)
        bundle = None
        if type(component) is SemanticComponent:
            family, kernel = "shared_semantic", "shared_head"
            if component._cell.cell_id != spec.cell_id:
                raise CellError("semantic component belongs to another logical cell")
            bundle = component.bundle
        elif type(component) is TemporalComponent:
            family, kernel = "stateful_temporal", component.kernel.config.kind
            if component.kernel.cell_id != spec.cell_id or component.episode_id != partition.run_id:
                raise CellError("temporal component belongs to another cell or run")
            bundle = component.bundle
        else:
            kinds = {ExactRetriever: "retrieval", NumericAlgorithm: "numerical",
                     RuleVerifier: "rule_verifier", ToolCell: "tool_wrapper"}
            if type(component) not in kinds:
                raise CellError("component class is not admitted by the population registry")
            family, kernel = "deterministic", kinds[type(component)]
        if (family, kernel) != (spec.family, spec.kernel):
            raise CellError("actual component differs from the frozen family or kernel")
        identity = component.identity
        if bundle is not None and bundle.digest() != identity.bundle_digest:
            raise CellError("actual bundle differs from the component identity")
        return spec, identity, bundle

    def create(self, partition, component, budget, total_work_units):
        if self.plan is None:
            return
        spec, identity, bundle = self.describe(partition, component)
        if budget != spec.budget or total_work_units != spec.total_work_units:
            raise CellError("creation budget differs from the frozen population plan")
        current = self.db.execute("SELECT * FROM population_current WHERE cell_id=?", (spec.cell_id,)).fetchone()
        expected = ComponentIdentity(**json.loads(current["identity"])).digest if current else spec.initial_identity
        if identity.digest != expected:
            raise CellError("new run must load the currently admitted logical-cell version")
        if current is None:
            self.db.execute("INSERT INTO population_current VALUES(?,?,?,0)",
                            (spec.cell_id, _bounded_json(asdict(identity)),
                             _bounded_json(bundle.record()) if bundle is not None else None))
        self.db.execute("INSERT INTO population_partitions VALUES(?,?,?)", (partition.digest, spec.cell_id, current["epoch"] if current else 0))

    def observations(self, cell_id, identity, epoch):
        rows = self.db.execute(
            "SELECT i.partition,i.request,i.payload,i.receipt FROM intents i "
            "JOIN population_partitions p ON p.partition=i.partition "
            "LEFT JOIN population_consumed c ON c.partition=i.partition AND c.request=i.request "
            "WHERE p.cell_id=? AND i.identity=? AND i.status='committed' AND c.request IS NULL",
            (cell_id, _bounded_json(asdict(identity))),
        )
        observed = []
        for row in rows:
            receipt, payload = json.loads(row["receipt"]), json.loads(row["payload"])
            if (receipt["status"] == "committed" and receipt["state_applied"] is True
                    and receipt.get("population", {}).get("logical_epoch") == epoch
                    and isinstance(payload, dict)
                    and (payload.get("operation") == "observe" or set(payload) == {"inputs"})):
                observed.append((row["partition"], row["request"]))
        return observed

    def transition(self, partition, component, current, mode):
        if self.plan is None:
            return
        spec, identity, bundle = self.describe(partition, component)
        if mode not in ("adopt", "rollback"):
            return
        latest = self.db.execute("SELECT * FROM population_current WHERE cell_id=?", (spec.cell_id,)).fetchone()
        active = self.db.execute("SELECT epoch FROM population_partitions WHERE partition=?", (partition.digest,)).fetchone()
        if (latest is None or active is None or active["epoch"] != latest["epoch"]
                or ComponentIdentity(**json.loads(latest["identity"])) != current):
            raise CellError("another run has already changed the logical-cell version")
        if latest["epoch"] >= 2**63 - 1:
            raise CellError("logical-cell epoch exhausted")
        if mode == "adopt":
            if not spec.plastic or bundle is None or latest["bundle"] is None:
                raise CellError("this logical cell is frozen")
            source = Bundle(**json.loads(latest["bundle"]))
            if source.digest() != current.bundle_digest:
                raise CellError("retained source bundle differs from the active identity")
            validate_local_update(spec.family, source, bundle, spec.trainable)
            if (bundle.training_lineage["update_rule"] != spec.update_rule
                    or bundle.training_lineage["evaluation_profile"] != spec.evaluation_profile):
                raise CellError("candidate changed the frozen update or evaluation rule")
            observed = self.observations(spec.cell_id, current, latest["epoch"])
            if len(observed) < spec.min_observations:
                raise CellError("not enough unused committed observations for an update")
            self.db.executemany("INSERT INTO population_consumed VALUES(?,?)", observed)
        self.db.execute("UPDATE population_current SET identity=?,bundle=?,epoch=epoch+1 WHERE cell_id=?",
                        (_bounded_json(asdict(identity)),
                         _bounded_json(bundle.record()) if bundle is not None else None, spec.cell_id))
        self.db.execute("UPDATE population_partitions SET epoch=? WHERE partition=?", (latest["epoch"] + 1, partition.digest))

    def annotate(self, partition, record):
        if self.plan is not None:
            spec = self.plan.spec(partition)
            row = self.db.execute("SELECT epoch FROM population_partitions WHERE partition=?", (partition.digest,)).fetchone()
            if row is None:
                raise CellError("partition has lost its population admission")
            record["population"] = dict(plan_digest=self.plan.digest, lineage=spec.lineage,
                                        cell_id=spec.cell_id, trainable=spec.trainable,
                                        logical_epoch=row["epoch"])

