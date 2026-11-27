"""Research source owner, immediate overlay and separately attributed parameters.

This local service owns typed sources. It does not authenticate an external CI
ledger, infer a key from arbitrary language, or claim model-generated answers are
correct. A source read and a parameter generation always have distinct origins.
"""

# Standalone script entry points resolve the existing sibling research modules.
# ruff: noqa: E402

import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
for dependency in ("memory_cell", "memory_cell_catalog"):
    sys.path.insert(0, str(SCRIPTS / dependency))

from metadata_catalog import MetadataCatalog
from parametric_owner import ActiveCell, Frontier, ParametricOwner
from durability import capabilities, create_directory, sync_directory
from parameter_publication import publish
from service_types import LeaseLost, ReadStatus
from source_store import SourceStore
from training_backend import train_candidate
from training_queue import TrainingQueue


class MemoryService:
    """One stable role/cell identity with current-source admission on every read."""

    def __init__(self, root, scope, cell_id="memory", role="semantic"):
        self.root = Path(root).absolute()
        if self.root.is_symlink():
            raise ValueError("memory service root cannot be a symlink")
        self.root = self.root.resolve()
        create_directory(self.root, parents=True, exist_ok=True)
        self.artifacts = self.root / "artifacts"
        if self.artifacts.is_symlink():
            raise ValueError("artifact root cannot be a symlink")
        create_directory(self.artifacts, exist_ok=True)
        self.store = SourceStore(self.root / "sources.sqlite", scope, cell_id, role)
        self.queue = TrainingQueue(self.store)
        self.owner = ParametricOwner(self.root / "parameters.sqlite")
        sync_directory(self.root)
        self.durability = capabilities()

    def write(self, source_id, entity, relation, value, expected_revision=None):
        return self.store.write(source_id, entity, relation, value, expected_revision)

    def correct(self, source_id, value, expected_revision):
        return self.store.correct(source_id, value, expected_revision)

    def revoke(self, source_id, expected_revision):
        return self.store.revoke(source_id, expected_revision)

    def read(self, entity, relation):
        """Read current source facts immediately; this is never parameter recall."""
        return self.store.read(entity, relation)

    def snapshot(self):
        return self.store.snapshot()

    def authority_view(self, scope=None):
        """Return only live authority metadata, suitable for a network provider."""
        if scope is not None and scope != self.store.scope:
            raise ValueError("source authority scope mismatch")
        with self.store.transaction(write=False) as db:
            return Frontier(
                self.store.scope,
                self.store.metadata(db)["epoch"],
                tuple(
                    r[0]
                    for r in db.execute("SELECT root FROM withdrawals ORDER BY root")
                ),
            )

    def parameter_binding(self):
        """Return current version metadata; stale parameter epochs are unavailable."""
        with self.store.transaction(write=False) as db:
            row = db.execute(
                "SELECT value FROM parameter_binding WHERE singleton=1"
            ).fetchone()
            if row is None:
                return None
            binding = json.loads(row[0])
            snapshot = self.store.snapshot_in(db)
            if (binding["scope"], binding["cell_id"], binding["role"]) != (
                self.store.scope,
                self.store.cell_id,
                self.store.role,
            ):
                raise ValueError("parameter binding owner or role mismatch")
            if (binding["epoch"], binding["snapshot_digest"]) != (
                snapshot["epoch"],
                snapshot["digest"],
            ):
                return None
        active = dict(binding["active"])
        active["roots"] = tuple(active["roots"])
        binding["active"] = ActiveCell(**active)
        if (
            self.owner.current(self.store.cell_id, self.store.scope)
            != binding["active"]
        ):
            return None
        return binding

    def invoke_parameter(self, entity, relation, question, reader):
        """Generate raw output only after current typed-key and version admission.

        The caller supplies the typed key and a bounded question. A question is
        not independently parsed or semantically verified by this service.
        Unknown/conflicting/revoked keys never call the decoder. In-flight source
        or version changes suppress the response; they cannot yield stale text.
        """
        if (
            type(question) is not str
            or not question.strip()
            or len(question.encode()) > 4096
            or not callable(reader)
        ):
            raise ValueError("bounded question and parameter reader required")
        before = self.read(entity, relation)
        result = {
            "status": before.status.value,
            "origin": "parameters",
            "response": None,
            "source_epoch": before.source_epoch,
            "source_roots": before.source_roots,
            "manifest_sha256": None,
            "correctness_verified": False,
        }
        if before.status != ReadStatus.ANSWERED:
            return result
        binding = self.parameter_binding()
        if binding is None or binding["epoch"] != before.source_epoch:
            return result | {"status": "unavailable"}

        def provider():
            view = self.authority_view()
            if view.epoch != binding["epoch"]:
                raise ValueError("source epoch changed after parameter binding")
            return view

        def invoke(active, _catalog_question):
            if active != binding["active"]:
                raise ValueError("parameter version changed after source admission")
            return reader(active, question)

        try:
            catalog = MetadataCatalog(
                binding["catalog_path"], binding["catalog_sha256"]
            )
            response = catalog.read(
                self.owner,
                entity=entity,
                relation=relation,
                provider=provider,
                callback=invoke,
            )
            if (
                self.read(entity, relation) != before
                or self.parameter_binding() != binding
            ):
                raise ValueError("source or parameter version changed during inference")
            if response["status"] != "known":
                raise ValueError(
                    "current supported source is absent from bound catalog"
                )
        except (ValueError, OSError) as error:
            return result | {"status": "indeterminate", "reason": str(error)}
        return result | {
            "status": "generated",
            "response": response["response"],
            "manifest_sha256": binding["active"].manifest_sha256,
        }

    def work_once(
        self,
        base_dir,
        *,
        worker_id="local",
        lease_seconds=3600,
        steps=128,
        rank=8,
        seed=2718,
        learning_rate=0.001,
        templates=None,
    ):
        """Claim durable work, train independently, stage and CAS-publish once."""
        lease = self.queue.claim(worker_id, lease_seconds=lease_seconds)
        if lease is None:
            return {"status": "idle"}
        try:
            if (
                lease.candidate is None
                and lease.snapshot["facts"]
                and self.authority_view().epoch == lease.snapshot["epoch"]
            ):
                destination = (
                    self.artifacts
                    / f"job-{lease.job_id}-attempt-{lease.attempt}-{lease.token}"
                )
                candidate = train_candidate(
                    lease.snapshot,
                    destination,
                    base_dir,
                    steps=steps,
                    rank=rank,
                    seed=seed,
                    learning_rate=learning_rate,
                    templates=templates,
                )
                self.queue.stage(lease, candidate)
            return publish(self, lease)
        except Exception as error:
            try:
                self.queue.fail(lease, error)
            except LeaseLost:
                pass
            raise


def read_local(active, question, *, base_dir):
    """Cold-load real decoder callback; only call through live owner admission."""
    from parametric_model import SourceMemoryCell
    from tensor_contract import bounded_read, strict_json
    import torch

    config = strict_json(
        bounded_read(Path(active.directory) / "adapter_config.json", 64 * 1024)
    )
    torch.set_num_threads(2)
    cell = SourceMemoryCell(base_dir, rank=config["r"])
    cell.load(
        active.directory,
        expected_manifest_sha256=active.manifest_sha256,
        scope=active.scope,
        allowed_roots=set(active.roots),
        revoked=set(),
    )
    return cell.generate([question])[0]
