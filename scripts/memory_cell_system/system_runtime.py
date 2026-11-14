"""Keep the lifecycle coordinator free of resident model and optimizer tensors."""

import json
from pathlib import Path

from model_process import ChildFailure, run_child, run_decoder
from system_common import retain


def train_once(service, model, output, label, steps):
    script = (
        Path(__file__).resolve().parents[1]
        / "memory_cell_service"
        / "training_worker.py"
    )
    arguments = [
        "--root",
        str(service.root),
        "--scope",
        service.store.scope,
        "--cell-id",
        service.store.cell_id,
        "--role",
        service.store.role,
        "--base",
        str(model),
        "--steps",
        str(steps),
        "--rank",
        "8",
        "--seed",
        "2718",
        "--learning-rate",
        "0.001",
        "--once",
    ]
    try:
        receipt = run_child(
            script,
            arguments,
            timeout=900,
            receipt_dir=output / "processes",
            operation="trainer",
        )
    except ChildFailure as error:
        retain(output / f"{label}.process.json", error.receipt)
        raise
    retain(output / f"{label}.process.json", receipt)
    return json.loads(receipt["stdout"])


def read_worker(
    model, snapshot, sha, scope, roots, query, output, label, *, control="adapter"
):
    request = dict(
        model=str(Path(model).resolve()),
        snapshot=str(Path(snapshot).resolve()),
        manifest_sha256=sha,
        scope=scope,
        allowed_roots=sorted(roots),
        questions=query,
        rank=8,
        seed=2718,
        control=control,
    )
    retain(output / f"{label}.request.json", request)
    journal = run_decoder(
        request, cwd=output / "reader-cwd", receipt_dir=output / "processes"
    )
    journal["fresh_process_wall_seconds"] = journal["decoder_process"]["wall_seconds"]
    (output / f"{label}.stderr.txt").write_text(journal["decoder_process"]["stderr"])
    retain(output / f"{label}.journal.json", journal)
    return journal
