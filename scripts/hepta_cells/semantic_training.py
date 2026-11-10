"""Durable experimental head training; no native adoption/signing authority.

Evaluation/holdout commitments bind the operation, without proving evaluator
independence. The host owns data rights, original result custody and provenance.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

import numpy as np

from .bundle import Bundle, validate_local_update
from .component_types import CellError, PendingExecution, RequestConflict
from .component_types import _bounded_json, _hex, _token
from .semantic import (
    LocalHead,
    SemanticCandidate,
    SemanticCell,
    SemanticTrainingError,
    _digest,
)
from .semantic_component import SemanticComponent

MAX_BYTES = 4 * 1024 * 1024


def encoded(value):
    return _bounded_json(value, MAX_BYTES)


def array_record(value):
    value = np.asarray(value)
    if (
        value.nbytes > MAX_BYTES // 2
        or value.dtype.kind not in "fiu"
        or not np.isfinite(value).all()
    ):
        raise CellError("finite numeric arrays required")
    return dict(
        dtype=value.dtype.str, shape=list(value.shape), data=value.tobytes().hex()
    )


def array_read(value):
    dtype = np.dtype(value["dtype"])
    if dtype.kind not in "fiu" or dtype.itemsize > 8:
        raise CellError("unsupported retained numeric array")
    result = np.frombuffer(bytes.fromhex(value["data"]), dtype=dtype).reshape(
        value["shape"]
    )
    if not np.isfinite(result).all():
        raise CellError("nonfinite retained array")
    return result


@dataclass(frozen=True)
class RetainedSemanticTraining:
    component: SemanticComponent
    candidate: SemanticCandidate
    original_bytes: bytes


class SemanticTrainingOwner:
    """Persist Pending before training; never blindly replay interrupted work.

    A create-only, fsynced original JSON result precedes the completion commit.
    Explicit recover reads only that path; missing material remains unresolved.
    SQLite and the result directory are trusted local custody, not authentication.
    Costs retain the trainer's scope; external residency/energy remain unmeasured.
    """

    def __init__(self, database, result_directory, *, create=False):
        if os.name != "posix":
            raise CellError("semantic training directory-fsync owner requires POSIX")
        path = Path(database).resolve()
        self.directory = Path(result_directory).resolve(strict=True)
        if not self.directory.is_dir():
            raise CellError("original result directory required")
        if create:
            with path.open("xb"):
                pass
        self.db = sqlite3.connect(
            path.as_uri() + "?mode=rw", uri=True, isolation_level=None
        )
        self.db.row_factory = sqlite3.Row
        try:
            self.db.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;")
            if create:
                self.db.execute("""CREATE TABLE semantic_training(
                    operation TEXT PRIMARY KEY, request TEXT NOT NULL,
                    status TEXT NOT NULL, result BLOB, result_digest TEXT, attempt TEXT)""")
            self.db.execute(
                "SELECT operation,request,status,result,result_digest,attempt FROM semantic_training LIMIT 0"
            )
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def propose(
        self,
        operation,
        component,
        inputs,
        targets,
        *,
        artifact_id,
        evaluation_profile,
        holdout_commitment,
        steps=1,
        learning_rate=0.01,
    ):
        _token(operation)
        _token(artifact_id)
        _hex(evaluation_profile)
        _hex(holdout_commitment)
        if not isinstance(component, SemanticComponent):
            raise CellError("frozen semantic component required")
        cell = component._cell
        if (
            not isinstance(inputs, (list, tuple))
            or not 1 <= len(inputs) <= cell.budget.max_items
        ):
            raise CellError("bounded concrete training inputs required")
        if (
            type(steps) is not int
            or not 1 <= steps <= cell.budget.max_train_steps
            or type(learning_rate) not in (int, float)
            or not np.isfinite(learning_rate)
            or learning_rate <= 0
        ):
            raise CellError("bounded positive training steps/rate required")
        items = [
            dict(text=value)
            if isinstance(value, str)
            else dict(array=array_record(np.asarray(value, dtype=np.float64)))
            for value in inputs
        ]
        target = array_record(cell.objective.targets(targets, len(items)))
        request = encoded(
            dict(
                schema="hepta.experimental.semantic-training-request.v1",
                operation=operation,
                result_path=str(
                    self.directory / (hash_bytes(operation.encode()) + ".json")
                ),
                source_bundle=component.bundle.record(),
                source_component=component.identity.digest,
                source_cell=cell.digest,
                objective=asdict(cell.objective),
                budget=asdict(cell.budget),
                artifact_id=artifact_id,
                evaluation_profile=evaluation_profile,
                holdout_commitment=holdout_commitment,
                inputs=items,
                targets=target,
                steps=steps,
                learning_rate=learning_rate,
            )
        )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM semantic_training WHERE operation=?", (operation,)
            ).fetchone()
            if row is not None:
                if row["request"] != request:
                    raise RequestConflict("original training request differs")
                if row["status"] != "Completed":
                    raise PendingExecution(
                        "original outcome unresolved; recover original result"
                    )
                raw = bytes(row["result"])
                if hash_bytes(raw) != row["result_digest"]:
                    raise CellError("retained training result changed")
                self.db.execute("COMMIT")
                return self._restore(component, request, raw)
            if (
                self.db.execute("SELECT COUNT(*) FROM semantic_training").fetchone()[0]
                >= 128
            ):
                raise CellError("training operation capacity exhausted")
            self.db.execute(
                "INSERT INTO semantic_training VALUES(?,?,'Pending',NULL,NULL,NULL)",
                (operation, request),
            )
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        return self._execute(component, request)

    def _execute(self, component, request):
        wall, cpu = time.perf_counter(), time.process_time()
        frozen = json.loads(request)
        operation = frozen["operation"]
        candidate = None
        try:
            copied = [
                value["text"] if "text" in value else array_read(value["array"])
                for value in frozen["inputs"]
            ]
            target, candidate = component.propose(
                copied,
                array_read(frozen["targets"]),
                artifact_id=frozen["artifact_id"],
                evaluation_profile=frozen["evaluation_profile"],
                steps=frozen["steps"],
                learning_rate=frozen["learning_rate"],
            )
            record = dict(
                schema="hepta.experimental.semantic-training-result.v1",
                request_digest=hash_bytes(request.encode()),
                bundle=target.bundle.record(),
                arrays=[array_record(value) for value in candidate.head.arrays],
                dataset=candidate.dataset_digest,
                steps=candidate.steps,
                loss_before=candidate.loss_before,
                loss_after=candidate.loss_after,
                training_receipt=candidate.training_receipt,
                owner_cost=dict(
                    host_wall_seconds=time.perf_counter() - wall,
                    process_cpu_seconds=time.process_time() - cpu,
                    scope="through original training; excludes result commit/readback",
                ),
            )
            raw = encoded(record).encode()
            retained = self._restore(component, request, raw)
            path = Path(frozen["result_path"])
            with path.open("xb") as result:
                result.write(raw)
                result.flush()
                os.fsync(result.fileno())
            # A file and containing-directory fsync precede durable completion.
            descriptor = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._complete(operation, raw)
            return retained
        except BaseException as error:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            attempt = dict(
                status="unresolved",
                error_type=type(error).__name__,
                host_wall_seconds=time.perf_counter() - wall,
                process_cpu_seconds=time.process_time() - cpu,
                original_training_receipt=(
                    error.receipt
                    if isinstance(error, SemanticTrainingError)
                    else candidate.training_receipt
                    if candidate is not None
                    else None
                ),
            )
            self.db.execute(
                "UPDATE semantic_training SET attempt=? WHERE operation=?",
                (encoded(attempt), operation),
            )
            raise

    def _complete(self, operation, raw):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM semantic_training WHERE operation=?", (operation,)
            ).fetchone()
            if row is None:
                raise RequestConflict("original training operation missing")
            if row["status"] == "Completed":
                if bytes(row["result"]) != raw or row["result_digest"] != hash_bytes(
                    raw
                ):
                    raise RequestConflict("original completed result differs")
            elif row["status"] == "Pending":
                changed = self.db.execute(
                    "UPDATE semantic_training SET status='Completed',result=?,result_digest=? WHERE operation=? AND status='Pending'",
                    (raw, hash_bytes(raw), operation),
                )
                if changed.rowcount != 1:
                    raise RequestConflict("original Pending completion lost")
            else:
                raise RequestConflict("invalid retained training state")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def recover(self, operation, component):
        """Read the exact original export; never train or create missing history."""
        _token(operation)
        row = self.db.execute(
            "SELECT * FROM semantic_training WHERE operation=?", (operation,)
        ).fetchone()
        if row is None:
            raise RequestConflict("original training operation missing")
        frozen = json.loads(row["request"])
        expected = self.directory / (hash_bytes(operation.encode()) + ".json")
        if frozen["result_path"] != str(expected):
            raise RequestConflict("original result directory differs")
        if row["status"] == "Completed":
            raw = bytes(row["result"])
            if hash_bytes(raw) != row["result_digest"]:
                raise CellError("retained training result changed")
        else:
            if not expected.is_file() or expected.is_symlink():
                raise PendingExecution("original exported training result unavailable")
            if expected.stat().st_size > MAX_BYTES:
                raise CellError("original training result exceeds byte budget")
            raw = expected.read_bytes()
        retained = self._restore(component, row["request"], raw)
        if row["status"] != "Completed":
            self._complete(operation, raw)
        return retained

    def _restore(self, component, request, raw):
        if len(raw) > MAX_BYTES:
            raise CellError("retained result exceeds byte budget")
        record, frozen = json.loads(raw), json.loads(request)
        source = component._cell
        if (
            encoded(record).encode() != raw
            or record["schema"] != "hepta.experimental.semantic-training-result.v1"
            or record["request_digest"] != hash_bytes(request.encode())
            or frozen["source_bundle"] != component.bundle.record()
            or frozen["source_component"] != component.identity.digest
            or frozen["source_cell"] != source.digest
            or frozen["objective"] != asdict(source.objective)
            or frozen["budget"] != asdict(source.budget)
        ):
            raise CellError("retained result is not the exact frozen operation")
        arrays = [array_read(value) for value in record["arrays"]]
        if len(arrays) not in (2, 3):
            raise CellError("invalid retained private head")
        head = LocalHead(arrays[0], arrays[1], arrays[2] if len(arrays) == 3 else None)
        bundle = Bundle(**record["bundle"])
        validate_local_update("shared_semantic", component.bundle, bundle)
        receipt, lineage = record["training_receipt"], bundle.training_lineage
        if not isinstance(receipt, dict):
            raise CellError("original training receipt required")
        items = [
            value["text"] if "text" in value else array_read(value["array"])
            for value in frozen["inputs"]
        ]
        targets = array_read(frozen["targets"])
        item_digests = [
            (
                _digest("array", value.dtype.str, value.shape, value.tobytes())
                if isinstance(value, np.ndarray)
                else _digest(type(value).__name__, value)
            )
            for value in items
        ]
        expected_dataset = _digest(
            "semantic-dataset-v1",
            *item_digests,
            targets.shape,
            targets.dtype.str,
            targets.tobytes(),
        )
        if (
            receipt.get("schema") != "hepta.cell.semantic-training.v1"
            or receipt.get("cell_id") != source.cell_id
            or receipt.get("objective") != source.objective.kind
            or receipt.get("target_name") != source.objective.target_name
            or record["dataset"] != expected_dataset
            or bundle.artifact_id != frozen["artifact_id"]
            or lineage["evaluation_profile"] != frozen["evaluation_profile"]
            or lineage["dataset"] != record["dataset"]
            or receipt["source_digest"] != source.digest
            or receipt["source_bundle_digest"] != component.bundle.digest()
            or receipt["candidate_bundle_digest"] != bundle.digest()
            or receipt["dataset_digest"] != record["dataset"]
            or receipt["completed_steps"] != frozen["steps"]
            or record["steps"] != frozen["steps"]
            or receipt["status"] != "completed"
            or receipt["learning_rate"] != frozen["learning_rate"]
            or receipt["requested_steps"] != frozen["steps"]
            or receipt["loss_before"] != record["loss_before"]
            or receipt["loss_after"] != record["loss_after"]
            or lineage["update_rule"]
            != _digest(
                "local-head-sgd-v1",
                frozen["steps"],
                frozen["learning_rate"],
                source.objective.kind,
            )
        ):
            raise CellError("retained candidate/training lineage differs")
        owner_cost = record.get("owner_cost")
        if not isinstance(owner_cost, dict) or owner_cost.get("scope") != (
            "through original training; excludes result commit/readback"
        ):
            raise CellError("original declared owner-cost scope required")
        for costs in (receipt, owner_cost):
            for key in ("host_wall_seconds", "process_cpu_seconds"):
                value = costs.get(key)
                if (
                    type(value) not in (int, float)
                    or not np.isfinite(value)
                    or value < 0
                ):
                    raise CellError(
                        "original finite nonnegative measured cost required"
                    )
        target = SemanticCell(
            source.cell_id, source.binding, head, source.objective, source.budget
        )
        restored = SemanticComponent(component._pool, target, bundle)
        candidate = SemanticCandidate(
            source.cell_id,
            source.digest,
            source.binding,
            source.objective,
            head,
            record["dataset"],
            record["steps"],
            record["loss_before"],
            record["loss_after"],
            receipt,
        )
        return RetainedSemanticTraining(restored, candidate, raw)


def hash_bytes(value):
    return hashlib.sha256(value).hexdigest()
