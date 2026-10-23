"""A long-running worker with its own checkpoint store, owner, and TCP endpoint."""

import os
from pathlib import Path

from network_checkpoints import install, pack
from network_fences import Fences
from parametric_owner import ParametricOwner, _name
from tensor_contract import bounded_read, strict_json
from network_wire import call, endpoint, fields


class Worker:
    def __init__(self, root, node_id, authority, key, model, *, reader=None):
        self.root = Path(root).absolute()
        if self.root.is_symlink() or not _name(node_id):
            raise ValueError("real node root and node identity required")
        endpoint(authority)
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshots = self.root / "checkpoints"
        self.snapshots.mkdir(exist_ok=True)
        if self.snapshots.is_symlink():
            raise ValueError("checkpoint store cannot be a symlink")
        self.node_id, self.authority, self.key = node_id, authority, key
        self.model = str(Path(model).absolute())
        self.owner = ParametricOwner(self.root / "owner.sqlite")
        self.fences = Fences(self.root / "fences.sqlite")
        self.reader = reader or self._read_model

    def observe(self, scope, cell_id):
        snapshot = call(
            self.authority,
            self.key,
            dict(op="snapshot", scope=scope, cell_id=cell_id),
            timeout=10,
        )
        return self.fences.observe(scope, cell_id, snapshot)

    def _read_model(self, active, questions, control):
        from parametric_worker import run

        config = strict_json(
            bounded_read(Path(active.directory) / "adapter_config.json", 64 * 1024)
        )
        return run(
            dict(
                model=self.model,
                snapshot=active.directory,
                manifest_sha256=active.manifest_sha256,
                scope=active.scope,
                allowed_roots=list(active.roots),
                questions=questions,
                rank=config["r"],
                seed=2718,
                control=control,
            )
        )

    def _admit(self, scope, cell_id):
        view, assigned = self.observe(scope, cell_id)
        if assigned is None or assigned["node_id"] != self.node_id:
            raise ValueError("cell is not assigned to this node")

        def provider():
            latest_view, latest_placement = self.observe(scope, cell_id)
            if latest_placement != assigned:
                raise ValueError("placement changed during operation")
            provider.last_view = latest_view
            return latest_view

        provider.last_view = view
        active = self.owner.current(cell_id, scope)
        if active is None or active.manifest_sha256 != assigned["manifest_sha256"]:
            active = self.owner.activate(
                cell_id,
                self.snapshots / assigned["manifest_sha256"],
                assigned["manifest_sha256"],
                scope=scope,
                expected_current=active.manifest_sha256 if active else None,
                generation=active.generation + 1 if active else 0,
                parent_manifest_sha256=active.manifest_sha256 if active else None,
                provider=provider,
                allowed_roots=assigned["roots"],
            )
        if list(active.roots) != assigned["roots"]:
            raise ValueError("placement roots differ from verified checkpoint")
        return view, assigned, provider

    def read(self, scope, cell_id, questions, control):
        if (
            type(questions) is not list
            or not 1 <= len(questions) <= 128
            or any(
                type(q) is not str or not q.strip() or len(q.encode()) > 4096
                for q in questions
            )
            or sum(len(q.encode()) for q in questions) > 96 * 1024
            or control not in ("adapter", "base", "shuffled")
        ):
            raise ValueError(
                "bounded questions and registered research control required"
            )
        view, assigned, provider = self._admit(scope, cell_id)

        def forward(active):
            self.fences.calls(increment=True)
            return self.reader(active, questions, control)

        journal = self.owner.invoke(cell_id, scope, provider, forward)
        return dict(
            node_id=self.node_id,
            pid=os.getpid(),
            placement=assigned,
            frontier_epoch=provider.last_view.epoch,
            journal=journal,
            production_accepted=False,
        )

    def dispatch(self, request):
        if type(request) is not dict:
            raise ValueError("RPC object required")
        operation = request.get("op")
        if operation == "read":
            fields(request, ("op", "scope", "cell_id", "questions", "control"))
            return self.read(
                request["scope"],
                request["cell_id"],
                request["questions"],
                request["control"],
            )
        if operation == "stage":
            fields(request, ("op", "package", "retained_manifest_sha256"))
            return install(
                self.snapshots, request["package"], request["retained_manifest_sha256"]
            )
        if operation == "export":
            fields(request, ("op", "scope", "cell_id"))
            _view, _assigned, provider = self._admit(
                request["scope"], request["cell_id"]
            )
            return self.owner.invoke(
                request["cell_id"],
                request["scope"],
                provider,
                lambda active: pack(
                    active.directory, active.manifest_sha256, active.scope
                ),
            )
        if operation == "status":
            fields(request, ("op",))
            return dict(
                role="worker",
                node_id=self.node_id,
                pid=os.getpid(),
                model_callbacks=self.fences.calls(),
                root=str(self.root),
            )
        raise ValueError("unknown worker operation")
