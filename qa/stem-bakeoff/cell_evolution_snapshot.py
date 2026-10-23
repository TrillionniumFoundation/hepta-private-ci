"""Offline immutable Head/Router snapshots; no production writer or authority.

Source withdrawal views are supplied by the research host. They are consistency
witnesses, not authenticated production ledger receipts. Tensor budgets exclude
the shared Encoder, allocator overhead and backend workspaces; measure RSS too.
"""

from dataclasses import asdict, dataclass
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import threading

import torch

from cell_head_training import (_json_bytes, _state_digest, load_head_artifact,
                                save_head_artifact)
from cell_router_artifact import load_router_artifact, save_router_artifact
from cell_router_training import RouterCellV1, _check_cells
from feature_bundle import FeatureBundleV1, FeatureIdentityV1

MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 16384


class EvolutionError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def group_digest(group):
    return digest(["hepta.evolution.source-group.v1", group])


def _is_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class WithdrawalViewV1:
    scope_id: str
    epoch: int = 0
    revoked_source_digests: tuple[str, ...] = ()

    def __post_init__(self):
        if (not isinstance(self.scope_id, str) or not 1 <= len(self.scope_id) <= 128
                or type(self.epoch) is not int or not 0 <= self.epoch < 2**64
                or type(self.revoked_source_digests) is not tuple
                or len(self.revoked_source_digests) > MAX_SOURCES
                or any(not _is_digest(s) for s in self.revoked_source_digests)
                or len(set(self.revoked_source_digests)) != len(self.revoked_source_digests)):
            raise EvolutionError("invalid withdrawal view")
        object.__setattr__(self, "revoked_source_digests", tuple(sorted(self.revoked_source_digests)))


@dataclass(frozen=True)
class EvolutionBudgetV1:
    cells: int = 2
    resident_tensor_bytes: int = 16 * 1024 * 1024
    transition_tensor_bytes: int = 64 * 1024 * 1024
    gradient_bytes: int = 8 * 1024 * 1024
    optimizer_state_bytes: int = 0
    head_example_calls: int = 1_000_000
    parameter_example_updates: int = 10**12
    router_example_steps: int = 1_000_000
    inference_cells_per_row: int = 1
    inference_cost_units_per_row: float = 1.0

    def validate(self):
        values = asdict(self)
        cost = values.pop("inference_cost_units_per_row")
        if (any(type(v) is not int or not 0 <= v <= 2**62 for v in values.values())
                or not 1 <= self.cells <= 2 or not 1 <= self.inference_cells_per_row <= self.cells
                or type(cost) not in (int, float) or not math.isfinite(cost) or not 0 < cost <= 1e9):
            raise EvolutionError("invalid bounded evolution budget")


def check_budget(usage, budget):
    if type(budget) is not EvolutionBudgetV1:
        raise EvolutionError("typed evolution budget required")
    budget.validate()
    limits = asdict(budget)
    for key, value in usage.items():
        if key not in limits or type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise EvolutionError("invalid resource accounting")
        if value > limits[key]:
            raise EvolutionError(f"evolution budget exceeded: {key}")


def tensor_bytes(modules):
    storages = {}
    for module in modules:
        for tensor in module.state_dict().values():
            storage = tensor.untyped_storage()
            storages[(str(tensor.device), storage.data_ptr())] = storage.nbytes()
    return sum(storages.values())


def _source_sets(report, witnesses):
    if not isinstance(witnesses, dict) or set(witnesses) != set(report["splits"]):
        raise EvolutionError("complete source-group witness required")
    learned, protected = set(), set()
    for name, split in report["splits"].items():
        groups = witnesses[name]
        rows = split["source_record_digests"]
        if (not isinstance(groups, (tuple, list)) or len(groups) != len(rows)
                or any(not isinstance(g, str) or not 1 <= len(g) <= 256 for g in groups)
                or hashlib.sha256(_json_bytes(groups)).hexdigest() != split["source_group_sha256"]):
            raise EvolutionError("source-group witness hash mismatch")
        sources = set(rows) | {group_digest(g) for g in groups}
        if name in ("train", "calibration"):
            learned.update(sources)
            learned.add(digest({k: split[k] for k in ("source_record_digests", "source_group_sha256",
                                                     "labels_sha256", "bundle_digests")}))
        if name != "train":
            protected.update(sources)
    return learned, protected


def check_sources(sources, identity, provider, minimum=None):
    if not callable(provider):
        raise EvolutionError("current withdrawal-view provider required")
    view = provider()
    if type(view) is not WithdrawalViewV1 or view.scope_id != identity.scope_id:
        raise EvolutionError("withdrawal scope mismatch")
    if minimum is not None:
        if (view.epoch < minimum["epoch"]
                or not set(minimum["revoked_source_digests"]) <= set(view.revoked_source_digests)
                or (view.epoch == minimum["epoch"] and asdict(view) != {
                    **minimum, "revoked_source_digests": tuple(minimum["revoked_source_digests"])})):
            raise EvolutionError("withdrawal frontier rollback or same-epoch fork")
    if set(sources) & set(view.revoked_source_digests):
        raise EvolutionError("withdrawn learning ancestor; entire snapshot is unavailable")
    return view


def _read_manifest(directory, expected):
    path = Path(directory)
    member = path / "snapshot.json"
    if path.is_symlink() or not path.is_dir() or not _is_digest(expected):
        raise EvolutionError("real snapshot directory and retained digest required")
    info = member.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_MANIFEST_BYTES:
        raise EvolutionError("snapshot manifest file boundary")
    data = member.read_bytes()
    if len(data) != info.st_size or hashlib.sha256(data).hexdigest() != expected:
        raise EvolutionError("snapshot manifest changed")
    return json.loads(data)


class EvolutionSnapshotV1:
    def __init__(self, directory, manifest_sha256, manifest, cells, router, budget):
        self.directory = Path(directory)
        self.manifest_sha256 = manifest_sha256
        self._manifest = copy.deepcopy(manifest)
        self.cells = tuple(cells)
        self.router = router
        self.budget = budget
        self.identity = cells[0].head.identity

    @property
    def report(self):
        return copy.deepcopy(self._manifest)

    @property
    def generation(self):
        return self._manifest["graph_generation"]

    def require_current(self, provider):
        if _read_manifest(self.directory, self.manifest_sha256) != self._manifest:
            raise EvolutionError("in-memory snapshot differs from persisted manifest")
        cells, bindings, signature, _ = _check_cells(self.cells)
        if bindings != self._manifest["cell_bindings"] or signature[0] != self.identity:
            raise EvolutionError("snapshot Cell binding changed")
        if self.router is not None and (
                digest(self.router.report) != self._manifest["router_report_sha256"]
                or _state_digest(self.router._net) != self.router.report["trained_tensor_sha256"]):
            raise EvolutionError("snapshot Router binding changed")
        modules = [c.head._head for c in cells] + ([self.router._net] if self.router else [])
        if any(p.grad is not None for module in modules for p in module.parameters()):
            raise EvolutionError("frozen inference snapshot retains optimizer gradients")
        resident = tensor_bytes(modules)
        check_budget({"cells": len(cells), "resident_tensor_bytes": resident}, self.budget)
        check_budget({"inference_cells_per_row": self.router.report["config"]["top_k"] if self.router else 1,
                      "inference_cost_units_per_row": min(self.router.report["config"]["budget_units"],
                        self.budget.inference_cost_units_per_row) if self.router else cells[0].cost_units}, self.budget)
        return check_sources(self._manifest["source_closure"], self.identity, provider,
                             self._manifest["withdrawal_view"])

    def predict_task(self, bundle, withdrawal_provider):
        before = self.require_current(withdrawal_provider)
        if type(bundle) is not FeatureBundleV1:
            raise EvolutionError("typed frozen features required")
        bundle.require_identity(self.identity)
        if self.router is not None:
            output = self.router.predict_task(bundle, self.cells,
                budget_units=min(self.budget.inference_cost_units_per_row,
                                 self.router.report["config"]["budget_units"]))
        else:
            cell = self.cells[0]
            check_budget({"inference_cells_per_row": 1,
                          "inference_cost_units_per_row": cell.cost_units}, self.budget)
            output = cell.head.predict_task(bundle)
            output.update({"router_forward_calls": 0, "head_example_calls": len(bundle.source_record_digests),
                "head_module_invocations": {cell.cell_id: 1},
                "actual_cost_units": len(bundle.source_record_digests) * cell.cost_units,
                "routes": [{"source_record_digest": row, "selected": [cell.cell_id],
                    "candidates": [{"cell_id": cell.cell_id, "predicted_loss_cost": None,
                                    "declared_cost_units": cell.cost_units, "legal": True}],
                    "actual_calls": [cell.cell_id], "actual_cost_units": cell.cost_units,
                    "budget_units": self.budget.inference_cost_units_per_row, "route_mode": "single_cell"}
                    for row in bundle.source_record_digests]})
        if self.require_current(withdrawal_provider) != before:
            raise EvolutionError("withdrawal view changed during inference; discard entire result")
        output.update({"snapshot_sha256": self.manifest_sha256, "graph_generation": self.generation})
        return output


def _persist_snapshot(cells, router, router_source_groups, directory, budget, withdrawal_provider, *,
                     parent=None, operation="bootstrap", receipt=None, restored_from=None):
    ordered, bindings, signature, _ = _check_cells(cells)
    identity = signature[0]
    if (len(ordered) > 2 or (len(ordered) == 2) != (router is not None)
            or operation not in ("bootstrap", "split", "continue", "merge", "retire", "rollback")
            or (parent is None) != (operation == "bootstrap")):
        raise EvolutionError("invalid snapshot operation or roster")
    if parent is not None and parent.identity != identity:
        raise EvolutionError("snapshot Encoder identity changed")
    base = restored_from if operation == "rollback" else parent
    sources = set(base.report["source_closure"]) if base else {identity.encoder_sha256, identity.preprocess_sha256}
    protected = set(base.report["protected_evaluation_sources"]) if base else set()
    groups = {c.cell_id: dict(c.head_source_groups) for c in ordered}
    for cell in ordered:
        learned, held = _source_sets(cell.head.report, groups[cell.cell_id])
        sources.update(learned)
        protected.update(held)
    if router is not None:
        if (router.identity != identity or router.report["cell_bindings"] != bindings
                or _state_digest(router._net) != router.report["trained_tensor_sha256"]):
            raise EvolutionError("new roster requires its bound Router")
        config = router.report["config"]
        check_budget({"inference_cells_per_row": config["top_k"],
                      "inference_cost_units_per_row": config["budget_units"]}, budget)
        learned, held = _source_sets(router.report, router_source_groups)
        sources.update(learned)
        protected.update(held)
    resident = tensor_bytes([c.head._head for c in ordered] + ([router._net] if router else []))
    transition = 2 * parent.report["resident_tensor_bytes"] + 3 * resident if parent else 3 * resident
    check_budget({"cells": len(ordered), "resident_tensor_bytes": resident,
                  "transition_tensor_bytes": transition}, budget)
    if router is None:
        check_budget({"inference_cells_per_row": 1,
                      "inference_cost_units_per_row": ordered[0].cost_units}, budget)
    before = check_sources(sources, identity, withdrawal_provider,
                           base.report["withdrawal_view"] if base else None)
    target = Path(directory)
    target.mkdir(mode=0o700, parents=False, exist_ok=False)
    artifacts = []
    fences = dict(parent.report["cell_generation_fences"]) if parent else {}
    for index, cell in enumerate(ordered):
        artifact = save_head_artifact(cell.head, target / f"head-{index}")
        sources.add(artifact["manifest_sha256"])
        old = next((v for v in (parent.report["heads"] if parent else []) if v["cell_id"] == cell.cell_id), None)
        generation = fences.get(cell.cell_id, 0) + 1
        if operation == "retire" and old:
            generation = old["model_generation"]
        elif operation in ("split", "merge"):
            generation = max(h["model_generation"] for h in parent.report["heads"]) + 1
        fences[cell.cell_id] = generation
        artifacts.append({"cell_id": cell.cell_id, "directory": f"head-{index}",
            "manifest_sha256": artifact["manifest_sha256"], "cost_units": cell.cost_units,
            "model_generation": generation, "source_groups": groups[cell.cell_id]})
    router_artifact = None
    if router is not None:
        saved = save_router_artifact(router, target / "router")
        sources.add(saved["manifest_sha256"])
        router_artifact = {"directory": "router", "manifest_sha256": saved["manifest_sha256"],
                           "source_groups": router_source_groups}
    ancestors = sorted(set(parent.report["ancestor_snapshot_digests"] + [parent.manifest_sha256])) if parent else []
    if len(sources) > MAX_SOURCES or len(protected) > MAX_SOURCES or len(ancestors) > 64:
        raise EvolutionError("snapshot provenance budget exceeded")
    if check_sources(sources, identity, withdrawal_provider, asdict(before)) != before:
        raise EvolutionError("withdrawal view changed while preparing snapshot")
    manifest = {"schema": "hepta.cell-evolution-snapshot.v1", "operation": operation,
        "feature_identity": asdict(identity), "graph_generation": parent.generation + 1 if parent else 1,
        "parent_snapshot_digest": parent.manifest_sha256 if parent else None,
        "restored_snapshot_digest": restored_from.manifest_sha256 if restored_from else None,
        "ancestor_snapshot_digests": ancestors, "cell_generation_fences": fences,
        "heads": artifacts, "router": router_artifact, "cell_bindings": bindings,
        "router_report_sha256": digest(router.report) if router else None,
        "source_closure": sorted(sources), "protected_evaluation_sources": sorted(protected),
        "withdrawal_view": asdict(before), "admitted_budget": asdict(budget),
        "resident_tensor_bytes": resident, "serialization_transition_tensor_reservation": transition,
        "operation_receipt": receipt or {},
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False,
        "scope": "offline_snapshot_only_not_production_CURRENT_or_authenticated_source_ledger"}
    data = _json_bytes(manifest)
    if len(data) > MAX_MANIFEST_BYTES:
        raise EvolutionError("snapshot manifest exceeds byte budget")
    with (target / "snapshot.json").open("xb") as output:
        output.write(data)
    # Adopt the actual saved NPZ, dropping training-only gradients and aliases.
    return load_snapshot(target, expected_manifest_sha256=hashlib.sha256(data).hexdigest(),
                         budget=budget, withdrawal_provider=withdrawal_provider)


def bootstrap_snapshot(cells, router, router_source_groups, directory, budget, withdrawal_provider):
    return _persist_snapshot(cells, router, router_source_groups, directory, budget, withdrawal_provider)


def load_snapshot(directory, *, expected_manifest_sha256, budget, withdrawal_provider):
    manifest = _read_manifest(directory, expected_manifest_sha256)
    if (manifest["schema"] != "hepta.cell-evolution-snapshot.v1" or manifest["authority"] != "DENY_ALL"
            or manifest["mode"] != "SHADOW_ONLY" or manifest["production_activation_allowed"] is not False
            or type(manifest["graph_generation"]) is not int or manifest["graph_generation"] < 1
            or not 1 <= len(manifest["heads"]) <= 2
            or len(manifest["source_closure"]) > MAX_SOURCES
            or any(not _is_digest(s) for s in manifest["source_closure"])):
        raise EvolutionError("invalid snapshot manifest")
    identity = FeatureIdentityV1(**manifest["feature_identity"])
    check_sources(manifest["source_closure"], identity, withdrawal_provider, manifest["withdrawal_view"])
    check_budget({"cells": len(manifest["heads"]), "resident_tensor_bytes": manifest["resident_tensor_bytes"]}, budget)
    cells = []
    for index, record in enumerate(manifest["heads"]):
        if record["directory"] != f"head-{index}":
            raise EvolutionError("invalid Head artifact path")
        head = load_head_artifact(Path(directory) / record["directory"],
            expected_manifest_sha256=record["manifest_sha256"], expected_identity=identity)
        cells.append(RouterCellV1(record["cell_id"], head, record["cost_units"], record["source_groups"]))
    record = manifest["router"]
    if record is not None and record["directory"] != "router":
        raise EvolutionError("invalid Router artifact path")
    router = (load_router_artifact(Path(directory) / "router", expected_manifest_sha256=record["manifest_sha256"],
              expected_identity=identity, cells=cells) if record else None)
    if (len(cells) == 2) != (router is not None):
        raise EvolutionError("snapshot roster/Router shape mismatch")
    snapshot = EvolutionSnapshotV1(directory, expected_manifest_sha256, manifest, cells, router, budget)
    snapshot.require_current(withdrawal_provider)
    return snapshot


def retire_snapshot(parent, cell_id, directory, budget, withdrawal_provider):
    parent.require_current(withdrawal_provider)
    if len(parent.cells) != 2 or cell_id not in {c.cell_id for c in parent.cells}:
        raise EvolutionError("retirement must retain one legal Cell")
    cells = [c for c in parent.cells if c.cell_id != cell_id]
    return _persist_snapshot(cells, None, {}, directory, budget, withdrawal_provider, parent=parent,
        operation="retire", receipt={"retired_cell_ids": [cell_id], "training_head_example_calls": 0})


def rollback_snapshot(current, parent_snapshot, directory, budget, withdrawal_provider):
    if _read_manifest(current.directory, current.manifest_sha256) != current.report:
        raise EvolutionError("current rollback lineage manifest changed")
    if parent_snapshot.manifest_sha256 not in current.report["ancestor_snapshot_digests"]:
        raise EvolutionError("rollback target is not a retained ancestor")
    restored = load_snapshot(parent_snapshot.directory, expected_manifest_sha256=parent_snapshot.manifest_sha256,
                             budget=budget, withdrawal_provider=withdrawal_provider)
    check_sources(restored.report["source_closure"], restored.identity, withdrawal_provider,
                  current.report["withdrawal_view"])
    return _persist_snapshot(restored.cells, restored.router, (restored.report["router"] or {}).get("source_groups", {}),
        directory, budget, withdrawal_provider, parent=current, operation="rollback", restored_from=restored,
        receipt={"reloaded_parent_manifest_sha256": restored.manifest_sha256,
                 "training_head_example_calls": 0, "restored_resident_tensor_bytes": restored.report["resident_tensor_bytes"]})


class OfflineEvolutionOwnerV1:
    """In-process research dispatch only; durable production publication is external."""
    def __init__(self, snapshot, withdrawal_provider):
        snapshot.require_current(withdrawal_provider)
        self._current = snapshot
        self._provider = withdrawal_provider
        self._budget = asdict(snapshot.budget)
        self._lock = threading.RLock()

    @property
    def current(self):
        return self._current

    def commit(self, candidate, *, expected_parent_manifest_sha256, before_publish=None):
        """Validate all owner and optional host fences before publishing the pointer.

        The optional check executes under this owner's lock immediately before
        publication. A host must not report a failed post-publication validation
        while leaving an unacknowledged successor as the current snapshot.
        """
        if before_publish is not None and not callable(before_publish):
            raise EvolutionError("prepublication verifier must be callable")
        with self._lock:
            if (self._current.manifest_sha256 != expected_parent_manifest_sha256
                    or candidate.report["parent_snapshot_digest"] != expected_parent_manifest_sha256
                    or candidate.generation != self._current.generation + 1):
                raise EvolutionError("stale snapshot compare-and-swap")
            if any(value > self._budget[key] for key, value in asdict(candidate.budget).items()):
                raise EvolutionError("candidate raised the owner's fixed budget")
            candidate.require_current(self._provider)
            if before_publish is not None:
                before_publish()
            # A host verifier may re-enter this RLock and publish a competing
            # child. Never let the outer caller overwrite a changed parent.
            if (self._current.manifest_sha256 != expected_parent_manifest_sha256
                    or candidate.generation != self._current.generation + 1):
                raise EvolutionError("stale snapshot compare-and-swap")
            # Recheck after the host hook; it may observe a newer withdrawal cut.
            candidate.require_current(self._provider)
            self._current = candidate

    def predict_task(self, bundle):
        with self._lock:
            return self._current.predict_task(bundle, self._provider)
