"""Qualification-only scorer training for the existing Laya feature backend.

Produces an unselected candidate, never CURRENT, an approval or an execution
permit. Product training still requires the ledger's owner-backed materializer;
this utility must not be substituted for that admission boundary.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time


def load_rows(path: Path, expected: str) -> tuple[bytes, list[dict]]:
    if not path.is_absolute() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("invalid bounded qualification dataset")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("dataset bytes differ from the frozen input")
    value = json.loads(raw)
    if set(value) != {"schema", "qualification_only", "rows"}:
        raise ValueError("unknown qualification dataset fields")
    if value["schema"] != "hepta.laya.qualification-rows.v1" or value["qualification_only"] is not True:
        raise ValueError("not an admitted qualification dataset format")
    rows = value["rows"]
    if not isinstance(rows, list) or not 6 <= len(rows) <= 256:
        raise ValueError("qualification requires between 6 and 256 rows")
    seen = set()
    episodes = {}
    times = {split: [] for split in ("train", "calibration", "holdout")}
    for row in rows:
        if set(row) != {"id", "episode", "observed_at", "features_q24", "target", "split"}:
            raise ValueError("unknown or missing qualification row fields")
        if not isinstance(row["id"], str) or not row["id"] or row["id"] in seen:
            raise ValueError("duplicate or missing row identity")
        seen.add(row["id"])
        if not isinstance(row["episode"], str) or not row["episode"]:
            raise ValueError("missing episode identity")
        if row["split"] not in times or type(row["target"]) is not int or row["target"] not in (0, 1):
            raise ValueError("invalid split or observed label")
        if type(row["observed_at"]) is not int or row["observed_at"] <= 0:
            raise ValueError("invalid observation time")
        if episodes.setdefault(row["episode"], row["split"]) != row["split"]:
            raise ValueError("one episode crosses train/calibration/holdout boundaries")
        times[row["split"]].append(row["observed_at"])
    if any(len(values) < 2 for values in times.values()):
        raise ValueError("all three independent folds require at least two rows")
    if not max(times["train"]) < min(times["calibration"]) or not max(times["calibration"]) < min(times["holdout"]):
        raise ValueError("qualification folds are not ordered by observation time")
    return raw, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--base-sha256", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=32)
    args = parser.parse_args()
    if not 1 <= args.steps <= 256 or not args.output.is_absolute() or args.output.exists():
        raise ValueError("training steps must be bounded and output must be a new absolute directory")
    raw, rows = load_rows(args.dataset, args.dataset_sha256)
    if not args.backend.is_absolute():
        raise ValueError("the existing inference backend must be named by an absolute source path")
    spec = importlib.util.spec_from_file_location("hepta_laya_backend", args.backend)
    if spec is None or spec.loader is None:
        raise ValueError("backend source cannot be loaded")
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    for row in rows:
        backend.bounded_features(row["features_q24"])
    started = time.monotonic()
    cell = backend.LayaCell(args.model, args.base_sha256)
    torch = cell.torch
    torch.manual_seed(0)
    cached = []
    for row in rows:
        captured = []
        hook = cell.model.scorer.register_forward_pre_hook(lambda _module, values: captured.append(values[0].detach()))
        try:
            cell.logits(row["features_q24"])
        finally:
            hook.remove()
        if len(captured) != 1:
            raise ValueError("unexpected scorer execution graph")
        cached.append(captured[0].clone())
    features = torch.cat(cached, dim=0)
    labels = torch.tensor([row["target"] for row in rows], dtype=torch.long)
    groups = {split: [i for i, row in enumerate(rows) if row["split"] == split]
              for split in ("train", "calibration", "holdout")}
    scorer = cell.model.scorer
    before = {name: value.detach().clone() for name, value in scorer.state_dict().items()}
    with torch.no_grad():
        frozen_logits = scorer(features).squeeze(-1).float()
    for parameter in scorer.parameters():
        parameter.requires_grad_(True)
    optimizer = torch.optim.AdamW(scorer.parameters(), lr=0.001, weight_decay=0.01)
    losses = []
    for _ in range(args.steps):
        logits = scorer(features[groups["train"]]).squeeze(-1).float()
        loss = torch.nn.functional.cross_entropy(logits, labels[groups["train"]])
        if not torch.isfinite(loss):
            raise ValueError("training produced a non-finite loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(scorer.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
    with torch.no_grad():
        logits = scorer(features).squeeze(-1).float()
        temperature = min((0.5, 1.0, 2.0, 4.0, 8.0), key=lambda value: float(
            torch.nn.functional.cross_entropy(logits[groups["calibration"]] / value, labels[groups["calibration"]])))
        frozen = torch.softmax(frozen_logits / cell.temperature, -1)[:, 1]
        adapted = torch.softmax(logits / temperature, -1)[:, 1]
    changed = [name for name, value in scorer.state_dict().items() if not torch.equal(before[name], value)]
    if not changed or not torch.isfinite(adapted).all():
        raise ValueError("no finite, actual parameter update was produced")
    from safetensors.torch import save_file
    if args.dataset.read_bytes() != raw or backend.file_digest(args.model / "model.safetensors") != args.base_sha256:
        raise ValueError("frozen dataset or base changed before candidate publication")
    args.output.mkdir(mode=0o700)
    weights = args.output / "scorer.safetensors"
    save_file({name: value.detach().contiguous() for name, value in scorer.state_dict().items()}, str(weights))
    metadata = {
        "schema": "hepta.laya.scorer-candidate.v1", "qualification_only": True,
        "base_sha256": args.base_sha256, "base_assets_sha256": cell.base_assets_digest,
        "preprocessor_sha256": backend.digest(backend.canonical(backend.PROFILE)),
        "scorer_sha256": backend.file_digest(weights), "temperature": temperature,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(), "training_steps": args.steps,
        "trainable_parameters": sum(p.numel() for p in scorer.parameters()),
    }
    report = {"qualification_only": True, "selected": False, "independent_acceptance": False,
              "longitudinal_efficacy": False, "dataset_sha256": metadata["dataset_sha256"],
              "training_steps": args.steps, "changed_tensors": changed,
              "trainable_parameters": metadata["trainable_parameters"],
              "first_loss": losses[0], "last_loss": losses[-1],
              "temperature": temperature, "folds": {key: len(value) for key, value in groups.items()},
              "elapsed_seconds": time.monotonic() - started, "peak_memory_bytes": backend.peak_bytes()}
    holdout = groups["holdout"]
    target = labels.float()
    report["holdout_frozen_brier"] = float(((frozen[holdout] - target[holdout]) ** 2).mean())
    report["holdout_candidate_brier"] = float(((adapted[holdout] - target[holdout]) ** 2).mean())
    report["holdout_frozen_probabilities"] = frozen[holdout].tolist()
    report["holdout_candidate_probabilities"] = adapted[holdout].tolist()
    # No re-selection from holdout, no promotion, no overwrite of the base.
    if args.dataset.read_bytes() != raw or backend.file_digest(args.model / "model.safetensors") != args.base_sha256:
        raise ValueError("frozen dataset or base changed during training")
    (args.output / "qualification.json").write_bytes(backend.canonical(report))
    # The manifest is last: an interrupted candidate directory cannot load.
    for path in (weights, args.output / "qualification.json"):
        with path.open("rb") as committed:
            os.fsync(committed.fileno())
    with (args.output / "candidate.json").open("xb") as manifest:
        manifest.write(backend.canonical(metadata))
        manifest.flush()
        os.fsync(manifest.fileno())
    directory = os.open(args.output, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    print(backend.canonical(report).decode())


if __name__ == "__main__":
    main()
