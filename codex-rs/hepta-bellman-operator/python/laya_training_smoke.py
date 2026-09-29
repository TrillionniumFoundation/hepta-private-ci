"""Real frozen-Laya feature -> private scorer -> paired-metric qualification.

This executable owns an isolated smoke model, not a product inference service.
Existing inference preparation/prediction is reused. Labels and logical event
indices are hand-authored synthetic fixtures, not observed user outcomes or a
consumed final holdout. Successful mechanics never establishes task efficacy.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import torch

RS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RS / "hepta-infer-worker-host/python"))
sys.path.insert(0, str(RS / "hepta-intelligence-eval/python"))
from cell_metrics import LabeledChoices, paired_metrics
from cell_head import (HeadBudget, HeadRow, fit_head, head_schema, restore_candidate,
                       state_digest, tensor_bytes)
from laya_binary import _UsageAgent
from laya_retrieval import (FORMAT, RetrievalDriver, checkpoint_identity, digest,
                            encoded, load_pinned)

SCOPE = "qualification.synthetic.head-training"
OBJECTIVE = digest("Select the listed source that explicitly supports the query, else abstain.")
OPTIONS = ("abstain", "source-a", "source-b")
BUDGET_SECONDS = 240


def cases(split: str):
    # These exogenous labels exist before model loading. Synthetic indices do
    # NOT certify future wall-clock outcomes or independent source principals.
    specifications = {
        "train": [
            ("Which source identifies the project named Cedar?", "The project is named Cedar.", "The project is named Birch.", "source-a"),
            ("Which source says Atlas opens on Tuesday?", "Atlas opens on Friday.", "Atlas opens on Tuesday.", "source-b"),
            ("Which source states the price is seven dollars?", "The price is nine dollars.", "The item has a blue label.", "abstain"),
            ("Which source gives the backup time as noon?", "The backup runs at noon.", "The backup runs at midnight.", "source-a"),
            ("Which source identifies the owner as Morgan?", "The owner is Casey.", "The owner is Morgan.", "source-b"),
            ("Which source identifies the room as 410?", "The meeting is online.", "The room is 309.", "abstain"),
            ("Which source says the duration is five minutes?", "The duration is five minutes.", "The duration is ten minutes.", "source-a"),
            ("Which source names the required format as CSV?", "The format is plain text.", "The format is CSV.", "source-b"),
        ],
        "future": [
            ("Which source identifies the project as Hazel?", "The project is Hazel.", "The project is Willow.", "source-a"),
            ("Which source names Avery as coordinator?", "Sam is the coordinator.", "Avery is the coordinator.", "source-b"),
            ("Which source gives a limit of twelve?", "The limit is four.", "The limit is three.", "abstain"),
            ("Which source says the destination is folder Green?", "The destination is folder Red.", "The destination is folder Green.", "source-b"),
        ],
        "retention": [
            ("Which source gives version 8?", "The version is 8.", "The version is 6.", "source-a"),
            ("Which source says the meeting is virtual?", "The meeting is in room 3.", "The meeting is virtual.", "source-b"),
            ("Which source names the package Kite?", "The package is named Stone.", "The package is named Brook.", "abstain"),
            ("Which source gives the color as gold?", "The color is gold.", "The color is silver.", "source-a"),
        ],
    }
    offset = {"train": 100, "future": 200, "retention": 1}[split]
    for i, (query, a, b, gold) in enumerate(specifications[split]):
        row_id = f"{split}.{i}"
        request = {"format": FORMAT, "operation_id": f"qualification.laya.training.{row_id}",
                   "scope": SCOPE, "objective_digest": OBJECTIVE,
                   "snapshot_digest": digest([a, b]), "query": query,
                   "candidates": [{"id": key, "source_digest": hashlib.sha256(text.encode()).hexdigest(),
                                   "excerpt": text} for key, text in zip(OPTIONS[1:], (a, b))]}
        yield row_id, offset + i, request, gold


def capture(agent, driver, request: dict, temperature: float, deadline: float):
    """Observe the actual scorer input, not an approximate encoder reconstruction.

    Qualification only: the caller exclusively owns this preloaded model and
    predictor; neither may be shared with another thread or product consumer.
    Temporary observation hooks are always removed, including inference failure.
    """
    if (str(agent.device) != "cpu" or agent.amp_enabled or agent._fast is not None
            or any(m.training for m in agent.model.modules())):
        raise ValueError("feature probe requires the frozen eager CPU profile")
    head_schema(agent.model.scorer)
    if agent.model._forward_hooks or agent.model._forward_pre_hooks or agent.model.scorer._forward_pre_hooks:
        raise ValueError("unexpected observer or model transformation")
    versions = tuple((id(p), p._version) for p in agent.model.parameters())
    saved, calls = [], [0]
    def feature_hook(_module, arguments):
        x, = arguments
        if (tuple(x.shape[:2]) != (1, len(OPTIONS)) or x.ndim != 3
                or x.dtype != torch.float32 or x.device.type != "cpu" or x.shape[-1] > 2048
                or not bool(torch.isfinite(x).all()) or saved):
            raise ValueError("unexpected real feature tensor")
        saved.append(x[0].detach().clone())
    def count(_module, _arguments):
        calls[0] += 1
    hook = agent.model.scorer.register_forward_pre_hook(feature_hook)
    forward = None
    try:
        forward = agent.model.register_forward_pre_hook(count)
        observation = driver.predict(encoded(request), deadline)
    finally:
        hook.remove()
        if forward is not None:
            forward.remove()
    if calls[0] != 1 or len(saved) != 1 or versions != tuple((id(p), p._version) for p in agent.model.parameters()):
        raise ValueError("real forward count or selected parameter identity changed")
    features = saved[0].clone().contiguous()  # Outside the SDK's inference context.
    with torch.no_grad():
        p = torch.softmax(agent.model.scorer(features).squeeze(-1) / temperature, -1)
    values = tuple(float(x) for x in p)
    if max(abs(values[i] - observation["prediction"][key]) for i, key in enumerate(OPTIONS)) > 1e-4:
        raise ValueError("captured scorer does not reproduce the fixed SDK decoder")
    return features, values, observation


def run(root: Path) -> dict:
    from laya.common import QTYPES, temp_bucket
    torch.set_num_threads(2)
    start = time.monotonic(); deadline = start + BUDGET_SECONDS
    def alive():
        if time.monotonic() >= deadline:
            raise TimeoutError("shared load/encode/train/evaluate budget exhausted")
    pins_path, checkpoint = root / "pins.json", root / "checkpoint"
    if pins_path.stat().st_size > 65536:
        raise ValueError("pin manifest bound")
    pins = json.loads(pins_path.read_bytes())
    agent, bundle = load_pinned(checkpoint, pins)
    load_seconds = time.monotonic() - start
    initial = state_digest(agent.model.scorer)
    all_versions = tuple((id(p), p._version) for p in agent.model.parameters())
    qt = QTYPES["choice"]
    temperature = float(agent.temperature_by_options.get(temp_bucket(qt, len(OPTIONS)), agent.temperature[qt]))
    if not math.isfinite(temperature) or not .01 <= temperature <= 100:
        raise ValueError("unsupported selected temperature")
    observed_agent = _UsageAgent(agent)
    driver = RetrievalDriver(observed_agent, bundle, 512, 192)
    rows, observations, labels, predictions = {}, {}, {}, {}
    feature_seconds = 0.0
    def extract(split):
        nonlocal feature_seconds
        batch, gold_rows, predicted = [], [], {}
        for row_id, logical_time, request, gold in cases(split):
            alive(); before = time.monotonic()
            features, values, observation = capture(agent, driver, request, temperature, deadline)
            usage = observed_agent.usage
            if (not isinstance(usage, dict) or type(usage.get("input_tokens")) is not int
                    or not 1 <= usage["input_tokens"] <= 512 or type(usage.get("output_tokens")) is not int
                    or usage["output_tokens"] != 0):
                raise ValueError("missing actual model token usage")
            feature_seconds += time.monotonic() - before
            target = torch.full((len(OPTIONS),), .1 / (len(OPTIONS) - 1), dtype=torch.float32)
            target[OPTIONS.index(gold)] = .9  # Fixed label smoothing, never the model's own answer.
            outcome = digest(["synthetic-exogenous-label", row_id, gold])
            batch.append(HeadRow(row_id, row_id, logical_time, SCOPE, OBJECTIVE, bundle,
                                 observation["input_digest"], outcome, OPTIONS, features, target))
            gold_rows.append(LabeledChoices(row_id, row_id, outcome, OPTIONS, gold))
            predicted[row_id] = values
            observations[row_id] = {"input_digest": observation["input_digest"],
                                    "receipt_digest": observation["receipt_digest"],
                                    "feature_sha256": hashlib.sha256(tensor_bytes(features)).hexdigest(),
                                    "actual_input_tokens": usage["input_tokens"], "real_forward_calls": 1}
            alive()
        rows[split], labels[split], predictions[split] = tuple(batch), tuple(gold_rows), predicted
    extract("train")
    fit = fit_head(agent.model.scorer, rows["train"], scope=SCOPE, objective=OBJECTIVE,
                   bundle=bundle, temperature=temperature, budget=HeadBudget(), deadline=deadline)
    if fit.disposition != "candidate" or fit.steps != 16 or fit.delta_norm <= 0:
        raise ValueError("real-weight fixture did not execute a nonzero private parameter update")
    before = time.monotonic()
    restored = restore_candidate(agent.model.scorer, fit, bundle=bundle, scope=SCOPE, objective=OBJECTIVE)
    restore_seconds = time.monotonic() - before
    # Held-out labels/features are not passed into fitting; these real model
    # calls occur after the candidate parameters have been fixed.
    extract("future"); extract("retention")
    if len({r.group_id for batch in rows.values() for r in batch}) != 16:
        raise ValueError("split group overlap")
    if max(r.observed_at_ms for r in rows["train"]) >= min(r.observed_at_ms for r in rows["future"]):
        raise ValueError("synthetic temporal split drift")
    alive(); before = time.monotonic(); metrics = {}
    for split in ("future", "retention"):
        candidate = {}
        with torch.no_grad():
            for row in rows[split]:
                candidate[row.row_id] = tuple(float(p) for p in torch.softmax(
                    restored(row.features).squeeze(-1) / temperature, -1))
        metrics[split] = paired_metrics(labels[split], predictions[split], candidate)
    evaluation_seconds = time.monotonic() - before
    if (state_digest(agent.model.scorer) != initial
            or all_versions != tuple((id(p), p._version) for p in agent.model.parameters())
            or checkpoint_identity(checkpoint, pins) != bundle):
        raise ValueError("selected model or prepared checkpoint changed")
    alive()
    # Preserve candidates as evidence only, never overwrite selected files.
    before = time.monotonic()
    with (root / "candidate-head.safetensors").open("xb") as stream:
        stream.write(fit.payload)
    saved = (root / "candidate-head.safetensors").read_bytes()
    if hashlib.sha256(saved).hexdigest() != fit.payload_sha256:
        raise ValueError("candidate persistence changed bytes")
    persistence_seconds = time.monotonic() - before
    alive()
    manifest = asdict(fit); del manifest["payload"]
    return {"schema": "hepta.laya.scorer-training-smoke.v1", "success": True,
            "source_sha": os.environ.get("SOURCE_SHA"),
            "tested_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "tested_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
            "base_bundle_digest": bundle, "weights_parameters": sum(p.numel() for p in agent.model.parameters()),
            "trainable_candidate_parameters": sum(p.numel() for p in restored.parameters()),
            "real_model_forward_calls": sum(o["real_forward_calls"] for o in observations.values()),
            "actual_input_tokens": sum(o["actual_input_tokens"] for o in observations.values()),
            "features": observations, "fit": manifest, "paired_metrics": metrics,
            "cost_seconds": {"load": load_seconds, "feature_extraction": feature_seconds,
                             "training": fit.elapsed_seconds, "candidate_restore": restore_seconds,
                             "metric_evaluation": evaluation_seconds, "candidate_persistence": persistence_seconds,
                             "total": time.monotonic() - start},
            "total_budget_seconds": BUDGET_SECONDS, "selected_parameters_unchanged": True,
            "synthetic_labels_and_logical_times": True, "observed_memory_bytes": None,
            "production_composition": False, "independent_acceptance": False,
            "held_out_efficacy": False, "ndu_efficacy": False, "artifact_adoption": False,
            "structural_plasticity": False, "external_effects": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    args = parser.parse_args(); root = args.prepared.resolve()
    report = {"schema": "hepta.laya.scorer-training-smoke.v1", "success": False,
              "source_sha": os.environ.get("SOURCE_SHA"), "production_composition": False,
              "held_out_efficacy": False, "independent_acceptance": False}
    try:
        report = run(root)
    except Exception as error:
        report["error_type"] = type(error).__name__
        raise
    finally:
        with (root / "training-report.json").open("xb") as stream:
            stream.write(encoded(report) + b"\n")


if __name__ == "__main__":
    main()
