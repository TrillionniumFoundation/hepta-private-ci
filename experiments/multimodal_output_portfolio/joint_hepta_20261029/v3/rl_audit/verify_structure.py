"""Replay retained structural critics and recompute raw decision metrics.

The source protocol remains unchanged. This post-execution audit cannot turn
synthetic outcomes into real future-window evidence or matched-budget gains.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from . import structure as s


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(observed, expected):
    np.testing.assert_equal(np.shape(observed), np.shape(expected))
    np.testing.assert_allclose(observed, expected, atol=2e-12, rtol=2e-12, equal_nan=False)


def nonnegative_integer(value, message):
    require(type(value) is int and value >= 0, message)


def retained_model(row, panel, cfg, observations_sha256):
    """Validate checkpoint geometry and recorded work; do not refit a model."""
    training, family, kind = row["training"], row["family"], row["kind"]
    for axis in ("cpu_ns", "wall_ns"):
        nonnegative_integer(training[axis], "invalid training " + axis)
    expected = {"updates": 0, "trainable_parameters": 0}
    model = None
    if "model" in row:
        require(family in cfg["families"] and kind in cfg["targets"], "model on a reference arm")
        raw = row["model"]
        model = {
            **raw,
            "mean": np.asarray(raw["mean"], dtype=float),
            "scale": np.asarray(raw["scale"], dtype=float),
            "parameters": [np.asarray(p, dtype=float) for p in raw["parameters"]],
        }
        require(
            model["family"] == family and model["kind"] == kind and model["noise"] == panel.noise,
            "model identity",
        )
        d, outputs, width = (panel.dimension, 1 if kind == "value" else panel.dimension, cfg["hidden"])
        shapes = (
            [(d, width), (width,), (width, outputs), (outputs,)]
            if family == "neural"
            else [(1 + d + (d * (d + 1) // 2 if family == "quadratic" else 0), outputs)]
        )
        require(
            [a.shape for a in model["parameters"]] == shapes
            and model["mean"].shape == model["scale"].shape == (outputs,),
            "checkpoint shape mismatch",
        )
        require(
            all(np.isfinite(a).all() for a in (model["mean"], model["scale"], *model["parameters"]))
            and np.all(model["scale"] > 0),
            "invalid checkpoint numeric values",
        )
        require(training["source_observations_sha256"] == observations_sha256, "unequal information")
        require(
            training["parameter_sha256"]
            == s.array_digest(model["mean"], model["scale"], *model["parameters"]),
            "checkpoint identity",
        )
        expected = {
            "updates": cfg["neural_updates"] if family == "neural" else 1,
            "trainable_parameters": sum(p.size for p in model["parameters"]),
            "normalization_statistics": 2 * outputs,
            "outputs": outputs,
            "observations_used": cfg["train_n"] * (1 + 2 * d if kind == "value" else 1),
        }
    else:
        require(family in ("reference", "action_ablation"), "missing fitted model")
    for key, value in expected.items():
        require(type(training[key]) is int and training[key] == value, "fit metadata mismatch: " + key)
    return model


def terminal_mean(x, panel):
    """Closed Gaussian integral, separately evaluated from the retained rows."""
    center = np.linspace(-0.25, 0.45, panel.dimension)
    frequency = np.linspace(0.5, 1, panel.dimension) / np.sqrt(panel.dimension)
    return (
        -np.sum((x - center) ** 2, axis=-1) / (2 * panel.dimension)
        - panel.noise**2 / 2
        + panel.complementarity * x[..., 0] * x[..., 1] / panel.dimension
        + 0.15 * np.exp(-(panel.noise**2) * np.dot(frequency, frequency) / 2) * np.sin(x @ frequency)
    )


def verify_case(case, cfg):
    panel, seed = s.Panel(**case["panel"]), case["seed"]
    require(case["panel"] in cfg["panels"], "panel contract mismatch")
    for section in ("shared_acquisition_and_truth", "whole_case"):
        for axis in ("cpu_ns", "wall_ns"):
            nonnegative_integer(case[section][axis], "invalid " + section + " " + axis)
    data = s.observations(panel, seed, cfg["train_n"], cfg)
    close(case["training_observations"]["states"], data["x"])
    close(case["training_observations"]["outcomes"], data["outcomes"])
    require(
        case["shared_acquisition_and_truth"]["observations_sha256"] == data["sha256"], "observation identity"
    )
    rng = np.random.default_rng(np.random.SeedSequence([seed, 911, panel.dimension]))
    x = rng.uniform(-1.25, 1.25, (cfg["test_n"], panel.dimension))
    noise, reset = (rng.normal(size=x.shape), rng.random(len(x)) < panel.reset_probability)
    close(case["public_test_states"], x)
    close(case["evaluation_noise"], noise)
    close(case["evaluation_reset_success"], reset)
    require(
        case["shared_acquisition_and_truth"]["evaluation_sha256"] == s.array_digest(x, noise, reset),
        "evaluation identity",
    )
    targets, fees, probabilities, names = s.actions(x, panel, cfg)
    require(names == case["action_names"], "action roster")
    expected = (
        probabilities * terminal_mean(targets, panel)
        + (1 - probabilities) * terminal_mean(x, panel)[:, None]
        - fees
    )
    targets[:, -1, :] = np.where(reset[:, None], 0, x)
    realized = s.quality(targets + panel.noise * noise[:, None, :], panel)
    fixed = int(np.argmax(s.action_values(data["x"], panel, cfg)[0].mean(axis=0)))
    require(case["fixed_action"] == fixed, "fixed reference changed")
    roster = [(f, k) for f in cfg["families"] for k in cfg["targets"]] + [
        ("reference", "exact"),
        ("reference", "fixed_known_model"),
        ("action_ablation", "frozen"),
    ]
    require([(r["family"], r["kind"]) for r in case["records"]] == roster, "arm roster changed")
    summaries, replays, choices_by_arm = [], 0, {}
    for row in case["records"]:
        kind, family = row["kind"], row["family"]
        if panel.noise == 0 and kind == "z_gradient":
            require(row["status"] == "unidentified", "zero diffusion was silently imputed")
        else:
            require(row["status"] in ("complete", "failed"), "unknown result status")
        if row["status"] != "complete":
            require(isinstance(row["error"], str) and bool(row["error"]), "lost failure reason")
            for axis in ("cpu_ns", "wall_ns"):
                nonnegative_integer(row["failed_" + axis], "lost failure cost")
            continue
        model = retained_model(row, panel, cfg, data["sha256"])
        if model is not None:
            # These are diagnostics on the SAME test states, not an independent
            # calibration partition or a model/threshold fitting operation.
            diagnostics = s.calibration(model, x, panel)
            require(set(row["calibration"]) == set(diagnostics), "diagnostic metric roster")
            for key, value in diagnostics.items():
                if value is None:
                    require(row["calibration"][key] is None, "invalid absent diagnostic")
                else:
                    close(row["calibration"][key], value)
            choices = np.asarray([s.select(model, state, panel, cfg) for state in x])
            replays += len(x)
        else:
            choices = (
                np.argmax(expected, axis=1)
                if kind == "exact"
                else np.full(len(x), fixed if kind == "fixed_known_model" else 0)
            )
        raw, metrics = row["raw"], row["metrics"]
        require(
            isinstance(raw["choices"], list)
            and len(raw["choices"]) == len(x)
            and all(type(v) is int and 0 <= v < len(names) for v in raw["choices"]),
            "invalid action roster",
        )
        np.testing.assert_array_equal(raw["choices"], choices)
        selected = expected[np.arange(len(x)), choices]
        quality = realized[np.arange(len(x)), choices]
        close(raw["expected_net"], selected)
        close(raw["observed_quality"], quality)
        close(raw["fees"], fees[choices])
        for axis in ("cpu_ns", "wall_ns"):
            require(
                len(raw[axis]) == len(x) and all(type(v) is int and v >= 0 for v in raw[axis]),
                "incomplete timing roster",
            )
        net = quality - fees[choices]
        checked_metrics = {
            "expected_net_value": selected.mean(),
            "expected_regret": (expected.max(axis=1) - selected).mean(),
            "expected_quality": (selected + fees[choices]).mean(),
            "observed_quality": quality.mean(),
            "mean_fee": fees[choices].mean(),
            "observed_net_value": net.mean(),
            "observed_net_p05": np.quantile(net, 0.05),
            "stop_no_update_fraction": np.mean(choices == 0),
            "wall_p95_ns": np.quantile(raw["wall_ns"], 0.95),
            "wall_p99_ns": np.quantile(raw["wall_ns"], 0.99),
        }
        require(set(metrics) == set(checked_metrics) | {"inference_cpu_ns"}, "decision metric roster")
        for key, value in checked_metrics.items():
            close(metrics[key], value)
        nonnegative_integer(metrics["inference_cpu_ns"], "invalid CPU total")
        require(metrics["inference_cpu_ns"] == sum(raw["cpu_ns"]), "CPU total mismatch")
        choices_by_arm[(family, kind)] = choices
        summaries.append(
            {
                "arm": family + ":" + kind,
                "expected_net": float(selected.mean()),
                "expected_regret": float((expected.max(axis=1) - selected).mean()),
                "trainable_parameters": row["training"]["trainable_parameters"],
                "train_cpu_ns": row["training"]["cpu_ns"],
                "inference_cpu_ns": sum(raw["cpu_ns"]),
            }
        )
    if panel.noise > 0:
        for family in cfg["families"]:
            direct, z = (
                choices_by_arm.get((family, "direct_gradient")),
                choices_by_arm.get((family, "z_gradient")),
            )
            if direct is not None and z is not None:
                require(np.array_equal(direct, z), "direct/Z rescaling changed an action")
    return summaries, replays


def verify(directory, index_sha256):
    directory = Path(directory)
    payload = (directory / "INDEX.json").read_bytes()
    require(hashlib.sha256(payload).hexdigest() == index_sha256, "independently pinned index mismatch")
    index, cfg = json.loads(payload), s.protocol()
    require(index["formal_roster"] is True and index["protocol"] == cfg, "formal protocol changed")
    roster = {f"{p.name}_{seed}.json" for p in s.panels() for seed in cfg["seeds"]}
    require(
        len(index["case_files"]) == len(roster) and {r["path"] for r in index["case_files"]} == roster,
        "case roster changed",
    )
    require(
        {p.name for p in directory.glob("*.json")} == roster | {"INDEX.json"}, "extra or missing case files"
    )
    total, failed, unidentified, replayed = 0, 0, 0, 0
    groups = defaultdict(list)
    for entry in index["case_files"]:
        raw = (directory / entry["path"]).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == entry["sha256"], "case content mismatch")
        case = json.loads(raw)
        require(entry["path"] == f"{case['panel']['name']}_{case['seed']}.json", "case identity mismatch")
        rows, count = verify_case(case, cfg)
        replayed += count
        for row in rows:
            groups[(case["panel"]["name"], row["arm"])].append(row)
        total += len(case["records"])
        failed += sum(r["status"] == "failed" for r in case["records"])
        unidentified += sum(r["status"] == "unidentified" for r in case["records"])
    require(
        (total, failed, unidentified)
        == (index["record_count"], index["failed_count"], index["unidentified_count"]),
        "summary count mismatch",
    )
    summary = []
    for (panel, arm), rows in sorted(groups.items()):
        summary.append(
            {
                "panel": panel,
                "arm": arm,
                "fit_seeds": len(rows),
                **{k: float(np.mean([r[k] for r in rows])) for k in rows[0] if k != "arm"},
            }
        )
    return {
        "schema": "hepta.structure-retained-replay.v1",
        "index_sha256": index_sha256,
        "cases": len(roster),
        "records": total,
        "failed": failed,
        "unidentified": unidentified,
        "retained_model_decisions_replayed": replayed,
        "panel_arm_summary": summary,
        "scientific_benefit_qualified": False,
        "independent_real_future_window": False,
        "scope": "post-execution descriptive replay; no pooled independent sample count or confidence intervals",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--index-sha256", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.directory, args.index_sha256), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    )
