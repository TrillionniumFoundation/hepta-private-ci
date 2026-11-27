"""Recoverable local publication joining source leases to parameter CAS.

The source write lock spans the short owner activation, never model training or
inference. A durable staged candidate permits recovery of an owner activation
that committed before the source binding transaction did.
"""

from dataclasses import asdict
import json

from service_types import canonical
from training_backend import verify_candidate


def publish(service, lease):
    store, queue, owner = service.store, service.queue, service.owner
    with store.transaction() as db:
        job = queue.check(db, lease)
        if store.metadata(db)["epoch"] != lease.snapshot["epoch"]:
            db.execute("UPDATE jobs SET state='superseded' WHERE id=?", (lease.job_id,))
            return {
                "status": "superseded",
                "job_id": lease.job_id,
                "epoch": lease.snapshot["epoch"],
            }
        if not lease.snapshot["facts"]:
            queue.check(db, lease)
            db.execute("DELETE FROM parameter_binding")
            db.execute("UPDATE jobs SET state='completed' WHERE id=?", (lease.job_id,))
            return {
                "status": "empty",
                "job_id": lease.job_id,
                "epoch": lease.snapshot["epoch"],
            }
        if not job["candidate"]:
            raise ValueError("publication requires a durably staged candidate")
        candidate = json.loads(job["candidate"])
        training = verify_candidate(candidate, lease.snapshot, service.artifacts)
        current = owner.current(store.cell_id, store.scope)
        queue.check(db, lease)
        if (
            current is not None
            and current.manifest_sha256 == candidate["manifest_sha256"]
        ):
            # Recheck actual bytes and live source frontier after a crash, even
            # when the pointer already committed in the separate owner DB.
            active = owner.invoke(
                store.cell_id,
                store.scope,
                service.authority_view,
                lambda selected: selected,
            )
        else:
            parent = current.manifest_sha256 if current else None
            active = owner.activate(
                store.cell_id,
                candidate["directory"],
                candidate["manifest_sha256"],
                scope=store.scope,
                expected_current=parent,
                generation=current.generation + 1 if current else 0,
                provider=service.authority_view,
                allowed_roots=[f["source_digest"] for f in lease.snapshot["facts"]],
                parent_manifest_sha256=parent,
            )
        # Validation/activation may span the deadline. A late owner commit is
        # retained as a staged recovery candidate, never exposed as a binding.
        queue.check(db, lease)
        binding = {
            "epoch": lease.snapshot["epoch"],
            "snapshot_digest": lease.snapshot["digest"],
            "scope": store.scope,
            "cell_id": store.cell_id,
            "role": store.role,
            "active": asdict(active),
            "catalog_path": candidate["catalog_path"],
            "catalog_sha256": candidate["catalog_sha256"],
        }
        db.execute(
            "INSERT OR REPLACE INTO parameter_binding VALUES (1,?)",
            (canonical(binding).decode(),),
        )
        db.execute(
            "UPDATE jobs SET state='completed',error=NULL WHERE id=?", (lease.job_id,)
        )
        return {
            "status": "published",
            "job_id": lease.job_id,
            "epoch": binding["epoch"],
            "manifest_sha256": active.manifest_sha256,
            "directory": active.directory,
            "catalog_path": binding["catalog_path"],
            "catalog_sha256": binding["catalog_sha256"],
            "generation": active.generation,
            "training": training,
            "durability": service.durability,
        }
