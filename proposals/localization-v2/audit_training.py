"""Read retained checkpoints/journals; measure main-fit gradient/update coverage."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import torch


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def real_values(tensor):
    return torch.view_as_real(tensor) if tensor.is_complex() else tensor


def audit(fit_directory):
    root = Path(fit_directory)
    result = json.loads((root / "result.json").read_text())
    if (result.get("schema") != "hcsn-localization-development-fit-v1"
            or result.get("status") != "completed_development_only"
            or result.get("source_before") != result.get("source_after")
            or result.get("source_dependency_files_unchanged") is not True
            or result.get("confirmation_access") is not False):
        raise ValueError("fit did not complete with unchanged development-only sources")
    if (digest(root / "initial.pt") != result["initialization_sha256"]
            or digest(root / "events.jsonl") != result["events_sha256"]):
        raise ValueError("initialization/journal identity mismatch")
    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    for phase, count in (("main", result["main_updates_completed"]),
                         ("diagnostic", result["diagnostic_updates_completed"])):
        expected = Counter(range(1, count + 1))
        for kind in ("update_started", "optimizer_step_started", "optimizer_step_completed"):
            observed = Counter(row["number"] for row in events if row["event"] == kind and row["phase"] == phase)
            if observed != expected:
                raise ValueError("missing/duplicate/unresolved optimizer operation")
    checkpoints = [row for row in events if row["event"] == "epoch_checkpoint"]
    if not checkpoints or events[-1].get("status") != "completed_development_only":
        raise ValueError("no final epoch checkpoint or terminal event")
    final_path = (root / checkpoints[-1]["path"]).resolve()
    if not final_path.is_relative_to(root.resolve()) or digest(final_path) != checkpoints[-1]["sha256"]:
        raise ValueError("checkpoint escaped or changed")
    # weights_only avoids executing arbitrary pickle globals from the artifacts.
    initial = torch.load(root / "initial.pt", map_location="cpu", weights_only=True)
    checkpoint = torch.load(final_path, map_location="cpu", weights_only=True)
    if checkpoint["manifest_sha256"] != result["data_manifest_sha256"]:
        raise ValueError("checkpoint data identity differs from fit")
    active = {row["name"]: row for row in result["capacity"]["parameters"] if row["trainable"]}
    saved_groups, declared_groups = checkpoint["optimizer"]["param_groups"], result["optimizer_groups"]
    if len(saved_groups) != len(declared_groups):
        raise ValueError("optimizer group roster mismatch")
    name_to_id = {}
    for saved, declared in zip(saved_groups, declared_groups):
        if (saved["lr"] != declared["lr"] or saved["weight_decay"] != declared["weight_decay"]
                or len(saved["params"]) != len(declared["parameter_names"])):
            raise ValueError("official optimizer group changed")
        for name, index in zip(declared["parameter_names"], saved["params"]):
            if name in name_to_id or index in name_to_id.values():
                raise ValueError("optimizer parameter duplicated")
            name_to_id[name] = index
    if set(name_to_id) != set(active):
        raise ValueError("optimizer does not cover exactly the trainable parameters")
    rows = []
    for name, record in active.items():
        before, after = real_values(initial[name]), real_values(checkpoint["model"][name])
        state = checkpoint["optimizer"]["state"][name_to_id[name]]
        moment = real_values(state["exp_avg_sq"])
        if (before.shape != after.shape or after.shape != moment.shape or after.numel() != record["real_scalars"]
                or float(state["step"]) != result["main_updates_completed"]
                or not bool(torch.isfinite(after).all()) or not bool(torch.isfinite(moment).all())
                or bool((moment < 0).any())):
            raise ValueError("invalid optimizer step count, moment or parameter shape/value")
        changed, gradient = before != after, moment > 0
        rows.append({"name": name, "real_scalars": after.numel(),
                     "nonzero_gradient_moment_scalars": int(gradient.sum()),
                     "changed_scalars": int(changed.sum()),
                     "changed_with_zero_gradient_moment": int((changed & ~gradient).sum()),
                     "maximum_absolute_change": float((after - before).abs().max())})
    frozen = [row["name"] for row in result["capacity"]["parameters"] if not row["trainable"]]
    if any(not torch.equal(initial[name], checkpoint["model"][name]) for name in frozen):
        raise ValueError("frozen parameter changed")
    orders = [row["episode_order"] for row in events if row["event"] == "epoch_started"]
    return {"schema": "hcsn-localization-update-audit-v1", "status": "audited_retained_main_fit",
            "audit_source_sha256": digest(__file__), "fit_result_sha256": digest(root / "result.json"),
            "initialization_sha256": result["initialization_sha256"], "checkpoint_sha256": digest(final_path),
            "events_sha256": result["events_sha256"], "arm": result["model"]["arm"],
            "width": result["model"]["configuration"]["width"], "parameters": rows,
            "trainable_real_scalars": sum(row["real_scalars"] for row in rows),
            "nonzero_gradient_moment_scalars": sum(row["nonzero_gradient_moment_scalars"] for row in rows),
            "changed_scalars": sum(row["changed_scalars"] for row in rows),
            "changed_with_zero_gradient_moment": sum(row["changed_with_zero_gradient_moment"] for row in rows),
            "main_updates_completed": result["main_updates_completed"],
            "diagnostic_updates_completed": result["diagnostic_updates_completed"],
            "main_label_ids": result["labels_seen_by_main_optimizer"],
            "epoch_orders_sha256": hashlib.sha256(json.dumps(orders).encode()).hexdigest(),
            "frozen_parameters_unchanged": True, "scientific_admission": "HOLD",
            "scope": "Positive retained AdamW second moment witnesses a nonzero main-fit gradient; zero does not prove structural disconnection. Weight-decay-only changes are separate. Scalar identifiability and formal capacity equivalence are not certified.",
            "new_training_runs": 0, "confirmation_access": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    result = audit(args.fit)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
