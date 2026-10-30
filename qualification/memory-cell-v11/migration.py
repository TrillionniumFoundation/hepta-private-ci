"""Research-only, same-host checkpoint handoff between cooperative processes.

The trusted controller owns a persistent location CAS in the replay database.
Checkpoint metadata never grants a lease. This is not the Rust owner authority,
remote attestation, a physical-host experiment, or mathematical unlearning.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import selectors
import sqlite3
import stat
import subprocess
import sys
import time

from maintenance import SQLiteReplayStore, artifact_identity


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_json(path, value):
    Path(path).write_text(encoded(value) + "\n")


class MigrationDenied(RuntimeError):
    def __init__(self, message, receipt=None):
        super().__init__(message)
        self.receipt = receipt or {}


class BudgetExceeded(MigrationDenied):
    pass


def artifact_files(path):
    """This profile transports exactly the two files emitted by models.save."""
    path = Path(path)
    if path.is_symlink() or not path.is_dir() or any(p.is_symlink() for p in path.parents):
        raise MigrationDenied("artifact directory is absent or contains a symlink")
    files = sorted(path.iterdir())
    if {p.name for p in files} != {"weights.pt", "manifest.json"}:
        raise MigrationDenied("unsupported artifact file set")
    if any(not stat.S_ISREG(p.lstat().st_mode) for p in files):
        raise MigrationDenied("artifact contains a special file")
    return files


class LocationControl:
    """Controller trust is explicit; all validity/CAS transactions share one DB."""

    def __init__(self, store, *, initialize=False):
        self.store, self.db = store, store.db
        if initialize:
            self.db.executescript("""
                CREATE TABLE migration_nodes(id TEXT PRIMARY KEY, root TEXT NOT NULL UNIQUE);
                CREATE TABLE migration_locations(
                    cell TEXT PRIMARY KEY, checkpoint TEXT NOT NULL, node TEXT NOT NULL,
                    path TEXT NOT NULL, digest TEXT NOT NULL, bytes INTEGER NOT NULL,
                    generation INTEGER NOT NULL);
                CREATE TABLE migration_prepared(
                    token TEXT PRIMARY KEY, cell TEXT NOT NULL, checkpoint TEXT NOT NULL,
                    source TEXT NOT NULL, target TEXT NOT NULL, expected_generation INTEGER NOT NULL,
                    source_path TEXT NOT NULL, target_path TEXT NOT NULL, digest TEXT NOT NULL,
                    bytes INTEGER NOT NULL, max_bytes INTEGER NOT NULL, max_wall REAL NOT NULL,
                    status TEXT NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE migration_events(id INTEGER PRIMARY KEY, action TEXT NOT NULL, details TEXT NOT NULL);
            """)

    def event(self, action, details):
        self.db.execute("INSERT INTO migration_events(action,details) VALUES (?,?)", (action, encoded(details)))

    def register_node(self, node, root):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=False)
        with self.store.transaction():
            self.db.execute("INSERT INTO migration_nodes VALUES (?,?)", (node, str(root)))

    def root(self, node):
        row = self.db.execute("SELECT root FROM migration_nodes WHERE id=?", (node,)).fetchone()
        if not row:
            raise MigrationDenied("unregistered logical node")
        return Path(row[0])

    def location(self, cell):
        row = self.db.execute("SELECT * FROM migration_locations WHERE cell=?", (cell,)).fetchone()
        if not row:
            raise MigrationDenied("cell has no authoritative location")
        return dict(row)

    def lease(self, cell):
        row = self.location(cell)
        return {key: row[key] for key in ("cell", "checkpoint", "generation")}

    def validate(self, row):
        """Validate the trusted ledger binding and actual source/local bytes."""
        if not self.store.checkpoint_is_valid(row["checkpoint"]):
            raise MigrationDenied("trusted checkpoint was revoked, corrected, or corrupted")
        bound = self.db.execute("SELECT digest,bytes FROM checkpoints WHERE id=?", (row["checkpoint"],)).fetchone()
        if (row["digest"], row["bytes"]) != (bound["digest"], bound["bytes"]):
            raise MigrationDenied("location differs from trusted training commit")
        path = Path(row["path"])
        if not path.resolve().is_relative_to(self.root(row["node"])):
            raise MigrationDenied("artifact lies outside its registered node")
        artifact_files(path)
        if artifact_identity(path) != (row["digest"], row["bytes"]):
            raise MigrationDenied("node artifact identity differs from trusted training commit")

    def publish(self, cell, node, checkpoint, *, expected_generation=None):
        """Trusted controller operation, never exposed in the worker protocol."""
        with self.store.transaction():
            bound = self.db.execute("SELECT * FROM checkpoints WHERE id=?", (checkpoint,)).fetchone()
            if not bound:
                raise MigrationDenied("checkpoint lacks an actual durable training commit")
            row = dict(cell=cell, checkpoint=checkpoint, node=node, path=bound["path"],
                       digest=bound["digest"], bytes=bound["bytes"], generation=1)
            self.validate(row)
            if expected_generation is None:
                self.db.execute("INSERT INTO migration_locations VALUES (?,?,?,?,?,?,?)", tuple(row.values()))
            else:
                row["generation"] = expected_generation + 1
                changed = self.db.execute("""UPDATE migration_locations SET checkpoint=?,node=?,path=?,digest=?,bytes=?,generation=?
                    WHERE cell=? AND generation=?""", (checkpoint, node, row["path"], row["digest"], row["bytes"],
                    row["generation"], cell, expected_generation)).rowcount
                if changed != 1:
                    raise MigrationDenied("publish generation CAS failed")
            self.event("publish", row)
        return self.lease(cell)

    def plan(self, cell, target, *, expected_generation, max_bytes, max_wall):
        if not isinstance(max_bytes, int) or max_bytes < 0 or not math.isfinite(max_wall) or max_wall < 0:
            raise ValueError("invalid migration budget")
        with self.store.transaction():
            current = self.location(cell)
            self.validate(current)
            if current["generation"] != expected_generation or current["node"] == target:
                raise MigrationDenied("plan has stale generation or unchanged location")
            token = secrets.token_hex(16)
            target_path = self.root(target) / ("prepared-" + token)
            row = dict(token=token, cell=cell, checkpoint=current["checkpoint"], source=current["node"],
                       target=target, expected_generation=expected_generation, source_path=current["path"],
                       target_path=str(target_path), digest=current["digest"], bytes=current["bytes"],
                       max_bytes=max_bytes, max_wall=max_wall, status="planned", receipt="{}")
            self.db.execute("INSERT INTO migration_prepared VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
            self.event("plan", row)
        return token

    def preparation(self, token):
        row = self.db.execute("SELECT * FROM migration_prepared WHERE token=?", (token,)).fetchone()
        if not row:
            raise MigrationDenied("no controller-issued preparation")
        return dict(row)

    def check_plan(self, plan):
        current = self.location(plan["cell"])
        if (current["generation"], current["node"], current["checkpoint"], current["digest"]) != (
                plan["expected_generation"], plan["source"], plan["checkpoint"], plan["digest"]):
            raise MigrationDenied("preparation is stale relative to owner generation")
        self.validate(current)

    def activate(self, token):
        started = time.perf_counter()
        try:
            with self.store.transaction():
                plan = self.preparation(token)
                if plan["status"] != "prepared":
                    raise MigrationDenied("candidate is not prepared")
                self.check_plan(plan)
                target = dict(cell=plan["cell"], checkpoint=plan["checkpoint"], node=plan["target"],
                              path=plan["target_path"], digest=plan["digest"], bytes=plan["bytes"],
                              generation=plan["expected_generation"] + 1)
                self.validate(target)
                changed = self.db.execute("""UPDATE migration_locations SET node=?,path=?,generation=?
                    WHERE cell=? AND generation=? AND node=? AND checkpoint=?""", (target["node"], target["path"],
                    target["generation"], target["cell"], plan["expected_generation"], plan["source"], plan["checkpoint"])).rowcount
                if changed != 1:
                    raise MigrationDenied("activation generation CAS failed")
                self.db.execute("UPDATE migration_prepared SET status='activated' WHERE token=?", (token,))
                receipt = dict(ok=True, token=token, location=target, pid=os.getpid(), wall_seconds=time.perf_counter() - started)
                self.event("activate", receipt)
            return receipt
        except Exception as error:
            receipt = dict(ok=False, token=token, error=type(error).__name__, reason=str(error),
                           pid=os.getpid(), wall_seconds=time.perf_counter() - started)
            with self.store.transaction():
                self.event("activation_denied", receipt)
            return receipt

    def check_read(self, node, lease):
        with self.store.transaction():
            row = self.location(lease["cell"])
            if (row["generation"], row["checkpoint"], row["node"]) != (
                    lease["generation"], lease["checkpoint"], node):
                raise MigrationDenied("read lease is stale or process is not current owner")
            self.validate(row)
            return row


class Worker:
    """A node can copy/compute, but cannot publish or activate itself."""

    def __init__(self, store, node):
        self.control, self.node, self.pending = LocationControl(store), node, {}
        self.control.root(node)

    def prepare(self, token):
        started, copied, phase = time.perf_counter(), 0, "precheck"
        plan = self.control.preparation(token)
        if plan["target"] != self.node or plan["status"] != "planned":
            raise MigrationDenied("preparation target or state mismatch")
        partial = Path(plan["target_path"] + ".partial")

        def budget(next_bytes):
            if next_bytes > plan["max_bytes"]:
                raise BudgetExceeded("checkpoint byte budget exceeded")
            if time.perf_counter() - started >= plan["max_wall"]:
                raise BudgetExceeded("soft migration wall budget exceeded")

        try:
            budget(plan["bytes"])
            with self.control.store.transaction():
                self.control.check_plan(plan)
            files = artifact_files(plan["source_path"])
            partial.mkdir(exist_ok=False)
            phase = "copy"
            for file in files:
                with file.open("rb") as source, (partial / file.name).open("xb") as target:
                    while block := source.read(65536):
                        budget(copied + len(block))
                        target.write(block)
                        copied += len(block)
                    target.flush()
                    os.fsync(target.fileno())
            budget(copied)
            phase = "validate_model"
            if artifact_identity(partial) != (plan["digest"], plan["bytes"]):
                raise MigrationDenied("copied artifact digest differs")
            manifest = json.loads((partial / "manifest.json").read_text())
            if manifest["spec"]["kind"] not in ("linear", "mlp", "associative"):
                raise MigrationDenied("migration profile supports feature models only")
            from models import load
            model = load(partial)
            budget(copied)
            phase = "seal_and_recheck"
            final = Path(plan["target_path"])
            if final.exists():
                raise MigrationDenied("target artifact already exists")
            os.replace(partial, final)
            fd = os.open(final.parent, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            with self.control.store.transaction():
                self.control.check_plan(plan)
                if artifact_identity(final) != (plan["digest"], plan["bytes"]):
                    raise MigrationDenied("sealed target changed during preparation")
                budget(copied)
                receipt = dict(status="prepared", token=token, node=self.node, pid=os.getpid(), copied_bytes=copied,
                               artifact_bytes=plan["bytes"], digest=plan["digest"], model_spec=model.spec,
                               wall_seconds=time.perf_counter() - started, serving_authorized=False)
                changed = self.control.db.execute("UPDATE migration_prepared SET status='prepared',receipt=? WHERE token=? AND status='planned'",
                                                  (encoded(receipt), token)).rowcount
                if changed != 1:
                    raise MigrationDenied("preparation state changed")
                self.control.event("prepared", receipt)
            return receipt
        except Exception as error:
            receipt = dict(status="rejected", token=token, node=self.node, pid=os.getpid(), phase=phase,
                           copied_bytes=copied, artifact_bytes=plan["bytes"], wall_seconds=time.perf_counter() - started,
                           error=type(error).__name__, reason=str(error), serving_authorized=False)
            with self.control.store.transaction():
                self.control.db.execute("UPDATE migration_prepared SET status='rejected',receipt=? WHERE token=? AND status='planned'",
                                        (encoded(receipt), token))
                self.control.event("preparation_denied", receipt)
            raise MigrationDenied(str(error), receipt) from error

    def begin_read(self, lease, features):
        from models import load, predict
        now = time.monotonic()
        self.pending = {key: value for key, value in self.pending.items() if value["deadline"] > now}
        if len(self.pending) >= 8 or not 1 <= len(features) <= 32:
            raise MigrationDenied("bounded read queue or batch limit exceeded")
        row = self.control.check_read(self.node, lease)
        model = load(row["path"])
        if any(len(feature) != model.spec["dimension"] for feature in features):
            raise MigrationDenied("input width differs from checkpoint")
        output = predict(model, features).tolist()
        token = secrets.token_hex(16)
        self.pending[token] = dict(lease=dict(lease), output=output, deadline=now + 30)
        return dict(token=token, output_released=False, generation_checked_before=row["generation"])

    def finish_read(self, token):
        pending = self.pending.pop(token, None)
        if pending is None or pending["deadline"] <= time.monotonic():
            raise MigrationDenied("pending read absent or expired", dict(output_discarded=True))
        try:
            row = self.control.check_read(self.node, pending["lease"])
        except Exception as error:
            raise MigrationDenied(str(error), dict(output_discarded=True, postcheck_failed=True)) from error
        return dict(output=pending["output"], output_released=True, generation_checked_after=row["generation"],
                    checkpoint=row["checkpoint"], artifact_sha256=row["digest"])


def node_main(db_path, node):
    import torch
    torch.set_num_threads(2)
    store = SQLiteReplayStore(db_path)
    worker = Worker(store, node)
    log = (worker.control.root(node) / "worker.jsonl").open("a")

    def emit(receipt):
        log.write(encoded(receipt) + "\n")
        log.flush()
        os.fsync(log.fileno())
        print(encoded(receipt), flush=True)

    emit(dict(ok=True, event="ready", node=node, pid=os.getpid(), parent_pid=os.getppid(),
              source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    for line in sys.stdin:
        request, started = json.loads(line), time.perf_counter()
        try:
            op = request["op"]
            if op == "stop":
                result = dict(stopped=True)
            elif op == "prepare":
                result = worker.prepare(request["token"])
            elif op == "begin_read":
                result = worker.begin_read(request["lease"], request["features"])
            elif op == "finish_read":
                result = worker.finish_read(request["token"])
            else:
                raise MigrationDenied("operation is not exposed to workers")
            receipt = dict(ok=True, result=result)
        except Exception as error:
            receipt = dict(ok=False, error=type(error).__name__, reason=str(error), details=getattr(error, "receipt", {}))
        receipt.update(request_id=request.get("request_id"), op=request.get("op"), node=node, pid=os.getpid(),
                       wall_seconds=time.perf_counter() - started)
        emit(receipt)
        if request.get("op") == "stop":
            break
    log.close()
    store.close()


class NodeClient:
    def __init__(self, db_path, node, root):
        self.node, self.receipts = node, []
        self.stderr = (Path(root) / "stderr.log").open("a")
        self.process = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()), "node", "--db", str(db_path), "--node", node],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True)
        self.ready = self.receive()
        if not self.ready["ok"] or self.ready["pid"] != self.process.pid:
            raise RuntimeError("worker failed startup")

    def receive(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(30):
                raise TimeoutError("worker response timed out")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("worker exited without receipt")
        receipt = json.loads(line)
        self.receipts.append(receipt)
        return receipt

    def rpc(self, op, **args):
        self.process.stdin.write(encoded(dict(op=op, request_id=len(self.receipts), **args)) + "\n")
        self.process.stdin.flush()
        return self.receive()

    def read(self, lease, features):
        begin = self.rpc("begin_read", lease=lease, features=features)
        return self.rpc("finish_read", token=begin["result"]["token"]) if begin["ok"] else begin

    def close(self):
        if self.process.poll() is None:
            self.rpc("stop")
            self.process.wait(timeout=10)
        self.process.stdin.close()
        self.process.stdout.close()
        self.stderr.close()
        return dict(node=self.node, pid=self.process.pid, returncode=self.process.returncode)


def train_fixture(store, destination, checkpoint, seed):
    import numpy as np
    import torch
    from models import FeatureMemory, fit, save
    torch.set_num_threads(2)
    batch = store.claim_batch(new_count=4, replay_count=4)
    if batch is None or len(batch.records) != 4:
        raise RuntimeError("fixture must train from all four actual active records")
    features = np.asarray([record["features"] for record in batch.records], np.float32)
    values = np.asarray([record["value"] for record in batch.records], np.float32)
    schedule = np.random.default_rng(seed).integers(4, size=(80, 4), dtype=np.int64)
    model = FeatureMemory("mlp", 4, 2, hidden=8, seed=seed)
    receipt = fit(model, features, values, [("binary", 2)], schedule, lr=.03,
                  source_ids=[record["source_ids"][0] for record in batch.records], label="migration-functional")
    save(model, destination, metadata={"claimed_owner": "target", "claimed_generation": 999999,
                                      "warning": "metadata claims grant no authority"})
    committed = store.commit_training(batch, checkpoint, destination)
    np.save(destination.parent / (checkpoint + "-schedule.npy"), schedule, allow_pickle=False)
    write_json(destination.parent / (checkpoint + "-training.json"), dict(fit=receipt, commit=committed, record_ids=[r["record_id"] for r in batch.records]))
    return committed


def run_functional(output):
    """One bounded functional run; no quality or cross-host efficiency claim."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    source_root = Path(__file__).resolve().parent
    snapshot = output / "EXECUTED_SOURCE"
    snapshot.mkdir()
    identities = {}
    for name in ["migration.py", "test_migration.py", "models.py", "maintenance.py"]:
        payload = (source_root / name).read_bytes()
        (snapshot / name).write_bytes(payload)
        identities[name] = hashlib.sha256(payload).hexdigest()
    write_json(output / "PLAN.json", dict(schema="hepta.memory.v11.migration-functional.v1", same_machine=True,
        controller_pid=os.getpid(), source_sha256=identities, fixture_seed=51031, fit_steps=80, max_copy_wall_seconds=10,
        scenarios=["metadata_not_authority", "byte_budget_reject", "wall_budget_reject", "corrupt_prepared_reject",
                   "prepare_not_owner", "generation_CAS", "inflight_stale_discard", "persistent_restart",
                   "correction_veto", "corrected_checkpoint_recovery", "revocation_veto"],
        authority="research SQLite controller; not Rust owner", wall_budget="soft checks between IO/model operations"))
    db_path = output / "control.sqlite"
    store = SQLiteReplayStore(db_path)
    control = LocationControl(store, initialize=True)
    for node in ["source", "target"]:
        control.register_node(node, output / node)
    records = [dict(key=f"fixture-{i}", type="functional", version=1, source_ids=[f"migration-source-{i}"],
                    features=[float(j == i) for j in range(4)], value=[float(i // 2), float(i % 2)]) for i in range(4)]
    for record in records:
        store.append(record)
    write_json(output / "INPUT_RECORDS.json", records)
    committed = train_fixture(store, control.root("source") / "checkpoint-initial", "initial", 51031)
    lease = control.publish("memory", "source", "initial")
    clients, operations, checks = {}, {}, {}
    try:
        for node in ["source", "target"]:
            clients[node] = NodeClient(db_path, node, control.root(node))
        source, target = clients["source"], clients["target"]
        features = [record["features"] for record in records]
        operations["source_initial"] = source.read(lease, features)
        checks["actual_source_model_serves"] = operations["source_initial"]["ok"]
        fake = dict(lease, generation=999999)
        operations["metadata_claim_denied"] = target.read(fake, features)
        operations["worker_publish_denied"] = target.rpc("publish", cell="memory", generation=999999)
        checks["metadata_cannot_grant_authority"] = not operations["metadata_claim_denied"]["ok"] and not operations["worker_publish_denied"]["ok"]
        for label, max_bytes, max_wall in [("byte_budget", committed["artifact_bytes"] - 1, 10), ("wall_budget", committed["artifact_bytes"], 0)]:
            token = control.plan("memory", "target", expected_generation=1, max_bytes=max_bytes, max_wall=max_wall)
            operations[label] = target.rpc("prepare", token=token)
            checks[label + "_rejects_without_handoff"] = not operations[label]["ok"] and control.location("memory")["generation"] == 1
        token = control.plan("memory", "target", expected_generation=1, max_bytes=committed["artifact_bytes"], max_wall=10)
        operations["corrupt_prepare"] = target.rpc("prepare", token=token)
        damaged = Path(control.preparation(token)["target_path"]) / "weights.pt"
        payload = bytearray(damaged.read_bytes())
        payload[-1] ^= 1
        damaged.write_bytes(payload)
        operations["corrupt_activation"] = control.activate(token)
        checks["actual_corrupt_bytes_veto_activation"] = operations["corrupt_prepare"]["ok"] and not operations["corrupt_activation"]["ok"]
        token = control.plan("memory", "target", expected_generation=1, max_bytes=committed["artifact_bytes"], max_wall=10)
        operations["prepared"] = target.rpc("prepare", token=token)
        operations["target_before_cas"] = target.read(dict(lease, generation=2), features)
        before = source.rpc("begin_read", lease=lease, features=features)
        operations["inflight_before_cas"] = before
        operations["activation"] = control.activate(token)
        operations["old_inflight_after_cas"] = source.rpc("finish_read", token=before["result"]["token"])
        operations["source_stale_lease"] = source.read(lease, features)
        operations["duplicate_activation"] = control.activate(token)
        store.close()
        store = SQLiteReplayStore(db_path)
        control = LocationControl(store)
        new_lease = control.lease("memory")
        operations["target_after_controller_reopen"] = target.read(new_lease, features)
        checks["prepared_target_cannot_serve"] = operations["prepared"]["ok"] and not operations["target_before_cas"]["ok"]
        checks["CAS_fences_source_and_duplicate"] = operations["activation"]["ok"] and not operations["source_stale_lease"]["ok"] and not operations["duplicate_activation"]["ok"]
        checks["inflight_output_discarded_on_handoff"] = not operations["old_inflight_after_cas"]["ok"] and operations["old_inflight_after_cas"]["details"].get("output_discarded") is True
        checks["budget_recovery_and_persistent_identical_output"] = new_lease["generation"] == 2 and operations["target_after_controller_reopen"]["ok"] and operations["source_initial"]["result"]["output"] == operations["target_after_controller_reopen"]["result"]["output"]
        for mode in ["correction", "revocation"]:
            current = control.lease("memory")
            current_bytes = control.location("memory")["bytes"]
            token = control.plan("memory", "source", expected_generation=current["generation"], max_bytes=current_bytes, max_wall=10)
            operations[mode + "_prepared"] = source.rpc("prepare", token=token)
            inflight = target.rpc("begin_read", lease=current, features=features)
            if mode == "correction":
                corrected = dict(records[0], version=2, value=[1.0, 1.0], source_ids=["migration-source-correction"])
                store.append(corrected)
                write_json(output / "CORRECTION.json", corrected)
            else:
                store.revoke_source("migration-source-1")
            operations[mode + "_inflight_rejected"] = target.rpc("finish_read", token=inflight["result"]["token"])
            operations[mode + "_activation_rejected"] = control.activate(token)
            operations[mode + "_current_read_rejected"] = target.read(current, features)
            operations[mode + "_prepared_read_rejected"] = source.read(dict(current, generation=current["generation"] + 1), features)
            checks[mode + "_vetoes_current_prepared_and_inflight"] = operations[mode + "_prepared"]["ok"] and all(not operations[mode + suffix]["ok"] for suffix in ["_inflight_rejected", "_activation_rejected", "_current_read_rejected", "_prepared_read_rejected"])
            if mode == "correction":
                train_fixture(store, control.root("target") / "checkpoint-corrected", "corrected", 51032)
                current = control.publish("memory", "target", "corrected", expected_generation=current["generation"])
                operations["corrected_checkpoint_recovery"] = target.read(current, features)
                checks["actual_corrected_retraining_recovers_service"] = operations["corrected_checkpoint_recovery"]["ok"] and current["generation"] == 3
        checks["distinct_same_host_child_processes"] = source.process.pid != target.process.pid and all(c.ready["parent_pid"] == os.getpid() for c in clients.values())
        checks["source_archive_retained"] = (control.root("source") / "checkpoint-initial" / "weights.pt").is_file()
    finally:
        processes = [client.close() for client in clients.values()]
        stats = store.stats()
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()
        write_json(output / "OPERATIONS.json", operations)
        write_json(output / "PROCESSES.json", processes)
    final_sources = {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in identities}
    checks["source_unchanged_during_execution"] = identities == final_sources
    result = dict(schema="hepta.memory.v11.migration-functional-result.v1", all_checks_passed=all(checks.values()),
                  checks=checks, wall_seconds=time.perf_counter() - started, processes=processes,
                  initial_checkpoint=committed, ledger_stats_before_close=stats,
                  physical_host_claim=False, mathematical_unlearning_claim=False,
                  cost_scope="actual local copy bytes and measured process/operation wall; no network or cross-host result")
    write_json(output / "RESULTS.json", result)
    files = [dict(path=p.relative_to(output).as_posix(), bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(output.rglob("*")) if p.is_file()]
    write_json(output / "INVENTORY.json", dict(files=files, total_bytes=sum(p["bytes"] for p in files), inventory_excludes_itself=True))
    if not result["all_checks_passed"]:
        raise AssertionError("functional migration checks failed: " + encoded(checks))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("node")
    worker.add_argument("--db", type=Path, required=True)
    worker.add_argument("--node", required=True)
    run = commands.add_parser("run")
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "node":
        node_main(args.db, args.node)
    else:
        print(encoded(run_functional(args.output)))


if __name__ == "__main__":
    main()
