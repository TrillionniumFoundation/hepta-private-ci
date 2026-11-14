"""Atomic population visibility over independently admitted real cell versions.

Prepared owner databases/checkpoints are private to a transaction until its
single SQLite topology commit. Crashed preparation is resumable; aborted bytes
remain evidence. A rollback creates a new topology and new owner generations.
External frontier changes always fence reads, including in-flight responses.
"""

import json
from pathlib import Path

from evolution_common import (
    advance_frontier,
    canonical,
    checked_frontier,
    digest,
    identifier,
    require,
    roots,
    transaction,
)
from topology_contract import MAX_HISTORY, empty_policy, make_plan


class TopologyStore:
    """Local one-writer topology authority; it does not authenticate its provider."""

    def __init__(self, root, scope, provider, owners):
        self.root, self.scope, self.provider, self.owners = (
            Path(root).absolute(),
            identifier(scope),
            provider,
            owners,
        )
        require(
            not self.root.is_symlink() and callable(provider),
            "real topology root and source authority required",
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "topology.sqlite"
        require(not self.database.is_symlink(), "topology database symlink")
        with transaction(self.database) as db:
            for statement in (
                "CREATE TABLE IF NOT EXISTS metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1),value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS topologies (generation INTEGER PRIMARY KEY,value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS versions (cell TEXT NOT NULL,version INTEGER NOT NULL,value TEXT NOT NULL,PRIMARY KEY(cell,version))",
                "CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY,value TEXT NOT NULL,state TEXT NOT NULL,staged TEXT,error TEXT,receipt TEXT)",
            ):
                db.execute(statement)
            row = db.execute("SELECT value FROM metadata WHERE singleton=1").fetchone()
            if row is None:
                meta = dict(scope=self.scope, generation=0, frontier=None)
                initial = dict(
                    generation=0,
                    operation_id=None,
                    cells={},
                    edges=[],
                    edge_policy=empty_policy(),
                    production_accepted=False,
                )
                db.execute(
                    "INSERT INTO metadata VALUES(1,?)", (canonical(meta).decode(),)
                )
                db.execute(
                    "INSERT INTO topologies VALUES(0,?)", (canonical(initial).decode(),)
                )
            else:
                require(
                    json.loads(row[0])["scope"] == self.scope, "topology scope mismatch"
                )

    def _metadata(self, db):
        return json.loads(
            db.execute("SELECT value FROM metadata WHERE singleton=1").fetchone()[0]
        )

    def _snapshot(self, db, generation=None):
        generation = (
            self._metadata(db)["generation"] if generation is None else generation
        )
        row = db.execute(
            "SELECT value FROM topologies WHERE generation=?", (generation,)
        ).fetchone()
        require(row is not None, "unknown committed topology")
        return json.loads(row[0])

    def snapshot(self, generation=None):
        with transaction(self.database) as db:
            return self._snapshot(db, generation)

    def observe(self):
        current = checked_frontier(self.provider(), self.scope)
        with transaction(self.database) as db:
            meta = self._metadata(db)
            advance_frontier(meta["frontier"], current)
            meta["frontier"] = current
            db.execute(
                "UPDATE metadata SET value=? WHERE singleton=1",
                (canonical(meta).decode(),),
            )
        return current

    def _plan_row(self, db, op_id):
        row = db.execute(
            "SELECT * FROM operations WHERE id=?", (identifier(op_id),)
        ).fetchone()
        require(row is not None, "unknown topology operation")
        return row

    def prepare(
        self,
        op_id,
        kind,
        *,
        expected_generation,
        inputs,
        candidates,
        edges=None,
        edge_policy=None,
        target_generation=None,
    ):
        frontier = self.observe()
        edges, policy = (
            ([] if edges is None else edges),
            (empty_policy() if edge_policy is None else edge_policy),
        )
        with transaction(self.database) as db:
            current = self._snapshot(db)
            require(
                current["generation"] == expected_generation < MAX_HISTORY,
                "topology generation CAS or history bound",
            )
            require(
                not db.execute(
                    "SELECT id FROM operations WHERE state IN ('preparing','ready') AND id<>?",
                    (op_id,),
                ).fetchone(),
                "another topology preparation is active",
            )
            latest = {}
            for row in db.execute("SELECT cell,value FROM versions ORDER BY version"):
                latest[row["cell"]] = json.loads(row["value"])
            if kind == "rollback":
                old = self._snapshot(db, target_generation)
                expected = [
                    dict(
                        cell_id=c["cell_id"],
                        role=c["role"],
                        directory=c["directory"],
                        manifest_sha256=c["manifest_sha256"],
                        support_roots=c["support_roots"],
                        derivation="reuse",
                    )
                    for c in old["cells"].values()
                ]
                require(
                    candidates == expected
                    and edges == old["edges"]
                    and policy == old["edge_policy"],
                    "rollback must use exact retained target",
                )
            plan = make_plan(
                op_id,
                kind,
                current,
                inputs,
                candidates,
                latest,
                frontier,
                edges,
                policy,
                target_generation,
            )
            old = db.execute(
                "SELECT value,state FROM operations WHERE id=?", (op_id,)
            ).fetchone()
            if old:
                require(
                    json.loads(old["value"]) == plan and old["state"] != "aborted",
                    "operation identity reused or aborted",
                )
            else:
                db.execute(
                    "INSERT INTO operations VALUES(?,?,'preparing',NULL,NULL,NULL)",
                    (op_id, canonical(plan).decode()),
                )
        return self.resume(op_id)

    def resume(self, op_id):
        frontier = self.observe()
        with transaction(self.database) as db:
            row = self._plan_row(db, op_id)
            if row["state"] == "committed":
                return json.loads(row["receipt"])
            require(row["state"] != "aborted", "aborted topology cannot resume")
            require(
                not db.execute(
                    "SELECT id FROM operations WHERE state IN ('preparing','ready') AND id<>?",
                    (op_id,),
                ).fetchone(),
                "other preparation is active",
            )
            plan = json.loads(row["value"])
            require(
                plan["base_generation"] == self._metadata(db)["generation"]
                and plan["source_frontier"] == frontier,
                "prepared topology/source frontier is stale",
            )
            db.execute(
                "UPDATE operations SET state='preparing',error=NULL WHERE id=?",
                (op_id,),
            )
        try:
            versions = {}
            for selected in plan["candidates"]:
                location = self.root / "prepared" / op_id / selected["cell_id"]
                versions[selected["cell_id"]] = self.owners.stage(
                    selected, frontier, location
                )
            observed = self.observe()
            require(observed == frontier, "source changed during topology preparation")
            with transaction(self.database) as db:
                row = self._plan_row(db, op_id)
                require(
                    row["state"] == "preparing"
                    and self._metadata(db)["generation"] == plan["base_generation"],
                    "topology changed during preparation",
                )
                db.execute(
                    "UPDATE operations SET state='ready',staged=? WHERE id=?",
                    (canonical(versions).decode(), op_id),
                )
            return dict(
                operation_id=op_id,
                status="ready",
                plan_sha256=plan["plan_sha256"],
                staged_versions=versions,
            )
        except BaseException as error:
            with transaction(self.database) as db:
                db.execute(
                    "UPDATE operations SET state='failed',error=? WHERE id=? AND state='preparing'",
                    (str(error)[:2048], op_id),
                )
            raise

    def commit(self, op_id):
        frontier = self.observe()
        with transaction(self.database) as db:
            row = self._plan_row(db, op_id)
            if row["state"] == "committed":
                return json.loads(row["receipt"])
            require(row["state"] == "ready", "operation must be prepared before commit")
            plan, staged = json.loads(row["value"]), json.loads(row["staged"])
        for version in staged.values():
            self.owners.verify(version, frontier)
        observed = self.observe()
        require(
            observed == frontier == plan["source_frontier"],
            "source frontier changed before commit",
        )
        with transaction(self.database) as db:
            row = self._plan_row(db, op_id)
            if row["state"] == "committed":
                return json.loads(row["receipt"])
            meta, current = self._metadata(db), self._snapshot(db)
            require(
                row["state"] == "ready"
                and current["generation"] == plan["base_generation"],
                "topology commit CAS failed",
            )
            require(
                meta["frontier"] == observed,
                "source frontier changed after commit admission",
            )
            cells = {
                k: v for k, v in current["cells"].items() if k not in plan["inputs"]
            } | staged
            for c in cells.values():
                require(
                    set(c["roots"]) <= set(observed["roots"]),
                    "live ancestry is withdrawn",
                )
            require(
                len({c["base_identity"] for c in cells.values()}) <= 1,
                "population uses different base models",
            )
            value = dict(
                generation=current["generation"] + 1,
                operation_id=op_id,
                cells=cells,
                edges=plan["edges"],
                edge_policy=plan["edge_policy"],
                source_frontier=observed,
                production_accepted=False,
            )
            receipt = dict(
                operation_id=op_id,
                status="committed",
                generation=value["generation"],
                plan_sha256=plan["plan_sha256"],
                topology_sha256=digest(value),
                kind=plan["kind"],
                rollback_target=plan["rollback_target"],
            )
            for c in staged.values():
                db.execute(
                    "INSERT INTO versions VALUES(?,?,?)",
                    (c["cell_id"], c["version"], canonical(c).decode()),
                )
            db.execute(
                "INSERT INTO topologies VALUES(?,?)",
                (value["generation"], canonical(value).decode()),
            )
            meta.update(generation=value["generation"], frontier=observed)
            db.execute(
                "UPDATE metadata SET value=? WHERE singleton=1",
                (canonical(meta).decode(),),
            )
            db.execute(
                "UPDATE operations SET state='committed',receipt=? WHERE id=?",
                (canonical(receipt).decode(), op_id),
            )
        return receipt

    def abort(self, op_id):
        with transaction(self.database) as db:
            row = self._plan_row(db, op_id)
            require(row["state"] != "committed", "committed history cannot be erased")
            db.execute("UPDATE operations SET state='aborted' WHERE id=?", (op_id,))

    def rollback(self, op_id, target_generation, *, expected_generation):
        old, current = self.snapshot(target_generation), self.snapshot()
        candidates = [
            dict(
                cell_id=c["cell_id"],
                role=c["role"],
                directory=c["directory"],
                manifest_sha256=c["manifest_sha256"],
                support_roots=c["support_roots"],
                derivation="reuse",
            )
            for c in old["cells"].values()
        ]
        self.prepare(
            op_id,
            "rollback",
            expected_generation=expected_generation,
            inputs=list(current["cells"]),
            candidates=candidates,
            edges=old["edges"],
            edge_policy=old["edge_policy"],
            target_generation=target_generation,
        )
        return self.commit(op_id)

    def invoke(self, cell_id, query_roots, callback):
        required = roots(query_roots)
        require(
            required and callable(callback),
            "explicit source capability and reader required",
        )
        before, topology = self.observe(), self.snapshot()
        require(cell_id in topology["cells"], "cell is not live in current topology")
        selected = topology["cells"][cell_id]
        require(
            set(required) <= set(selected["support_roots"]) <= set(before["roots"]),
            "query outside cell support",
        )
        require(
            set(selected["roots"]) <= set(before["roots"]),
            "withdrawn learning ancestor",
        )
        value = self.owners.invoke(selected, self.observe, callback, required)
        require(
            self.observe() == before
            and self.snapshot()["generation"] == topology["generation"],
            "in-flight topology/source change suppressed answer",
        )
        return value

    def graph_snapshot(self):
        frontier, topology = self.observe(), self.snapshot()
        require(
            set(topology["edge_policy"]["ancestry_roots"]) <= set(frontier["roots"]),
            "withdrawn learned-edge ancestor",
        )
        return topology, frontier
