"""Fresh source-pair execution study on the six recovered full-002 checkpoints.

The generator is frozen. Only continuation and terminal regression heads are
fitted. This is a constructed MNIST task, not chronological future evidence.
The clairvoyant arm is a labeled diagnostic and cannot select a deployed policy.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import resource
import sys
import time

import torch

from .continuation_head import ContinuationHead, DecisionContext, encoder_only, paired_record
from .data import load_corpus, render_tokens
from .forecast import ForecastBackend, ForecastBundle, RidgeHead
from .neural import ACTIONS
from .observer import Recognizer, observe_tensors, read_bundle, write_bundle
from .plan_training import ControlledSnapshot
from .run import case_batch


ARMS = ("encoder_only", "static_quota", "dev_fixed", "mean_head", "finite_plan_search",
        "entropic_head", "clairvoyant_oracle")
PATHS = ((), *((a, "refine_image") for a in ACTIONS))
CORRUPTIONS = ("clean", "occlusion", "missing", "heavy_noise", "wrong_hint", "missing_no_hint")
CPU_TARIFF = 0.01
TARIFF = {"cpu_seconds": CPU_TARIFF, "wall_seconds": 0.0,
          "units": "declared utility per CPU second; not a measured monetary tariff",
          "energy": "unmeasured", "gpu": "not used"}
METADATA_SHA256 = {
    "protocol.json": "b45d60a3dcd4de13493c20be5b8649692163ebe0674b58d8957c3919097e7de5",
    "summary.json": "01cecd970da28561050685d85c2fb5c78422d519f2b39d284d2e03b454e75f73",
    "observer.json": "3c5062afeff0f9cbaff333c48f7899ae486e5eca67f60103bad68e1b12897f7d",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def save_gzip(path, value):
    with gzip.open(path, "wt") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)


def risk_summary(group):
    returns = sorted(row["net_return"] for row in group)
    log_weights = [-2.0 * value for value in returns]
    shift = max(log_weights)
    ce = -(shift + math.log(sum(math.exp(x - shift) for x in log_weights) / len(returns))) / 2.0
    tail_count = max(1, math.ceil(len(returns) * 0.1))
    return {"empirical_ce_gamma2": ce, "bottom_decile_mean_net_return": sum(returns[:tail_count]) / tail_count,
            "utility_below_half_rate": sum(row["utility"] < 0.5 for row in group) / len(group),
            "risk_metrics_scope": "descriptive empirical source-panel metrics; no calibrated risk guarantee"}


def advance(base, state, path):
    for action in path:
        state = base.step(state, action)
    return state


def emit(base, state, batch, observer, output):
    started = time.process_time(), time.perf_counter()
    decoded = base.decode(state)
    paths = write_bundle(output, render_tokens(decoded.token_ids[0]), decoded.image_logits[0].sigmoid())
    pixels, caption, hashes = read_bundle(paths)
    online = {"cpu_seconds": time.process_time() - started[0],
              "wall_seconds": time.perf_counter() - started[1]}
    scoring = time.process_time(), time.perf_counter()
    metrics = observe_tensors(observer, pixels, [caption], batch.target.pixels, batch.target.labels)[0]
    return {"utility": metrics["utility"], "metrics": metrics, "caption": caption,
            "output_sha256": digest(hashes), "output_hashes": hashes, "emission_cost": online,
            "audit_cpu_seconds": time.process_time() - scoring[0],
            "audit_wall_seconds": time.perf_counter() - scoring[1]}


def support_choice(head, backend, state, context, fixed):
    try:
        scores = head.predict(backend, state, context, cost_profile_digest=digest(TARIFF)).tolist()
    except ValueError as error:
        if "outside empirical feature coverage" not in str(error):
            raise
        return fixed, {"support_rejected": True, "fallback": "dev_fixed"}
    index = max(range(4), key=lambda i: scores[i])
    choice = index + 1 if scores[index] > 0 else 0
    return choice, {"support_rejected": False, "scores": scores}


@torch.inference_mode()
def execute(inputs, output, source_sha, fit_pairs=96, dev_pairs=48, test_pairs=96):
    if (len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha)
            or (fit_pairs, dev_pairs, test_pairs) not in ((96, 48, 96), (6, 6, 6))):
        raise ValueError("Immutable source SHA and either the frozen full panel or mechanical smoke required")
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    inputs = Path(inputs); frozen = inputs / "ndu-runs/full-002"
    if any(file_hash(frozen / name) != sha for name, sha in METADATA_SHA256.items()):
        raise ValueError("Recovered metadata differs from the pinned original archive")
    old = json.loads((frozen / "protocol.json").read_text())
    summary = json.loads((frozen / "summary.json").read_text())
    observer_record = json.loads((frozen / "observer.json").read_text())
    total = time.process_time(), time.perf_counter()
    torch.set_num_threads(2); torch.use_deterministic_algorithms(True)
    corpus = load_corpus(inputs / "ndu-data", evaluator_sources=10000)
    if corpus.manifest != old["dataset_manifest"]:
        raise ValueError("Recovered source partition differs from original full-002")
    offset = 120  # full-001 used 0..59; full-002 used 60..119.
    partitions = {"fit": list(range(offset, offset + fit_pairs)),
                  "dev": list(range(offset + fit_pairs, offset + fit_pairs + dev_pairs)),
                  "test": list(range(offset + fit_pairs + dev_pairs, offset + fit_pairs + dev_pairs + test_pairs))}
    if 2 * (offset + fit_pairs + dev_pairs + test_pairs) > len(corpus.splits["test"]):
        raise ValueError("Requested new source panel exceeds frozen test source pool")
    census = {part: [{"index": i, "corruption": CORRUPTIONS[i % 6],
                      "sources": list(corpus.splits["test"].ids[2*i:2*i+2])}
                     for i in indices] for part, indices in partitions.items()}
    used = [{s.rsplit(":", 1)[1] for row in rows for s in row["sources"]} for rows in census.values()]
    old_used = {s.rsplit(":", 1)[1] for rows in old["cases"].values() for row in rows for s in row["source_ids"]}
    if any(a & b for i, a in enumerate(used) for b in used[i+1:]) or any(s & old_used for s in used):
        raise ValueError("New fit/dev/test or recovered evaluation sources overlap")
    models = {f"seed-{seed}-{profile}": frozen / f"seed-{seed}-{profile}.pt"
              for seed in (17, 29, 43) for profile in ("supervised", "terminal_entropic_ndu")}
    model_hashes = {name: file_hash(path) for name, path in models.items()}
    # The original summary binds every model and both independently fitted observers.
    expected_models = summary["checkpoint_files"]
    if set(expected_models) != set(model_hashes):
        raise ValueError("Recovered checkpoint census differs from original summary")
    for name, sha in model_hashes.items():
        if expected_models[name]["snapshot_file_sha256"] != sha:
            raise ValueError("Recovered checkpoint differs from original summary")
    observers = {}
    for kind in ("reward", "audit"):
        path = frozen / (kind + "-observer.pt")
        if file_hash(path) != observer_record["weights_sha256"][kind]:
            raise ValueError("Recovered observer bytes differ from original receipt")
        model = Recognizer().eval().requires_grad_(False)
        model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
        observers[kind] = model
    protocol = {"schema": "hepta.v6.continuation-benchmark.v1", "source_sha": source_sha,
                "registered_before_new_outcomes": True, "census": census, "arms": ARMS,
                "paths": PATHS, "tariff": TARIFF, "models": model_hashes,
                "original_archive_sha256": "ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e",
                "original_source_sha": old["source"]["git_commit"],
                "new_generator_training": False, "temporal_future": False,
                "decision_scope": "one decision over five fixed suffix plans; at most two transitions",
                "context_clock": "head target excludes common encoding; context is fixed for continuation",
                "online_clock": "test row includes encoding, selection, actual transitions and emission",
                "metadata_sha256": METADATA_SHA256,
                "observer_sha256": observer_record["weights_sha256"],
                "risk_reporting": "descriptive gamma=2 CE, bottom-decile mean net return, utility<0.5 rate",
                "fallback": "dev_fixed on empirical support rejection; STOP on nonpositive supported scores",
                "promotion": "no-update; exploratory execution study, no production admission",
                "versions": {"torch": str(torch.__version__), "python": sys.version},
                "source_files": {p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")}}
    save(output / "PROTOCOL.json", protocol)
    rows, fit_reports = [], {}
    context = DecisionContext(16., 4., 0, 2)
    for label, model_path in models.items():
        print(json.dumps({"model": label, "status": "fitting"}), flush=True)
        directory = output / label; directory.mkdir()
        checkpoint = ControlledSnapshot.load(model_path, expected_file_sha256=model_hashes[label])
        base = checkpoint._base
        seed = int(label.split("-")[1])
        width = base.config["hidden"] * 4
        carrier = ForecastBundle(RidgeHead(width, 1), RidgeHead(width, 4), torch.zeros(2), base.fingerprint, ())
        backend = ForecastBackend(base, carrier, label + ":continuation-study")
        fitted_at = time.process_time(), time.perf_counter()
        records, terminal_x, terminal_y, costs = [], [], [], []
        for item in census["fit"]:
            index = item["index"]
            batch = case_batch(corpus, "future", index, item["corruption"])
            _, state = encoder_only(base, batch.observation, noise_seed=seed * 10000 + index)

            def evaluate(candidate, path, pair_seed, measurement):
                slot = PATHS.index(tuple(path))
                result = emit(base, candidate, batch, observers["reward"], directory / "fit" / str(index) / str(slot))
                cost = CPU_TARIFF * (measurement["transition_cpu_seconds"] + result["emission_cost"]["cpu_seconds"])
                terminal_x.append(base.state_features(candidate)[0].double())
                terminal_y.append(result["utility"])
                costs.append({"slot": slot, "cost": cost,
                              "emission_cost": CPU_TARIFF * result["emission_cost"]["cpu_seconds"]})
                return {"utility": result["utility"], "actual_cost": cost, "output_sha256": result["output_sha256"]}

            records.append(paired_record(backend, state, context, source_ids=item["sources"],
                           suffix=("refine_image",), cost_profile_digest=digest(TARIFF),
                           evaluate=evaluate, pair_seed=seed * 10000 + index, gamma=2.0))
        risk_head = ContinuationHead.fit(base, records)
        mean_records = []
        for row in records:
            neutral = {k: v for k, v in row.items() if k != "sha256"}
            neutral.update(gamma=0.0, target="mean_return_difference")
            mean_records.append({**neutral, "sha256": digest(neutral)})
        mean_head = ContinuationHead.fit(base, mean_records)
        terminal = RidgeHead.fit(torch.stack(terminal_x), torch.tensor(terminal_y, dtype=torch.float64))
        typical_emission_cost = [sum(x["emission_cost"] for x in costs if x["slot"] == slot) / fit_pairs
                                 for slot in range(5)]
        save_gzip(directory / "PAIRS.json.gz", records)
        risk_head.save(directory / "entropic-head.json"); mean_head.save(directory / "mean-head.json")
        save(directory / "terminal-head.json", {k: v.tolist() for k, v in terminal.state_dict().items()})
        dev = []
        for item in census["dev"]:
            index = item["index"]
            batch = case_batch(corpus, "future", index, item["corruption"])
            _, state = encoder_only(base, batch.observation, noise_seed=seed * 10000 + index)
            values = []
            for slot, path in enumerate(PATHS):
                before = time.process_time()
                candidate = advance(base, state, path)
                transition = time.process_time() - before
                value = emit(base, candidate, batch, observers["reward"], directory / "dev" / str(index) / str(slot))
                values.append(value["utility"] - CPU_TARIFF * (transition + value["emission_cost"]["cpu_seconds"]))
            dev.append(values)
        means = [sum(row[i] for row in dev) / len(dev) for i in range(5)]
        fixed = max(range(5), key=lambda i: means[i])
        fit_reports[label] = {"fit_pairs": fit_pairs, "dev_pairs": dev_pairs, "fixed_slot": fixed,
                             "dev_mean_net_returns": means, "head_dimension": width + 14,
                             "typical_emission_cost": typical_emission_cost,
                             "cpu_seconds": time.process_time() - fitted_at[0],
                             "wall_seconds": time.perf_counter() - fitted_at[1],
                             "base_snapshot": base.fingerprint, "controlled_snapshot": checkpoint.fingerprint}
        save(output / "FITTING.json", fit_reports)
        for item in census["test"]:
            index = item["index"]
            batch = case_batch(corpus, "future", index, item["corruption"])
            order = list(ARMS); random.Random(seed * 100000 + index).shuffle(order)
            for arm in order:
                begin = time.process_time(), time.perf_counter()
                _, state = encoder_only(base, batch.observation, noise_seed=seed * 10000 + index)
                detail = {}; oracle_scoring_cpu = oracle_scoring_wall = 0.0
                selected_state = None
                if arm == "encoder_only":
                    slot = 0
                elif arm == "static_quota":
                    slot = 3  # refine_text, then refine_image; fixed before dev.
                elif arm == "dev_fixed":
                    slot = fixed
                elif arm in ("mean_head", "entropic_head"):
                    slot, detail = support_choice(mean_head if arm == "mean_head" else risk_head,
                                                 backend, state, context, fixed)
                elif arm == "finite_plan_search":
                    candidates = [advance(base, state, path) for path in PATHS]
                    predicted = [float(terminal(base.state_features(s))[0, 0]) - typical_emission_cost[i]
                                 for i, s in enumerate(candidates)]
                    if not all(math.isfinite(x) for x in predicted):
                        raise ValueError("Nonfinite finite-plan forecast")
                    slot = max(range(5), key=lambda i: predicted[i]); selected_state = candidates[slot]
                    detail = {"forecast": predicted, "complete_fixed_plan_bank": True,
                              "searched_state_reused": True, "exact_for_true_world": False,
                              "ranking_cost": "remaining emission only; all candidate transitions already sunk"}
                elif arm == "clairvoyant_oracle":
                    candidates = []
                    for candidate_slot, path in enumerate(PATHS):
                        candidate = advance(base, state, path)
                        result = emit(base, candidate, batch, observers["audit"],
                                      directory / "oracle" / str(index) / str(candidate_slot))
                        candidates.append((candidate, result["utility"]))
                        oracle_scoring_cpu += result["audit_cpu_seconds"]
                        oracle_scoring_wall += result["audit_wall_seconds"]
                    slot = max(range(5), key=lambda i: candidates[i][1]); selected_state = candidates[slot][0]
                    detail = {"uses_hidden_test_labels": True, "diagnostic_only": True,
                              "upper_bound_scope": "quality in this five-plan bank, not measured net return",
                              "candidate_utilities": [item[1] for item in candidates]}
                else:
                    raise AssertionError("Unregistered policy")
                state = selected_state if selected_state is not None else advance(base, state, PATHS[slot])
                selected = time.process_time(), time.perf_counter()
                result = emit(base, state, batch, observers["audit"], directory / "test" / str(index) / arm)
                online_cpu = selected[0] - begin[0] + result["emission_cost"]["cpu_seconds"]
                online_wall = selected[1] - begin[1] + result["emission_cost"]["wall_seconds"]
                # Oracle label queries are charged inside its selection envelope.
                row = {"model": label, "seed": seed, "training": label.split("-", 2)[2],
                       "source_index": index, "sources": item["sources"], "corruption": item["corruption"],
                       "arm": arm, "slot": slot, "path": PATHS[slot], "detail": detail,
                       "cpu_seconds": online_cpu, "wall_seconds": online_wall,
                       "net_return": result["utility"] - CPU_TARIFF * online_cpu,
                       "oracle_audit_cpu_in_selection": oracle_scoring_cpu,
                       "oracle_audit_wall_in_selection": oracle_scoring_wall, **result}
                rows.append(row)
                with (output / "ROWS.jsonl").open("a") as stream:
                    stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        base.verify_integrity()
        print(json.dumps({"model": label, "status": "complete", "rows": len(rows)}), flush=True)
    expected = len(models) * test_pairs * len(ARMS)
    if {p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")} != protocol["source_files"]:
        raise ValueError("Source bytes changed during the frozen run")
    if len(rows) != expected or len({(r["model"], r["source_index"], r["arm"]) for r in rows}) != expected:
        raise ValueError("Incomplete or duplicated registered execution panel")
    groups = {}
    for label in models:
        for arm in ARMS:
            group = [r for r in rows if r["model"] == label and r["arm"] == arm]
            groups[label + "/" + arm] = {k: sum(r[k] for r in group) / len(group)
                                          for k in ("utility", "net_return", "cpu_seconds", "wall_seconds")}
            groups[label + "/" + arm].update(rows=len(group),
                support_rejections=sum(r["detail"].get("support_rejected", False) for r in group),
                slots=dict(Counter(r["slot"] for r in group)))
            groups[label + "/" + arm].update(risk_summary(group))
    report = {"status": "completed", "source_sha": source_sha, "rows": len(rows), "expected_rows": expected,
              "independent_test_pairs": test_pairs, "fixed_generator_seed_pairs": 3,
              "groups": groups, "fitting": fit_reports, "protocol_sha256": digest(protocol),
              "rows_sha256": file_hash(output / "ROWS.jsonl"), "cpu_seconds": time.process_time() - total[0],
              "wall_seconds": time.perf_counter() - total[1],
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
              "energy": "unmeasured", "decision": "no-update", "production_activated": False,
              "limits": ["constructed MNIST; no temporal future claim", "original generator fits reused",
                         "one continuation decision; no repeated replanning",
                         "Torch generator; this run does not establish Rust parity for its 398-dimensional heads",
                         "same-family imperfect image observers", "shared CPU timings", "declarative CPU tariff",
                         "no new generator-training factorial", "no general optimality or distribution-shift certificate"]}
    save(output / "SUMMARY.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("inputs", "output", "source-sha"):
        parser.add_argument("--" + key, required=True)
    for key, default in (("fit-pairs", 96), ("dev-pairs", 48), ("test-pairs", 96)):
        parser.add_argument("--" + key, type=int, default=default)
    args = parser.parse_args()
    result = execute(args.inputs, args.output, args.source_sha, args.fit_pairs, args.dev_pairs, args.test_pairs)
    print(json.dumps({k: result[k] for k in ("status", "rows", "cpu_seconds", "wall_seconds", "decision")}))
