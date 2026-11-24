"""Complete trusted-local learner checkpoints and exactly-once holdout claims."""

import os
from pathlib import Path
import random
import tempfile

import numpy as np
import torch


def rng_record(generator):
    numpy_state = np.random.get_state()
    return {"python": random.getstate(), "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
            "generator": generator.get_state(),
            "numpy": [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]]}


def restore_rng(record, generator):
    random.setstate(record["python"])
    torch.set_rng_state(record["torch"].cpu())
    generator.set_state(record["generator"].cpu())
    state = record["numpy"]
    np.random.set_state((state[0], np.asarray(state[1], dtype=np.uint32), *state[2:]))
    if record["cuda"]:
        if not torch.cuda.is_available() or len(record["cuda"]) != torch.cuda.device_count():
            raise ValueError("CUDA RNG topology differs from the saved checkpoint")
        torch.cuda.set_rng_state_all([value.cpu() for value in record["cuda"]])


def save_checkpoint(path, *, identity, model, optimizer, controller, generator, ledger):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    settled_cost = ledger.snapshot()
    with ledger.operation("checkpoint", mandatory=True):
        record = {"schema": "hepta.adaptive.learner-checkpoint.v1", "identity": identity,
                  "model": model.state_dict(), "optimizer": optimizer.state_dict(),
                  "controller": controller, "rng": rng_record(generator),
                  "cost": settled_cost}
        handle = tempfile.NamedTemporaryFile(dir=path.parent, prefix="checkpoint-", delete=False)
        temporary = Path(handle.name)
        try:
            with handle:
                torch.save(record, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def load_checkpoint(path, *, identity, model, optimizer, generator, ledger):
    record = torch.load(path, map_location=next(model.parameters()).device, weights_only=True)
    if record.get("schema") != "hepta.adaptive.learner-checkpoint.v1" or record["identity"] != identity:
        raise ValueError("checkpoint schema or experiment identity mismatch")
    tails = {"0" * 64, *(item["hash"] for item in ledger.records)}
    if record["cost"]["tail"] not in tails or record["cost"]["pending"] is not None:
        raise ValueError("checkpoint has no settled prefix in the cost journal")
    model.load_state_dict(record["model"])
    optimizer.load_state_dict(record["optimizer"])
    restore_rng(record["rng"], generator)
    controller = record["controller"]
    # Recomputed work after this checkpoint remains charged in the durable log.
    controller["recovery_discarded_operations"] = (
        controller.get("recovery_discarded_operations", 0)
        + sum(item["kind"] == "reserve" and item["name"] != "checkpoint"
              for item in ledger.records[record["cost"]["records"]:]))
    return controller


def claim_final_holdout(path, identity):
    """A crash after this exclusive claim makes this evaluation unavailable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(identity + "\n")
        handle.flush()
        os.fsync(handle.fileno())
