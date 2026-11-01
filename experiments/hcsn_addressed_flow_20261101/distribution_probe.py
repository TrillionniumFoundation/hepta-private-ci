"""Prospective, same-weight intervention on state/content association.

Uses the inherited factorized_content switch, not a second model kernel.
The full probability vector remains available in both arms. This probes a
trained model's use of state-conditioned signed content moments; it cannot
establish that a full probability distribution or this architecture is needed.
"""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import torch

from . import data, study
from .analyze import bootstrap
from experiments.hcsn_four_stage_flow_20261031 import models


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SEEDS = (17, 29, 43)
CONDITIONS = ("base", "irregular", "missing", "resample")
INTERVENTIONS = ("intact", "factorized_content")
CANDIDATE_SHA = "4ed955c533a124c968494436e8600956a0b2e65467d2712b2701dea83709d836"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def require(value, message):
    if not value:
        raise ValueError(message)


def sources():
    result = study.source_hashes()
    for path in (Path(__file__), HERE / "analyze.py"):
        result[str(path.resolve().relative_to(ROOT))] = digest(path)
    return result


def candidate_identity(run):
    run = Path(run)
    require(digest(run / "ALL_CHECKPOINTS.json") == CANDIDATE_SHA, "Original fixed candidate required")
    manifest, protocol = read(run / "ALL_CHECKPOINTS.json"), read(run / "PROTOCOL.json")
    training = read(run / "TRAINING_SOURCE.json")
    require(manifest["protocol_sha256"] == digest(run / "PROTOCOL.json") == training["protocol_sha256"]
            and manifest["source_commit"] == training["source_commit"]
            and training["source_hashes"] == protocol["source_hashes"], "Original training identity changed")
    for path, expected in protocol["source_hashes"].items():
        require(digest(ROOT / path) == expected, "Original source changed: " + path)
    selected = [row for row in manifest["fits"] if row["task"] == "dynamics" and row["arm"] == "flow"]
    require(len(selected) == 3 and {r["seed"] for r in selected} == set(SEEDS)
            and all(r["status"] == "completed" for r in selected), "Exactly three completed original Flow fits required")
    identities = {str((run / name).resolve()): digest(run / name)
                  for name in ("ALL_CHECKPOINTS.json", "PROTOCOL.json", "TRAINING_SOURCE.json")}
    for row in selected:
        path = run / row["checkpoint"]
        require(digest(path) == row["checkpoint_sha256"], "Original checkpoint changed")
        identities[str(path.resolve())] = row["checkpoint_sha256"]
    return sorted(selected, key=lambda row: row["seed"]), identities


def load_model(run, row):
    model = study.new_model("dynamics", "flow", row["seed"]).eval()
    model.load_state_dict(torch.load(Path(run) / row["checkpoint"], weights_only=True, map_location="cpu"))
    return model


def development(run, out):
    """Tiny DEV semantics check; trace actual frozen forward locals at projection."""
    rows, identities = candidate_identity(run)
    source = sources()
    lines, first = inspect.getsourcelines(models.ContentModel.forward)
    projection_line = first + next(index for index, line in enumerate(lines)
                                   if "factorized = probability" in line)
    cases = []
    for row in rows:
        model = load_model(run, row)
        for condition in CONDITIONS:
            arrays = data.batch("dynamics", 8, 912301, "dev", condition)
            arguments = [torch.from_numpy(arrays[key]) for key in ("x", "dt", "observed")]
            actual, before = [], []
            hook = model.read.register_forward_pre_hook(lambda module, args: actual.append(args[0].detach().clone()))
            def trace(frame, event, arg):
                if frame.f_code is models.ContentModel.forward.__code__:
                    if event == "line" and frame.f_lineno == projection_line:
                        before.append((frame.f_locals["probability"].detach().clone(),
                                       frame.f_locals["memory"].detach().clone()))
                    return trace
                return None
            try:
                model.intervention = None
                with torch.no_grad():
                    model(*arguments)
                intact = torch.stack(actual, 1)
                actual.clear()
                model.intervention = "factorized_content"
                previous_trace = sys.gettrace()
                try:
                    sys.settrace(trace)
                    with torch.no_grad():
                        model(*arguments)
                finally:
                    sys.settrace(previous_trace)
                altered = torch.stack(actual, 1)
            finally:
                hook.remove()
            offset = models.STATES * models.WIDTH
            require(torch.equal(intact[..., offset:], altered[..., offset:]),
                    "Probability, analytic extra features or current encoding changed")
            require(len(before) == arrays["x"].shape[1], "Projection trace incomplete")
            mass_error, p_error, change = 0., 0., 0.
            local = []
            for step, (probability, memory) in enumerate(before):
                seen = arguments[2][:, step, None, None]
                expected = torch.where(seen, probability[..., None] * memory.sum(1, keepdim=True), memory)
                measured = altered[:, step, :offset].reshape_as(memory)
                require(torch.equal(expected, measured), "Inherited projection differs from stated intervention")
                total_error = (measured.sum(1) - memory.sum(1)).abs()
                tolerance = 2e-6 + 2e-5 * memory.sum(1).abs()
                require(bool((total_error <= tolerance).all()), "Local signed-content totals not preserved within FP32 tolerance")
                require(bool(((probability.sum(-1) - 1).abs() <= 2e-6).all()), "Probability mass drift too large")
                delta = float((measured - memory).abs().max())
                mass_error = max(mass_error, float(total_error.max()))
                p_error = max(p_error, float((probability.sum(-1) - 1).abs().max()))
                change = max(change, delta)
                local.append(dict(step=step, observed=int(seen.sum()), content_total_error=float(total_error.max()),
                                  probability_mass_error=float((probability.sum(-1)-1).abs().max()), change=delta))
            require(change > 1e-5, "Intervention did not alter state/content association")
            cases.append(dict(seed=row["seed"], condition=condition, episodes=8,
                probability_and_nonmemory_read_inputs_bitwise_equal=True, inherited_projection_bitwise_equal=True,
                maximum_local_content_total_error=mass_error, maximum_probability_mass_error=p_error,
                maximum_projection_change=change, local=local))
    require(source == sources() and all(digest(path) == sha for path, sha in identities.items()),
            "Source or original candidate changed during DEV check")
    result = dict(passed=True, scope="DEV semantics only; no accuracy tuning or confirmation input",
        dev_seed=912301, cases=cases, source_hashes=source, candidate_inputs_sha256=identities,
        content_total_tolerance="2e-6 + 2e-5*abs(local preprojection signed-content total)",
        interpretation="Local projection preserves p and per-feature total within FP32 error; later totals can differ because subsequent state-dependent killing sees a changed joint moment")
    write(Path(out) / "DEV_CHECKS.json", result)
    return dict(passed=True, cases=len(cases), receipt_sha256=digest(Path(out) / "DEV_CHECKS.json"))


def freeze(run, out, development_receipt):
    fits, identities = candidate_identity(run)
    dev = read(development_receipt)
    require(dev["passed"] is True and dev["source_hashes"] == sources(), "Passing current-source DEV receipt required")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    plan = dict(schema="hcsn.state.content.probe.v1", source_hashes=sources(),
        original_run=str(Path(run).resolve()), candidate_sha256=CANDIDATE_SHA,
        candidate_inputs_sha256=identities, fits=fits, seeds=list(SEEDS),
        conditions=list(CONDITIONS), interventions=list(INTERVENTIONS),
        confirmation_seed=91301, actual_seed=420091301, episodes=1024, records=24,
        design_origin="Post-v1-result follow-up; intervention and analysis fixed before this new synthetic confirmation draw",
        intervention="Inherited ContentModel.intervention='factorized_content': at observed tokens after propagation and before read, M[s,k] <- p[s]*sum_s M[s,k]; unobserved placeholders unchanged",
        preserved="Same checkpoint/input/clock, full probability vector p, policy, current encoded observation, J/G extras; signed-content total preserved locally up to FP32 roundoff",
        changed="State-to-content association; subsequent state-dependent killed transport can change downstream content totals",
        interpretation="A same-weight trained-model sensitivity probe. Both arms retain full p. Not proof of full-distribution necessity, optimal compression, a retrained comparator, or analytical superiority",
        selection="No retraining, tuning or model selection; all three original main Flow candidates",
        primary_metric="Per-episode mean correctness over eight queries; factorized minus intact",
        secondary_metrics=["all eight queries correct", "first query after jump", "later queries after jump", "resampling maximum logit difference"],
        intervals=dict(method="Paired hierarchical bootstrap of three training seeds and within-seed paired episodes", replicates=2000,
                       seed=991301, descriptive_interval=.95, primary_three_task_family_interval=.9833333333333333),
        multiplicity="Four condition contrasts are descriptive95%; no family-wide significance claim",
        uncertainty="Only three training seeds; degenerate bootstrap intervals are not population certainty",
        cost_scope="Whole confirmation phase CPU includes input generation, both arms, raw saves and bootstrap; per-condition inference timers are nested; external meter covers process imports",
        energy_joules=None, gpu=None, development_receipt=str(Path(development_receipt).resolve()),
        development_receipt_sha256=digest(development_receipt),
        runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__, threads=1, device="cpu"))
    for path in plan["source_hashes"]:
        target = out / "sources" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    write(out / "PLAN.json", plan)
    return dict(plan_sha256=digest(out / "PLAN.json"), source_sha256=digest(__file__), records=24)


def evaluate(out, plan_sha256, source_commit):
    started, cpu = time.perf_counter(), time.process_time()
    out = Path(out)
    require(digest(out / "PLAN.json") == plan_sha256, "Exact remotely frozen PLAN hash required")
    require(len(source_commit or "") == 40 and all(c in "0123456789abcdef" for c in source_commit),
            "Remote source/plan publication commit required")
    plan = read(out / "PLAN.json")
    require(sources() == plan["source_hashes"], "Probe source changed after freeze")
    fits, identities = candidate_identity(plan["original_run"])
    require(fits == plan["fits"] and identities == plan["candidate_inputs_sha256"], "Original weight identity changed")
    require(digest(plan["development_receipt"]) == plan["development_receipt_sha256"], "DEV evidence changed")
    for path, expected in plan["source_hashes"].items():
        require(digest(out / "sources" / path) == expected, "Frozen snapshot changed")
    folder = out / "confirmation"
    folder.mkdir(exist_ok=False)
    write(folder / "SOURCE_FREEZE.json", dict(source_commit=source_commit, plan_sha256=plan_sha256,
        candidate_sha256=CANDIDATE_SHA, source_hashes=sources(), candidate_inputs_sha256=identities))
    records, qualities, logits = [], {}, {}
    for fit in fits:
        model = load_model(plan["original_run"], fit)
        for condition in CONDITIONS:
            arrays = data.batch("dynamics", plan["episodes"], plan["confirmation_seed"], "confirm", condition)
            mask = arrays["y"] >= 0
            require(np.all(mask.sum(-1) == 8), "Eight queries per episode required")
            input_hashes = {name: hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()
                            for name, value in arrays.items()}
            for intervention in INTERVENTIONS:
                model.intervention = None if intervention == "intact" else intervention
                wall0, cpu0 = time.perf_counter(), time.process_time()
                output = study.predict(model, arrays)
                inference_cpu, inference_wall = time.process_time()-cpu0, time.perf_counter()-wall0
                correct = (output.argmax(-1)[mask] == arrays["y"][mask]).reshape(plan["episodes"], 8)
                episode = np.stack((correct.mean(-1), correct.all(-1).astype(float),
                                    correct[:, 4].astype(float), correct[:, 5:].mean(-1)), -1)
                path = folder / f"flow_{fit['seed']}_{intervention}_{condition}.npz"
                np.savez_compressed(path, logits=output, query_logits=output[mask], target=arrays["y"][mask],
                    prediction=output.argmax(-1)[mask], correct=correct,
                    episode_id=np.where(mask)[0], query_position=np.where(mask)[1], episode_metrics=episode)
                row = dict(seed=fit["seed"], intervention=intervention, condition=condition,
                    accuracy=float(episode[:, 0].mean()), all8=float(episode[:, 1].mean()),
                    jump_first=float(episode[:, 2].mean()), jump_later=float(episode[:, 3].mean()),
                    raw_file=path.name, raw_sha256=digest(path), checkpoint_sha256=fit["checkpoint_sha256"],
                    input_sha256=input_hashes, inference_cpu_seconds=inference_cpu, inference_wall_seconds=inference_wall)
                if condition == "base":
                    logits[fit["seed"], intervention] = output
                if condition == "resample":
                    row["resampling_max_abs_logit"] = float(np.max(np.abs(output[:, 1::2] - logits[fit["seed"], intervention])))
                records.append(row)
                qualities[fit["seed"], intervention, condition] = episode
                write(path.with_suffix(".json"), row)
        print(json.dumps(dict(seed=fit["seed"], records=8)), flush=True)
    require(len(records) == plan["records"], "Confirmation incomplete")
    rng = np.random.default_rng(plan["intervals"]["seed"])
    effects = []
    for condition in CONDITIONS:
        differences = np.stack([qualities[seed, "factorized_content", condition] - qualities[seed, "intact", condition]
                                for seed in SEEDS])
        intervals = bootstrap(differences, rng, plan["intervals"])
        effects.append(dict(condition=condition, contrast="factorized_content-intact",
            **dict(zip(("accuracy", "all8", "jump_first", "jump_later"), intervals, strict=True))))
    unchanged = sources() == plan["source_hashes"] and all(digest(path) == expected for path, expected in identities.items())
    require(unchanged and digest(out / "PLAN.json") == plan_sha256, "Source/candidate/plan changed during confirmation")
    summary = dict(schema="hcsn.state.content.probe.result.v1", records=records, effects=effects,
        source_commit=source_commit, plan_sha256=plan_sha256, candidate_sha256=CANDIDATE_SHA,
        source_hashes=plan["source_hashes"], source_and_candidate_unchanged=True,
        interpretation=plan["interpretation"], design_origin=plan["design_origin"],
        uncertainty=plan["uncertainty"], multiplicity=plan["multiplicity"], cost_scope=plan["cost_scope"],
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-started, energy_joules=None, gpu=None)
    write(folder / "SUMMARY.json", summary)
    return dict(records=len(records), effects=effects, source_and_candidate_unchanged=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dev", "freeze", "evaluate"), required=True)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--development-receipt", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.mode == "dev":
        result = development(args.run, args.out)
    elif args.mode == "freeze":
        result = freeze(args.run, args.out, args.development_receipt)
    else:
        result = evaluate(args.out, args.plan_sha256, args.source_commit)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
