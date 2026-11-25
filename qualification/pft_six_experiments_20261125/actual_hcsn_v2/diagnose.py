"""Train/dev-only diagnosis of the v1 low scores; test is never generated."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import time
import traceback

from common import (CAPSULE, ScaledReadout, SmallHCSN, ModelConfig, data, data_hash, dump,
                    extract, feature_statistics, fit_ridge, forward, make_model, metrics,
                    np, parameter_summary, ridge_logits, runtime, select, sha, torch, utc,
                    validate_sources)


def gradient_report(model, batch, finite_difference=False):
    part = select(batch, range(4))
    model.zero_grad(set_to_none=True)
    logits, _, _ = forward(model, part)
    loss = torch.nn.functional.cross_entropy(logits[-1], part["y"])
    loss.backward()
    gradients = {name: {"norm": float(p.grad.norm()), "max_abs": float(p.grad.abs().max()),
                        "finite": bool(torch.isfinite(p.grad).all())}
                 for name, p in model.named_parameters() if p.grad is not None}
    checks = []
    if finite_difference:
        for name, param in model.named_parameters():
            if param.grad is None or name not in ("input_drive.weight", "recurrent.weight", "readout.weight", "raw_cost"):
                continue
            index = int(param.grad.abs().argmax())
            analytic = float(param.grad.flatten()[index])
            original = float(param.detach().flatten()[index])
            eps = 1e-5
            losses = []
            with torch.no_grad():
                for sign in (1, -1):
                    param.flatten()[index] = original + sign * eps
                    value = forward(model, part)[0][-1]
                    losses.append(float(torch.nn.functional.cross_entropy(value, part["y"])))
                param.flatten()[index] = original
            numeric = (losses[0] - losses[1]) / (2 * eps)
            checks.append({"parameter": name, "flat_index": index, "analytic": analytic, "finite_difference": numeric,
                           "absolute_error": abs(analytic - numeric),
                           "relative_error": abs(analytic - numeric) / max(1e-9, abs(analytic), abs(numeric)),
                           "epsilon": eps})
    return {"final_only_loss": float(loss.detach()), "groups": gradients, "finite_differences": checks}


@torch.no_grad()
def message_report(model, batch):
    part = select(batch, range(8))
    x = part["x"].to(model.input_drive.weight)
    state = model.initial_state(8, part["margin"][:, None])
    values = []
    half = model.config.neurons // 2
    for tick in range(12):
        message = state.message.to(x)
        rec = torch.nn.functional.linear(message.flatten(1), model.recurrent.weight * model.synaptic_mask)
        drive = torch.nn.functional.pad(model.input_drive(x[tick]), (0, half)) + rec
        mark = torch.nn.functional.pad(model.input_mark(x[tick]), (0, half)) + rec
        values.append({"tick": tick, "drive_abs_max": float(drive.abs().max()),
                       "drive_saturation_fraction_abs_gt3": float((drive.abs() > 3).double().mean()),
                       "mark_saturation_fraction_abs_gt3": float((mark.abs() > 3).double().mean()),
                       "message_channel_std": message.std((0, 2), unbiased=False).tolist(),
                       "receiver_recurrent_std": float(rec[:, half:].std(unbiased=False))})
        _, _, state = model(x[tick:tick + 1], state=state, return_features=True)
    return {"steps": values, "sender_receives_receiver_mask_entries": int(torch.count_nonzero(
        model.synaptic_mask[:half].reshape(half, 3, 2 * half)[:, :, half:])),
        "recurrent_active": int(torch.count_nonzero(model.synaptic_mask))}


def load_old(width, old_root):
    path = (old_root / "run_v1/n16/new_parent.pt" if width == 16 else
            CAPSULE / f"parents/training/n{width}-qvi_full-s1101/checkpoint.pt")
    expected = {8: "dbb2e8385e52e426a1ad4d11320215a788b0069d5dd1fb9df21ab895888892ff",
                16: "db257d6e66939e0279d15fc7f096008d092d85081ef83e5bd4a68ea1e2e054c3",
                32: "0db75cbd98d45f9f8f5b46d180c6050ed63445faa1f1496e0b51b9a78849a19b",
                64: "7f6c9f0760fc7f77f29c1ec61da9fa59f59b716d744de9b376909870924c3746"}[width]
    if sha(path) != expected:
        raise ValueError("Old parent identity mismatch")
    saved = torch.load(path, map_location="cpu", weights_only=True)
    model = SmallHCSN(ModelConfig(**saved["config"]))
    model.load_state_dict(saved["selected_model"])
    return model, expected


def run(args):
    out = Path(args.out)
    out.mkdir(exist_ok=False)
    start = time.perf_counter()
    binding = {"experiment": "actual-hcsn-v2-train-dev-diagnosis-v1", "utc": utc(),
               "source": validate_sources(), "runtime": runtime(),
               "script_sha256": sha(__file__), "common_sha256": sha(Path(__file__).with_name("common.py")),
               "test_created": False, "old_test_read": False, "data_seed": 271}
    dump(out / "PROTOCOL.json", binding)
    train, dev = data("train"), data("dev")
    rows, failures = [], []
    for kind in ("archived", "fresh"):
        for width in (8, 16, 32, 64):
            try:
                parent, parent_sha = load_old(width, Path(args.old_root)) if kind == "archived" else (
                    make_model(width, 1701), None)
                gradient = gradient_report(parent, train, finite_difference=kind == "fresh" and width == 16)
                messages = message_report(parent, train)
                for bank in ("value_risk", "tanh"):
                    model = SmallHCSN(replace(parent.config, feature_bank=bank))
                    model.load_state_dict(parent.state_dict())
                    train_logits, train_features, train_cost = extract(model, train)
                    dev_logits, dev_features, dev_cost = extract(model, dev)
                    x, xd = train_features[-1].numpy(), dev_features[-1].numpy()
                    candidates = []
                    for scaled in (False, True):
                        for penalty in (1e-8, 1e-6, 1e-4, .02):
                            fit = fit_ridge(x, train["y"], penalty, scaled=scaled)
                            candidates.append({"scaled": scaled, "ridge": penalty,
                                "train": metrics(ridge_logits(fit, x), train),
                                "dev": metrics(ridge_logits(fit, xd), dev),
                                "solve_s": fit["solve_s"]})
                    rows.append({"kind": kind, "width": width, "bank": bank, "parent_sha256": parent_sha,
                                 "parameters": parameter_summary(model),
                                 "original_head_train": metrics(train_logits, train),
                                 "original_head_dev": metrics(dev_logits, dev),
                                 "feature_statistics": feature_statistics(x, train["y"]),
                                 "ridge_controls": candidates, "parent_value_risk_gradient": gradient,
                                 "messages": messages, "train_extract": train_cost, "dev_extract": dev_cost})
                    print(json.dumps({"kind": kind, "width": width, "bank": bank,
                        "raw_old_penalty_dev": candidates[3]["dev"]["accuracy"],
                        "scaled_old_penalty_dev": candidates[7]["dev"]["accuracy"],
                        "best_scaled_dev": max(r["dev"]["accuracy"] for r in candidates if r["scaled"])}), flush=True)
            except Exception as exc:
                failures.append({"kind": kind, "width": width, "error": repr(exc), "traceback": traceback.format_exc()})
    result = {"protocol_sha256": sha(out / "PROTOCOL.json"), "train_sha256": data_hash(train),
              "dev_sha256": data_hash(dev), "rows": rows, "failures": failures,
              "status": "COMPLETED" if len(rows) == 16 and not failures else "PARTIAL_OR_FAILED",
              "wall_s": time.perf_counter() - start, "test_created": False}
    dump(out / "RESULT.json", result)
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--old-root", required=True)
    raise SystemExit(run(parser.parse_args()))
