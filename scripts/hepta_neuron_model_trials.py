#!/usr/bin/env python3
"""Offline, shadow-only Hepta Neuron model comparison. Never selects an artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = "hepta.neuron.model-trial.v1"
SPLITS = ("train", "calibration", "holdout", "future_1", "future_2")
EVAL_SPLITS = SPLITS[2:]
# Preregistered, deterministic temperature candidates; fit only by the evaluator
# using labeled in-domain CALIBRATION rows. Holdout/future labels are never fitted.
TEMPERATURE_GRID_V1 = (0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0)
TEMPERATURE_EPSILON_V1 = 1e-6
ARMS = {
    "decisions": ("laya", "typed"),
    "multilingual": ("laya", "multilingual"),
    "heads": ("linear", "mlp", "swiglu"),
}
MODEL_IDS = {
    "laya": "convaiinnovations/laya",
    "typed": "convaiinnovations/laya-typed-decisions",
    "multilingual": "convaiinnovations/laya-multilingual",
}
Q24 = 1 << 24


class InvalidTrial(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise InvalidTrial(message)


def is_sha(value, length=64):
    return (
        isinstance(value, str)
        and len(value) == length
        and any(c != "0" for c in value)
        and all(c in "0123456789abcdef" for c in value)
    )


def physical_absolute_directory(path):
    """Reject symlinked roots and ancestors before resolving trusted artifacts."""
    root = Path(path)
    return (
        root.is_absolute()
        and root.is_dir()
        and all(not parent.is_symlink() for parent in (root, *root.parents))
    )


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_tree(root, only_python=False):
    """Bind tokenizer, config, head and encoder files; reject escaping links."""
    root = Path(root).resolve(strict=True)
    h = hashlib.sha256()
    all_paths = list(root.rglob("*"))
    # Reject links including directory symlinks, even when pathlib would not
    # traverse those directories and would silently omit linked model bytes.
    require(not any(path.is_symlink() for path in all_paths), "symlink in artifact")
    paths = sorted(
        x for x in all_paths if x.is_file() and (not only_python or x.suffix == ".py")
    )
    require(bool(paths), "empty model/SDK artifact")
    for path in paths:
        require(
            not path.is_symlink() and path.resolve().is_relative_to(root),
            "symlink in artifact",
        )
        name = path.relative_to(root).as_posix().encode("utf-8")
        h.update(len(name).to_bytes(4, "big") + name)
        h.update(bytes.fromhex(sha_file(path)))
    return h.hexdigest()


def write_new(path, data):
    payload = (
        json.dumps(
            data,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()
    with open(path, "xb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())


def strict_json_loads(data):
    """Reject duplicate keys and non-JSON float literals at trust boundaries."""

    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise InvalidTrial(f"nonfinite JSON literal: {value}")

    def finite_float(value):
        parsed = float(value)
        require(math.isfinite(parsed), "nonfinite JSON number")
        return parsed

    return json.loads(
        data,
        object_pairs_hook=no_duplicates,
        parse_constant=invalid_constant,
        parse_float=finite_float,
    )


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return strict_json_loads(f.read())


def verify_checkout(expected_sha):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    require(
        result.returncode == 0 and result.stdout.strip() == expected_sha,
        "source checkout differs from frozen manifest",
    )


def canonical_jsonl(rows):
    return b"".join(
        (
            json.dumps(
                row,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        for row in rows
    )


def blind_rows(rows, family):
    """Evaluator-only deterministic export: no holdout gold/OOD or future targets.

    This removes labels before the model runner receives the input file. The
    evaluator must retain the complete source file under separate permissions.
    """
    allow = {
        "id",
        "split",
        "source_group",
        "observed_at_ms",
        "language",
        "domain",
        "state",
        "question",
        "option_order",
        "features_q24",
        "target_q24",
    }
    result = []
    for original in rows:
        row = {key: value for key, value in original.items() if key in allow}
        if family == "heads" and row["split"] != "train":
            row.pop("target_q24", None)
        if family != "heads":
            row.pop("target_q24", None)
        result.append(row)
    return result


def load_inputs(manifest_file, dataset_file, role="evaluator"):
    require(role in ("evaluator", "runner"), "invalid dataset access role")
    manifest = read_json(manifest_file)
    require(
        manifest.get("schema") == SCHEMA and manifest.get("family") in ARMS,
        "invalid manifest",
    )
    require(
        is_sha(manifest.get("source_sha"), 40), "source SHA must be a pinned Git commit"
    )
    require(
        is_sha(manifest.get("dataset_sha256"))
        and is_sha(manifest.get("blind_dataset_sha256")),
        "sealed/blinded dataset SHA missing",
    )
    expected = manifest[
        "dataset_sha256" if role == "evaluator" else "blind_dataset_sha256"
    ]
    require(sha_file(dataset_file) == expected, "dataset changed after freezing")
    require(is_sha(manifest.get("host_profile_digest")), "host profile missing")
    require(
        type(manifest.get("parameter_cap")) is int and manifest["parameter_cap"] > 0,
        "parameter cap missing",
    )
    if manifest["family"] == "heads":
        h = manifest.get("head", {})
        require(
            type(h.get("input_dimension")) is int
            and type(h.get("state_width")) is int
            and 1 <= h["input_dimension"] <= 512
            and 5 <= h["state_width"] <= 256,
            "head shape is not within fixed Neuron dimensions",
        )
        expected, _ = parameter_budget(h["input_dimension"], h["state_width"])
        require(
            manifest["parameter_cap"] == expected["linear"],
            "head cap differs from the exact Linear baseline",
        )
    else:
        require(
            type(manifest.get("max_len")) is int
            and manifest["max_len"] == 512
            and is_sha(manifest.get("sdk_tree_sha256"))
            and is_sha(manifest.get("upstream_lock_sha256"))
            and manifest["parameter_cap"] <= 425_000_000,
            "unmatched text context, SDK, upstream lock or oversized model budget",
        )
    rows = []
    ids, source_splits = set(), {}
    with open(dataset_file, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            row = strict_json_loads(raw)
            require(isinstance(row, dict), "invalid row")
            cid, split, group = row.get("id"), row.get("split"), row.get("source_group")
            require(
                isinstance(cid, str) and cid and cid not in ids,
                "duplicate or empty case id",
            )
            require(
                split in SPLITS and isinstance(group, str) and group,
                "missing split/source group",
            )
            require(
                group not in source_splits or source_splits[group] == split,
                "source group leaked between splits",
            )
            source_splits[group] = split
            ids.add(cid)
            require(
                type(row.get("observed_at_ms")) is int and row["observed_at_ms"] > 0,
                "missing event observation timestamp",
            )
            if manifest["family"] == "heads":
                h = manifest.get("head", {})
                d, w = h.get("input_dimension"), h.get("state_width")
                require(
                    type(d) is int
                    and 1 <= d <= 512
                    and type(w) is int
                    and 5 <= w <= 256
                    and is_sha(h.get("encoder_digest")),
                    "invalid head dimensions",
                )
                fields = [("features_q24", d)]
                if role == "evaluator" or split == "train":
                    fields.append(("target_q24", 2 * w))
                else:
                    require(
                        "target_q24" not in row,
                        "sealed evaluation targets leaked to runner",
                    )
                for field, size in fields:
                    values = row.get(field)
                    require(
                        isinstance(values, list)
                        and len(values) == size
                        and all(type(v) is int and abs(v) <= 8 * Q24 for v in values),
                        f"invalid {field} for {cid}",
                    )
            else:
                q = row.get("question", {})
                require(
                    isinstance(row.get("state"), (str, dict, list))
                    and isinstance(q, dict)
                    and q.get("type") == "choice"
                    and isinstance(q.get("instructions"), str)
                    and isinstance(q.get("criteria"), dict)
                    and 2 <= len(q["criteria"]) <= 20
                    and all(isinstance(v, str) for v in q["criteria"].values())
                    and (
                        row.get("gold") in q["criteria"]
                        if role == "evaluator"
                        else "gold" not in row
                    ),
                    "invalid or exposed choice label",
                )
                order = row.get("option_order")
                require(
                    isinstance(order, list)
                    and len(order) == len(q["criteria"])
                    and all(isinstance(k, str) for k in order)
                    and len(set(order)) == len(order)
                    and set(order) == set(q["criteria"]),
                    "explicit choice order missing or differs from option set",
                )
                require(
                    isinstance(row.get("language"), str)
                    and row["language"]
                    and isinstance(row.get("domain"), str)
                    and row["domain"]
                    and (
                        type(row.get("is_ood")) is bool
                        if role == "evaluator"
                        else "is_ood" not in row
                    ),
                    "missing cohort/OOD facts or exposed OOD label",
                )
            rows.append(row)
    require(
        bool(rows) and all(any(r["split"] == s for r in rows) for s in SPLITS),
        "train/calibration/holdout/two future windows are required",
    )
    if manifest["family"] == "multilingual":
        require(
            all(
                {"en", "zh", "cross"}
                <= {r["language"] for r in rows if r["split"] == split}
                for split in EVAL_SPLITS
            ),
            "each window needs English, Chinese and cross-lingual tasks",
        )
    if manifest["family"] != "heads" and role == "evaluator":
        require(
            all(
                any(r["is_ood"] for r in rows if r["split"] == split)
                for split in EVAL_SPLITS
            ),
            "each evaluation window needs real held-out OOD cases",
        )
    # A future window must be observed after the earlier window, not merely relabeled.
    maxima = {
        s: max(r["observed_at_ms"] for r in rows if r["split"] == s) for s in SPLITS
    }
    minima = {
        s: min(r["observed_at_ms"] for r in rows if r["split"] == s) for s in SPLITS
    }
    require(
        all(maxima[a] < minima[b] for a, b in zip(SPLITS, SPLITS[1:])),
        "time windows overlap or are out of order",
    )
    if role == "evaluator":
        require(
            hashlib.sha256(
                canonical_jsonl(blind_rows(rows, manifest["family"]))
            ).hexdigest()
            == manifest["blind_dataset_sha256"],
            "blinded dataset is not derived from the sealed evaluator labels",
        )
    else:
        require(
            all(
                set(row)
                <= {
                    "id",
                    "split",
                    "source_group",
                    "observed_at_ms",
                    "language",
                    "domain",
                    "state",
                    "question",
                    "option_order",
                    "features_q24",
                    "target_q24",
                }
                for row in rows
            ),
            "unexpected field in blinded model inputs",
        )
    return manifest, rows


def parameter_budget(d, w):
    out = 2 * w
    cap = d * out + out
    mlp_h = (cap - out) // (d + out + 1)
    swiglu_h = (cap - out) // (2 * d + out + 2)
    require(mlp_h > 0 and swiglu_h > 0, "dimensions too small for matched heads")
    return {
        "linear": cap,
        "mlp": mlp_h * (d + out + 1) + out,
        "swiglu": swiglu_h * (2 * d + out + 2) + out,
    }, {"mlp": mlp_h, "swiglu": swiglu_h}


def peak_rss_bytes():
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def hardware():
    return {
        "system": platform.platform(),
        "python": sys.version.split()[0],
        "pid": os.getpid(),
        "monotonic_clock": "perf_counter_ns",
    }


def run_laya(manifest, rows, arm, artifact_dir, weights_file, device, sdk_digest):
    require(arm in MODEL_IDS and arm in ARMS[manifest["family"]], "wrong Laya arm")
    model = manifest.get("models", {}).get(arm, {})
    require(
        model.get("model_id") == MODEL_IDS[arm] and is_sha(model.get("revision"), 40),
        "unpinned model identity/revision",
    )
    require(
        is_sha(model.get("weights_sha256"))
        and is_sha(model.get("artifact_tree_sha256"))
        and is_sha(sdk_digest)
        and sdk_digest == manifest.get("sdk_tree_sha256"),
        "weight/artifact/SDK pin absent or not frozen in manifest",
    )
    require(
        physical_absolute_directory(artifact_dir),
        "model artifact requires an absolute, physical directory with no linked ancestors",
    )
    root = Path(artifact_dir).resolve(strict=True)
    weight = (root / weights_file).resolve(strict=True)
    require(
        weight.is_relative_to(root)
        and weight.is_file()
        and weight.name.endswith(".safetensors"),
        "weights must be contained safetensors",
    )
    require(sha_file(weight) == model["weights_sha256"], "model weight bytes mismatch")
    require(
        sha_tree(root) == model["artifact_tree_sha256"], "model artifact tree mismatch"
    )
    require(
        (root / "encoder" / "config.json").is_file() and (root / "tokenizer").is_dir(),
        "complete offline encoder/tokenizer must be present",
    )
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import laya  # optional: physically installed on the target host
    import torch

    require(
        sha_tree(Path(laya.__file__).parent, only_python=True) == sdk_digest,
        "Laya installed SDK tree does not match pin",
    )
    agent = laya.load(str(root), device=device)
    nparams = sum(p.numel() for p in agent.model.parameters())
    require(nparams <= manifest["parameter_cap"], "actual model exceeds size cap")
    require(str(agent.device) == device, "unexpected physical model device")
    # Shared text, option ordering and max_len; different tokenizers still reported separately.
    max_len = manifest.get("max_len")
    require(type(max_len) is int and max_len == 512, "must use common 512-token cap")
    require(
        type(agent.cfg.get("max_len")) is int and agent.cfg["max_len"] >= max_len,
        "model cannot support common context cap",
    )
    native_context = agent.cfg["max_len"]
    agent.cfg["max_len"] = max_len
    native_head = agent.cfg.get("head_max_len", 192)
    require(
        type(native_head) is int and native_head >= 192, "incompatible option budget"
    )
    agent.cfg["head_max_len"] = 192
    observations = []
    for row in rows:
        if row["split"] not in ("calibration", *EVAL_SPLITS):
            continue
        start = time.perf_counter_ns()
        # Explicit order is immutable across canonical JSON and independent
        # scorer serialization; never infer choice index from JSON key order.
        question = dict(row["question"])
        question["criteria"] = {k: question["criteria"][k] for k in row["option_order"]}
        result = agent.predict(row["state"], {"q": question})
        if str(agent.device) != device:
            raise InvalidTrial("model silently moved device during execution")
        elapsed = (time.perf_counter_ns() - start) / 1e6
        probs = result["answers"]["q"]["probabilities"]
        keys = row["option_order"]
        require(list(probs) == keys, "candidate order was altered")
        p = [probs[k] for k in keys]
        require(
            all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in p)
            and abs(sum(p) - 1) <= 0.001,
            "invalid probability distribution",
        )
        tokens = result["usage"]["input_tokens"]
        require(
            type(tokens) is int and 0 < tokens <= max_len,
            "reported token count exceeds shared budget",
        )
        observations.append(
            {
                "id": row["id"],
                "split": row["split"],
                "probabilities": p,
                "latency_ms": elapsed,
                "input_tokens": tokens,
            }
        )
    require(
        sha_tree(root) == model["artifact_tree_sha256"],
        "model artifact was mutated during execution",
    )
    return (
        nparams,
        model["weights_sha256"],
        observations,
        {
            "torch": torch.__version__,
            "sdk_tree_sha256": sdk_digest,
            "artifact_tree_sha256": model["artifact_tree_sha256"],
            "weights_file": str(weight),
            "native_context": native_context,
            "native_head_budget": native_head,
            "effective_context": max_len,
            "effective_head_budget": 192,
        },
    )


def make_head(torch, arm, d, out, hidden):
    nn = torch.nn
    if arm == "linear":
        return nn.Linear(d, out)
    if arm == "mlp":
        return nn.Sequential(
            nn.Linear(d, hidden["mlp"]), nn.GELU(), nn.Linear(hidden["mlp"], out)
        )
    if arm == "swiglu":

        class SwiGLU(nn.Module):
            def __init__(self):
                super().__init__()
                self.gate = nn.Linear(d, hidden["swiglu"])
                self.value = nn.Linear(d, hidden["swiglu"])
                self.readout = nn.Linear(hidden["swiglu"], out)

            def forward(self, x):
                return self.readout(
                    torch.nn.functional.silu(self.gate(x)) * self.value(x)
                )

        return SwiGLU()
    raise InvalidTrial("unknown head")


def run_head(manifest, rows, arm, device, artifact_out):
    require(arm in ARMS["heads"] and manifest["family"] == "heads", "wrong head arm")
    if device.startswith("cuda"):
        # PyTorch requires this to reproduce CUDA matmul reductions.
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    from safetensors.torch import load_file, save_file

    h = manifest["head"]
    d, w = h["input_dimension"], h["state_width"]
    expected, hidden = parameter_budget(d, w)
    require(
        manifest["parameter_cap"] == expected["linear"],
        "head cap must equal linear baseline",
    )
    require(
        expected[arm] >= 0.99 * manifest["parameter_cap"],
        "candidate too small for matched budget",
    )
    require(
        all(
            type(h.get(k)) is int and h[k] > 0 for k in ("seed", "epochs", "batch_size")
        ),
        "training configuration is incomplete",
    )
    require(
        type(h.get("learning_rate")) in (float, int) and 0 < h["learning_rate"] <= 0.1,
        "invalid learning rate",
    )
    torch.manual_seed(h["seed"])
    torch.use_deterministic_algorithms(True)
    if device.startswith("cuda"):
        torch.cuda.manual_seed_all(h["seed"])
    network = make_head(torch, arm, d, 2 * w, hidden).to(device)
    nparams = sum(p.numel() for p in network.parameters())
    require(
        nparams == expected[arm] and nparams <= manifest["parameter_cap"],
        "parameter mismatch",
    )
    train = [r for r in rows if r["split"] == "train"]
    x = (
        torch.tensor(
            [r["features_q24"] for r in train], dtype=torch.float32, device=device
        )
        / Q24
    )
    y = (
        torch.tensor(
            [r["target_q24"] for r in train], dtype=torch.float32, device=device
        )
        / Q24
    )
    opt = torch.optim.AdamW(
        network.parameters(), lr=h["learning_rate"], weight_decay=0.01
    )
    network.train()
    start_training = time.perf_counter()
    for epoch in range(h["epochs"]):
        generator = torch.Generator().manual_seed(h["seed"] + epoch)
        order = torch.randperm(len(train), generator=generator).tolist()
        for start in range(0, len(order), h["batch_size"]):
            ids = order[start : start + h["batch_size"]]
            opt.zero_grad(set_to_none=True)
            loss = torch.nn.functional.mse_loss(network(x[ids]), y[ids])
            require(bool(torch.isfinite(loss)), "nonfinite training loss")
            loss.backward()
            opt.step()
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    training_seconds = time.perf_counter() - start_training
    network.eval()
    save_path = Path(artifact_out)
    require(
        save_path.is_absolute()
        and not save_path.exists()
        and save_path.suffix == ".safetensors",
        "new absolute safetensors path required",
    )
    save_file(
        {k: v.detach().cpu().contiguous() for k, v in network.state_dict().items()},
        str(save_path),
    )
    weight_sha = sha_file(save_path)
    # Evaluate the exact persisted bytes, not the mutable in-memory trainer.
    loaded = make_head(torch, arm, d, 2 * w, hidden).to(device)
    state = load_file(str(save_path), device="cpu")
    loaded.load_state_dict(state, strict=True)
    loaded.eval()
    require(
        sum(p.numel() for p in loaded.parameters()) == nparams,
        "reloaded head parameter count mismatch",
    )
    with torch.no_grad():
        probe = x[0:1]
        require(
            torch.equal(network(probe), loaded(probe)),
            "reloaded head does not reproduce the trained tensor output",
        )
    del network, opt, state
    observations = []
    with torch.no_grad():
        for row in rows:
            if row["split"] not in EVAL_SPLITS:
                continue
            start = time.perf_counter_ns()
            values = (
                torch.tensor(
                    row["features_q24"], dtype=torch.float32, device=device
                ).unsqueeze(0)
                / Q24
            )
            result = loaded(values).clamp(-8, 8)
            if device.startswith("cuda"):
                torch.cuda.synchronize()
            elapsed = (time.perf_counter_ns() - start) / 1e6
            pred = torch.round(result.cpu()[0] * Q24).to(torch.int64).tolist()
            observations.append(
                {
                    "id": row["id"],
                    "split": row["split"],
                    "drive_q24": pred[:w],
                    "prediction_q24": pred[w:],
                    "latency_ms": elapsed,
                }
            )
    require(
        sha_file(save_path) == weight_sha, "head checkpoint changed after inference"
    )
    return (
        nparams,
        weight_sha,
        observations,
        {
            "torch": torch.__version__,
            "training_seconds": training_seconds,
            "optimizer": "AdamW",
            "weight_decay": 0.01,
            "reloaded_checkpoint_sha256": weight_sha,
            "checkpoint_reload_verified": True,
            "forward_executed_from_reloaded_checkpoint": True,
            "artifact_size_bytes": save_path.stat().st_size,
            "head_profile_sha256": hashlib.sha256(
                json.dumps(h, sort_keys=True).encode()
            ).hexdigest(),
        },
    )


def checked_probabilities(values, expected_len):
    require(
        isinstance(values, list)
        and len(values) == expected_len
        and all(
            type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values
        )
        and abs(sum(values) - 1) <= 0.001
        and sum(values) > 0,
        "invalid probabilities",
    )
    return [v / sum(values) for v in values]


def temperature_probabilities(probabilities, temperature):
    """Stable post-hoc scaling of shipped (already rounded) Laya probabilities."""
    p = checked_probabilities(probabilities, len(probabilities))
    require(
        len(p) >= 2
        and type(temperature) in (float, int)
        and math.isfinite(temperature)
        and temperature > 0,
        "invalid temperature",
    )
    logp = [math.log(max(v, TEMPERATURE_EPSILON_V1)) / temperature for v in p]
    offset = max(logp)
    exp = [math.exp(v - offset) for v in logp]
    scale = sum(exp)
    return [v / scale for v in exp]


def fit_temperature_calibration(rows, predictions):
    """Independent evaluator only: never exposes gold to model runners.

    Inference receipts contain the CALIBRATION predictions but NO labels; the
    evaluator joins its own sealed CALIBRATION cases and fits a global T using
    a declared fixed NLL grid. This function MUST NOT be run in a model worker.
    """
    calibration = {r["id"]: r for r in rows if r["split"] == "calibration"}
    observed = {x["id"]: x for x in predictions if x["split"] == "calibration"}
    require(
        len(observed) == len(calibration) and set(observed) == set(calibration),
        "calibration receipt omitted or duplicated cases",
    )
    eligible = []
    for cid, source in calibration.items():
        # Avoid teaching the confidence calibrator that true OOD observations are
        # in-distribution; reserve OOD samples for independent evaluation.
        if source["is_ood"]:
            continue
        keys = source["option_order"]
        probs = checked_probabilities(observed[cid]["probabilities"], len(keys))
        require(observed[cid]["split"] == "calibration", "calibration split drift")
        eligible.append((cid, keys.index(source["gold"]), probs))
    require(eligible, "no in-domain calibration observations")

    def mean_nll(t):
        return statistics.mean(
            -math.log(
                max(temperature_probabilities(p, t)[gold], TEMPERATURE_EPSILON_V1)
            )
            for _, gold, p in eligible
        )

    scored = [(mean_nll(t), abs(math.log(t)), t) for t in TEMPERATURE_GRID_V1]
    loss, _, chosen = min(scored)
    raw = mean_nll(1.0)
    require(math.isfinite(loss) and math.isfinite(raw), "nonfinite calibration result")
    ids = sorted(cid for cid, _, _ in eligible)
    return {
        "temperature": chosen,
        "fit_metric": "categorical_nll",
        "fit_grid_v1": list(TEMPERATURE_GRID_V1),
        "epsilon": TEMPERATURE_EPSILON_V1,
        "in_domain_calibration_count": len(eligible),
        "in_domain_ids_digest": hashlib.sha256(
            canonical_jsonl([{"id": i} for i in ids])
        ).hexdigest(),
        "raw_calibration_nll": raw,
        "fitted_calibration_nll": loss,
        "fitted_from": "calibration_only",
        "holdout_or_future_labels_used_for_fit": False,
    }


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(fraction * len(values)) - 1)]


def manifest_token_cap(family):
    # Current full-model comparison freezes a common 512-token budget.
    require(family in ("decisions", "multilingual"), "not a text task")
    return 512


def metrics(rows, observations, family):
    by_id = {r["id"]: r for r in rows if r["split"] in EVAL_SPLITS}
    require(
        len(observations) == len(by_id)
        and len({x["id"] for x in observations}) == len(by_id),
        "missing or duplicate prediction",
    )
    summary = {}
    for split in EVAL_SPLITS:
        batch = []
        for item in observations:
            require(
                item["id"] in by_id and item["split"] == by_id[item["id"]]["split"],
                "prediction identity/split drift",
            )
            if item["split"] == split:
                batch.append((by_id[item["id"]], item))
        require(bool(batch), "missing evaluation window")
        latencies = [b["latency_ms"] for _, b in batch]
        require(
            all(
                type(t) in (int, float) and math.isfinite(t) and t >= 0
                for t in latencies
            ),
            "invalid latency sample",
        )
        result = {
            "count": len(batch),
            "p50_ms": percentile(latencies, 0.5),
            "p95_ms": percentile(latencies, 0.95),
            "p99_ms": percentile(latencies, 0.99),
        }
        if family != "heads":
            token_counts = [item.get("input_tokens") for _, item in batch]
            if any(x is not None for x in token_counts):
                require(
                    all(
                        type(x) is int and 0 < x <= manifest_token_cap(family)
                        for x in token_counts
                    ),
                    "invalid input tokens",
                )
                result["mean_input_tokens"] = statistics.mean(token_counts)
                result["p99_input_tokens"] = percentile(token_counts, 0.99)
            bs, correct, bins, accepted, ood_count = (
                [],
                [],
                [[] for _ in range(10)],
                0,
                0,
            )
            for source, pred in batch:
                keys = source["option_order"]
                p = checked_probabilities(pred["probabilities"], len(keys))
                label = keys.index(source["gold"])
                bs.append(sum((v - (i == label)) ** 2 for i, v in enumerate(p)))
                choice = max(range(len(p)), key=p.__getitem__)
                win = int(choice == label)
                correct.append(win)
                confidence = max(p)
                bins[min(9, int(confidence * 10))].append((confidence, win))
                if source["is_ood"]:
                    ood_count += 1
                    accepted += int(confidence >= 0.8)
            cohort_scores = {}
            for field in ("language", "domain"):
                labels = sorted({source[field] for source, _ in batch})
                cohort_scores[field] = {
                    label: {
                        "count": sum(source[field] == label for source, _ in batch),
                        "accuracy": statistics.mean(
                            int(
                                max(
                                    range(len(pred["probabilities"])),
                                    key=pred["probabilities"].__getitem__,
                                )
                                == source["option_order"].index(source["gold"])
                            )
                            for source, pred in batch
                            if source[field] == label
                        ),
                    }
                    for label in labels
                }
            result.update(
                {
                    "cohorts": cohort_scores,
                    "accuracy": statistics.mean(correct),
                    "brier_multiclass": statistics.mean(bs),
                    "ece10": sum(
                        len(b)
                        * abs(
                            statistics.mean(x for x, _ in b)
                            - statistics.mean(y for _, y in b)
                        )
                        for b in bins
                        if b
                    )
                    / len(batch),
                    "ood_samples": ood_count,
                    "ood_false_accept_at_0_8": accepted / ood_count
                    if ood_count
                    else None,
                }
            )
        else:
            squares, absolute = [], []
            drive_sq, prediction_sq = [], []
            for source, pred in batch:
                width = len(source["target_q24"]) // 2
                require(
                    len(source["target_q24"]) == 2 * width and width > 0,
                    "invalid paired drive/prediction target",
                )
                for part, gold, errors in (
                    (pred.get("drive_q24"), source["target_q24"][:width], drive_sq),
                    (
                        pred.get("prediction_q24"),
                        source["target_q24"][width:],
                        prediction_sq,
                    ),
                ):
                    require(
                        isinstance(part, list)
                        and len(part) == width
                        and all(type(v) is int and abs(v) <= 8 * Q24 for v in part),
                        "invalid q24 drive/prediction output",
                    )
                    for a, b in zip(part, gold):
                        delta = (a - b) / Q24
                        squares.append(delta * delta)
                        absolute.append(abs(delta))
                        errors.append(delta * delta)
            result.update(
                {
                    "mse": statistics.mean(squares),
                    "mae": statistics.mean(absolute),
                    "drive_mse": statistics.mean(drive_sq),
                    "prediction_mse": statistics.mean(prediction_sq),
                }
            )
        summary[split] = result
    return summary


def compare(manifest, rows, packets, baseline_sha):
    family = manifest["family"]
    require(
        set(packets) == set(ARMS[family]) and is_sha(baseline_sha),
        "complete arms/frozen baseline required",
    )
    baseline_arm = ARMS[family][0]
    require(
        sha_file(packets[baseline_arm]) == baseline_sha,
        "no-change baseline receipt changed",
    )
    receipts = {arm: read_json(file) for arm, file in packets.items()}
    ids = {
        r["id"]
        for r in rows
        if r["split"]
        in (EVAL_SPLITS if family == "heads" else ("calibration", *EVAL_SPLITS))
    }
    results, calibrations, calibrated_results = {}, {}, {}
    for arm, receipt in receipts.items():
        require(
            receipt.get("schema") == SCHEMA
            and receipt.get("family") == family
            and receipt.get("arm") == arm
            and receipt.get("source_sha") == manifest["source_sha"]
            and receipt.get("dataset_sha256") == manifest["dataset_sha256"]
            and receipt.get("blind_dataset_sha256") == manifest["blind_dataset_sha256"]
            and receipt.get("host_profile_digest") == manifest["host_profile_digest"],
            "model/dataset/host identity drift",
        )
        if family != "heads":
            model = manifest.get("models", {}).get(arm, {})
            require(
                receipt.get("runtime", {}).get("upstream_lock_sha256")
                == manifest.get("upstream_lock_sha256"),
                "experiment receipt lost upstream source-lock binding",
            )
            require(
                receipt.get("runtime", {}).get("sdk_tree_sha256")
                == manifest.get("sdk_tree_sha256")
                and receipt.get("model_id") == MODEL_IDS[arm] == model.get("model_id")
                and receipt.get("model_revision") == model.get("revision")
                and receipt.get("weights_sha256") == model.get("weights_sha256")
                and receipt.get("runtime", {}).get("artifact_tree_sha256")
                == model.get("artifact_tree_sha256"),
                "model identity, bytes or revision drift",
            )
        if family == "heads":
            expected_profile = hashlib.sha256(
                json.dumps(manifest["head"], sort_keys=True).encode()
            ).hexdigest()
            runtime = receipt.get("runtime", {})
            require(
                runtime.get("head_profile_sha256") == expected_profile
                and runtime.get("checkpoint_reload_verified") is True
                and runtime.get("forward_executed_from_reloaded_checkpoint") is True
                and runtime.get("reloaded_checkpoint_sha256")
                == receipt.get("weights_sha256")
                and is_sha(receipt.get("weights_sha256")),
                "head encoder/training/reloaded-artifact binding drift",
            )
        require(
            type(receipt.get("parameters")) is int
            and 0 < receipt["parameters"] <= manifest["parameter_cap"],
            "model violates parameter cap",
        )
        if family != "heads":
            minimum, maximum = (
                (315_000_000, 330_000_000)
                if arm == "multilingual"
                else (415_000_000, 425_000_000)
            )
            require(
                minimum <= receipt["parameters"] <= maximum,
                "actual checkpoint size is outside its preregistered approximate family",
            )
        seen = receipt.get("observations")
        require(
            isinstance(seen, list)
            and len(seen) == len(ids)
            and all(isinstance(x, dict) and x.get("id") in ids for x in seen)
            and {x["id"] for x in seen} == ids,
            "different attempted cases across models",
        )
        evaluation = [x for x in seen if x["split"] in EVAL_SPLITS]
        results[arm] = metrics(rows, evaluation, family)
        if family != "heads":
            calibration = fit_temperature_calibration(rows, seen)
            calibrations[arm] = calibration
            scaled = [
                {
                    **x,
                    "probabilities": temperature_probabilities(
                        x["probabilities"], calibration["temperature"]
                    ),
                }
                for x in evaluation
            ]
            calibrated_results[arm] = metrics(rows, scaled, family)
    require(
        len({receipts[a].get("device") for a in ARMS[family]}) == 1,
        "arms used different compute devices",
    )
    if family == "heads":
        params = [receipts[a]["parameters"] for a in ARMS[family]]
        require(
            min(params) >= 0.99 * max(params),
            "head arms not within 1% parameter budget",
        )
    if family != "heads":
        runtime_versions = {
            (
                receipts[a].get("runtime", {}).get("torch"),
                receipts[a].get("runtime", {}).get("sdk_tree_sha256"),
            )
            for a in ARMS[family]
        }
        require(
            len(runtime_versions) == 1, "incomparable model SDK/torch runtime versions"
        )
    if family == "decisions":
        require(
            abs(receipts["laya"]["parameters"] - receipts["typed"]["parameters"])
            <= 0.01 * receipts["laya"]["parameters"],
            "421M comparison has unmatched parameters",
        )
    transitions = {}
    for candidate in ARMS[family][1:]:
        transitions[candidate] = {}
        base = {x["id"]: x for x in receipts[baseline_arm]["observations"]}
        new = {x["id"]: x for x in receipts[candidate]["observations"]}
        for split in EVAL_SPLITS:
            harmed, eligible = 0, 0
            for case in (r for r in rows if r["split"] == split):
                old, fresh = base[case["id"]], new[case["id"]]
                if family == "heads":

                    def error(p):
                        both = p["drive_q24"] + p["prediction_q24"]
                        return sum(
                            (a - b) ** 2 for a, b in zip(both, case["target_q24"])
                        )

                    eligible += 1
                    harmed += int(error(fresh) > error(old))
                else:
                    options = case["option_order"]
                    if (
                        options[
                            max(
                                range(len(options)),
                                key=lambda i: old["probabilities"][i],
                            )
                        ]
                        == case["gold"]
                    ):
                        eligible += 1
                        harmed += int(
                            options[
                                max(
                                    range(len(options)),
                                    key=lambda i: fresh["probabilities"][i],
                                )
                            ]
                            != case["gold"]
                        )
            key = (
                "paired_regression_degradation_rate"
                if family == "heads"
                else "negative_transfer_proxy_rate"
            )
            transitions[candidate][split] = {
                key: harmed / eligible if eligible else None,
                "at_risk_cases": eligible,
            }
    return {
        "schema": SCHEMA,
        "family": family,
        "diagnostic_comparison": True,
        "results": results,
        "calibration": calibrations,
        "calibrated_results": calibrated_results,
        "negative_transfer": transitions,
        "baseline_sha256": baseline_sha,
        "receipt_sha256": {arm: sha_file(path) for arm, path in packets.items()},
        "production_evidence_verified": False,
        "ndu_selection_authorized": False,
        "promotion_authorized": False,
        "blockers": [
            "independent evaluator/holdout signature absent",
            "NDU utility and future-window retention not independently attested",
            "actual target-host deployment/canary and recovery not attested",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "compare", "blind"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--arm", choices=tuple({v for arms in ARMS.values() for v in arms})
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--weights-file", type=Path, default=Path("model.safetensors"))
    parser.add_argument("--sdk-sha256")
    parser.add_argument(
        "--upstream-lock",
        type=Path,
        help="physical model experiments require frozen upstream catalog",
    )
    parser.add_argument("--checkpoint-out", type=Path)
    parser.add_argument(
        "--receipt", action="append", default=[], help="arm=absolute-file-path"
    )
    parser.add_argument("--baseline-sha256")
    args = parser.parse_args()
    try:
        manifest, rows = load_inputs(
            args.manifest,
            args.dataset,
            role="runner" if args.mode == "run" else "evaluator",
        )
        verify_checkout(manifest["source_sha"])
        if manifest["family"] != "heads":
            require(
                args.upstream_lock is not None, "frozen upstream model catalog required"
            )
            from hepta_neuron_artifact_preflight import (
                match_manifest_catalog,
                verify_catalog,
            )

            catalog = verify_catalog(read_json(args.upstream_lock))
            match_manifest_catalog(manifest, catalog, sha_file(args.upstream_lock))
        else:
            require(args.upstream_lock is None, "heads have no upstream Laya catalog")
        if args.mode == "blind":
            data = canonical_jsonl(blind_rows(rows, manifest["family"]))
            require(
                hashlib.sha256(data).hexdigest() == manifest["blind_dataset_sha256"],
                "blinded dataset digest changed",
            )
            with open(args.output, "xb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            return
        if args.mode == "compare":
            require(args.baseline_sha256 is not None, "baseline sha required")
            pairs = [a.split("=", 1) for a in args.receipt]
            require(all(len(p) == 2 for p in pairs), "expected arm=path")
            data = compare(
                manifest, rows, {arm: path for arm, path in pairs}, args.baseline_sha256
            )
        else:
            require(args.arm in ARMS[manifest["family"]], "invalid arm for family")
            started_wall = time.perf_counter()
            started_cpu = time.process_time()
            if manifest["family"] == "heads":
                require(args.checkpoint_out is not None, "head checkpoint-out required")
                parameters, weights, observations, runtime = run_head(
                    manifest, rows, args.arm, args.device, args.checkpoint_out
                )
            else:
                require(
                    args.artifact_dir is not None and args.sdk_sha256 is not None,
                    "pinned local model and SDK required",
                )
                parameters, weights, observations, runtime = run_laya(
                    manifest,
                    rows,
                    args.arm,
                    args.artifact_dir,
                    args.weights_file,
                    args.device,
                    args.sdk_sha256,
                )
            gpu_memory = None
            if args.device.startswith("cuda"):
                import torch

                torch.cuda.synchronize()
                gpu_memory = {
                    "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                    "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                }
            if manifest["family"] != "heads":
                runtime["upstream_lock_sha256"] = manifest["upstream_lock_sha256"]
            data = {
                "schema": SCHEMA,
                "family": manifest["family"],
                "arm": args.arm,
                "model_id": manifest.get("models", {})
                .get(args.arm, {})
                .get("model_id"),
                "model_revision": manifest.get("models", {})
                .get(args.arm, {})
                .get("revision"),
                "device": args.device,
                "source_sha": manifest["source_sha"],
                "dataset_sha256": manifest["dataset_sha256"],
                "blind_dataset_sha256": manifest["blind_dataset_sha256"],
                "host_profile_digest": manifest["host_profile_digest"],
                "parameters": parameters,
                "weights_sha256": weights,
                "runtime": runtime,
                "hardware": hardware(),
                "observations": observations,
                "end_to_end_wall_seconds": time.perf_counter() - started_wall,
                "cpu_seconds": time.process_time() - started_cpu,
                "peak_rss_bytes": peak_rss_bytes(),
                "peak_cuda_memory": gpu_memory,
                # Sequential per-request forward rate, not true backend batch throughput.
                "serial_forward_rate_per_s": len(observations)
                * 1000
                / sum(obs["latency_ms"] for obs in observations)
                if sum(obs["latency_ms"] for obs in observations) > 0
                else None,
                "true_backend_batch_throughput_per_s": None,
                "production_evidence_verified": False,
                "promotion_authorized": False,
            }
        write_new(args.output, data)
    except (
        InvalidTrial,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        ImportError,
    ) as error:
        parser.exit(2, f"blocked: {error}\n")


if __name__ == "__main__":
    main()
