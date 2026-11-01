"""Source freeze, all-candidate training, fresh confirmation and raw receipts."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from experiments.hcsn_regeneration_content_20261031 import policy, policy_audit, policy_run
from experiments.hcsn_regeneration_content_20261031.content import Model
from experiments.hcsn_regeneration_content_20261031.content_tasks import multimodal_support
from . import audit, calibration


BASE = Path(__file__).resolve().parent
OLD = BASE.parents[1] / "hcsn_regeneration_content_20261031"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"),
                      default=lambda x: x.tolist() if isinstance(x, np.ndarray) else x.item())


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(encoded(value) + "\n")


class Log:
    """Bounded gzip parts retain complete records without huge repository blobs."""

    def __init__(self, folder, prefix):
        self.folder, self.prefix, self.buffer, self.parts = folder, prefix, [], []

    def add(self, value):
        self.buffer.append(encoded(value) + "\n")
        if len(self.buffer) == 2048:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        pending, self.buffer = [self.buffer], []
        while pending:
            rows = pending.pop(0)
            payload = gzip.compress("".join(rows).encode(), mtime=0)
            if len(payload) >= 500000:
                if len(rows) == 1:
                    raise ValueError("A single evidence row exceeds the repository bound")
                middle = len(rows) // 2
                pending[0:0] = [rows[:middle], rows[middle:]]
                continue
            path = self.folder / f"{self.prefix}_{len(self.parts):04d}.jsonl.gz"
            with path.open("xb") as stream:
                stream.write(payload)
            self.parts.append({"file": path.name, "rows": len(rows), "sha256": sha(path)})


def upstream():
    manifests = {}
    for name in ("SOURCE_FREEZE.json", "CANDIDATE_FREEZE.json"):
        remote = BASE / "upstream_readback" / name
        receipt = json.loads(remote.with_suffix(remote.suffix + ".receipt.json").read_text())
        data = remote.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != receipt["git_blob_sha"] or data != (OLD / name).read_bytes():
            raise ValueError("Pinned GitHub readback manifest differs: " + name)
        manifests[name] = json.loads(data)
    source, candidate = manifests["SOURCE_FREEZE.json"], manifests["CANDIDATE_FREEZE.json"]
    if candidate["source_freeze_sha256"] != sha(OLD / "SOURCE_FREEZE.json"):
        raise ValueError("Original candidate/source binding broken")
    for mapping in (source["source_sha256"], candidate["artifact_sha256"]):
        for path, expected in mapping.items():
            if sha(OLD / path) != expected:
                raise ValueError("Original frozen input changed: " + path)
    return {"baseline_commit": "631d33ba7ee815ee48c017269033e94cb2bc107c",
            "source_files_verified": len(source["source_sha256"]),
            "candidate_files_verified": len(candidate["artifact_sha256"]),
            "source_manifest_sha256": sha(OLD / "SOURCE_FREEZE.json"),
            "candidate_manifest_sha256": sha(OLD / "CANDIDATE_FREEZE.json"),
            "method": "Fresh pinned GitHub manifest readback, exact Git blob and local byte equality; all original source/artifact SHA256 entries verified. No syntactic commit-only bypass."}


def source_map():
    paths = sorted(BASE.glob("*.py")) + [BASE / "PROTOCOL.json"] + sorted((BASE / "upstream_readback").glob("*"))
    return {str(p.relative_to(BASE)): sha(p) for p in paths}


def verify_source():
    freeze = json.loads((BASE / "SOURCE_FREEZE.json").read_text())
    if freeze["source_sha256"] != source_map():
        raise ValueError("R12 source changed after freeze")
    if freeze["upstream"] != upstream():
        raise ValueError("Upstream identity changed")
    return freeze


def load_pair(family, seed):
    model_path = OLD / f"evidence/content/runs/multimodal_evidence/{family}_w16_s{seed}/final.npz"
    payload = json.loads((OLD / f"evidence/policy/fits/{family}_s{seed}/controller.json").read_text())
    if payload["source"] != policy_run.identity(model_path):
        raise ValueError("Original controller/checkpoint/source identity mismatch")
    return Model.load(model_path), payload, sha(model_path)


def controller(payload):
    if payload["kind"] == "deployed_ridge":
        return calibration.DeployedRidge(payload["mean"], payload["scale"], payload["weights"], payload["ridge"])
    return policy_run.controller_from(payload)


def train(out, protocol):
    verify_source()
    all_models = []
    for family in protocol["families"]:
        for seed in protocol["seeds"]:
            cpu, wall = time.process_time(), time.perf_counter()
            folder = out / f"{family}_s{seed}"; folder.mkdir()
            model, original, model_sha = load_pair(family, seed)
            graphs = [policy_run.build_graph(model, c) for c in calibration.configurations(protocol, "train")]
            dev = [policy_run.build_graph(model, c) for c in calibration.configurations(protocol, "dev")]
            inputs = Log(folder, "training_states")
            for graph in graphs:
                for row in graph.records():
                    inputs.add({"config": graph.config.payload(), **row})
            inputs.flush()
            following = controller(original["best_lightweight"])
            matched, labels = calibration.DeployedRidge.fit_following(graphs, following, protocol["ridge"],
                                                                     protocol["occupancy_fraction"], "qstar")
            write(folder / "matched_qstar.json", matched.payload())
            candidates = []
            for index in range(1, protocol["rounds"] + 1):
                fitted, labels = calibration.DeployedRidge.fit_following(
                    graphs, following, protocol["ridge"], protocol["occupancy_fraction"])
                raw = Log(folder, f"round{index:02d}_labels")
                for row in labels:
                    raw.add(row)
                raw.flush()
                filename = f"round{index:02d}.json"
                write(folder / filename, fitted.payload())
                dev_returns = [g.exact_policy(fitted)["return"] for g in dev]
                candidates.append({"round": index, "filename": filename, "sha256": sha(folder / filename),
                                   "dev_returns": dev_returns, "dev_mean": float(np.mean(dev_returns)),
                                   "following_policy_sha256": hashlib.sha256(encoded(following.payload()).encode()).hexdigest(),
                                   "label_parts": raw.parts})
                following = fitted
            selected = max(candidates, key=lambda row: row["dev_mean"])
            write(folder / "selected.json", json.loads((folder / selected["filename"]).read_text()))
            record = {"family": family, "seed": seed, "model_sha256": model_sha,
                      "training_configs": [g.config.payload() for g in graphs], "dev_configs": [g.config.payload() for g in dev],
                      "training_state_parts": inputs.parts, "candidates": candidates,
                      "selected_round": selected["round"], "selected_dev_mean": selected["dev_mean"],
                      "original_lightweight_dev_mean": float(np.mean([g.exact_policy(controller(original["best_lightweight"]))["return"] for g in dev])),
                      "original_qstar_dev_mean": float(np.mean([g.exact_policy(controller(original["value"]))["return"] for g in dev])),
                      "matched_qstar_dev_mean": float(np.mean([g.exact_policy(matched)["return"] for g in dev])),
                      "cpu_before_receipt": time.process_time() - cpu, "wall_before_receipt": time.perf_counter() - wall}
            write(folder / "FIT.json", record); all_models.append(record)
            print(encoded({"fit_complete": f"{family}_s{seed}", "selected_round": selected["round"]}), flush=True)
    verify_source()
    artifacts = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    write(out / "CANDIDATE_FREEZE.json", {"schema": "hcsn.r12.value.candidates.v1", "created_unix_time": time.time(),
         "source_freeze_sha256": sha(BASE / "SOURCE_FREEZE.json"), "fresh_evaluation_started": False,
         "artifact_sha256": artifacts, "models": all_models})


def evaluate(out, fit, protocol):
    verify_source()
    freeze = json.loads((fit / "CANDIDATE_FREEZE.json").read_text())
    if freeze["source_freeze_sha256"] != sha(BASE / "SOURCE_FREEZE.json"):
        raise ValueError("Candidate source identity changed")
    for path, expected in freeze["artifact_sha256"].items():
        if sha(fit / path) != expected:
            raise ValueError("Frozen training artifact changed: " + path)
    write(out / "STARTED.json", {"unix_time": time.time(), "candidate_freeze_sha256": sha(fit / "CANDIDATE_FREEZE.json"),
                               "source_freeze_sha256": sha(BASE / "SOURCE_FREEZE.json"), "upstream": upstream()})
    results = []
    for family in protocol["families"]:
        for seed in protocol["seeds"]:
            model, original, model_sha = load_pair(family, seed)
            tag = f"{family}_s{seed}"; folder = out / tag; folder.mkdir()
            controllers = {"lightweight": controller(original["best_lightweight"]),
                           "original_qstar": controller(original["value"]),
                           "matched_qstar": controller(json.loads((fit / tag / "matched_qstar.json").read_text())),
                           "qpi_selected": controller(json.loads((fit / tag / "selected.json").read_text()))}
            for index, config in enumerate(calibration.configurations(protocol, "fresh")):
                cpu, wall = time.process_time(), time.perf_counter()
                case = folder / config.name; case.mkdir()
                graph = policy_run.build_graph(model, config)
                evaluated = {name: calibration.evaluate_policy(graph, control) for name, control in controllers.items()}
                raw = Log(case, "state_values")
                for history, node in graph.nodes.items():
                    raw.add({"history": history, "state_sha256": policy.state_digest(node["state"]),
                             "public_features": node["features"], "qstar": node["q"],
                             "policies": {name: {"qpi": r["q"][history], "scores": r["predictions"][history],
                                                 "chosen": r["choices"][history], "occupancy": r["occupancy"].get(history, 0.)}
                                          for name, r in evaluated.items()}})
                raw.flush()
                paired = Log(case, "paired_execution")
                measured = audit.paired_execution(graph, controllers, protocol["paired_worlds_per_config"],
                                                   9120000 + seed * 100 + index, paired.add)
                paired.flush()
                names = ("lightweight", "original_qstar", "qpi_selected")
                prefixes = audit.select_prefixes(graph, [evaluated[n] for n in names])
                forced = Log(case, "forced_prefix_execution"); checks = []
                for history in prefixes:
                    for name in names:
                        for action in graph.nodes[history]["q"]:
                            def sink(row, name=name):
                                forced.add({"controller": name, **row})
                            check = audit.conditional_execution(graph, controllers[name], history, action,
                                                                  evaluated[name]["q"][history][action], sink)
                            checks.append({"controller": name, **check})
                forced.flush()
                summary = {"family": family, "seed": seed, "config": config.payload(), "model_sha256": model_sha,
                           "histories": len(graph.nodes), "initial_stop": graph.nodes[()]["q"]["STOP"],
                           "oracle_return": graph.nodes[()]["value"], "policies": {},
                           "forced_prefixes": prefixes, "forced_checks": checks,
                           "evidence_parts": {"states": raw.parts, "paired": paired.parts, "forced": forced.parts},
                           "cpu_before_receipt": time.process_time() - cpu, "wall_before_receipt": time.perf_counter() - wall}
                for name, result in evaluated.items():
                    exact = result["exact"]
                    read_fee, skip_fee = exact["expected_reads"] * config.read_cost, exact["expected_skips"] * config.skip_cost
                    summary["policies"][name] = {"exact": exact, "correctness": exact["return"] + read_fee + skip_fee,
                        "read_fee": read_fee, "skip_fee": skip_fee, "root_action": result["choices"][()],
                        "metrics": calibration.metrics(graph, result), "actual_paired": measured[name]}
                write(case / "RESULT.json", summary); results.append(summary)
                print(encoded({"confirmation_complete": tag, "config": config.name,
                               "qpi_return": summary["policies"]["qpi_selected"]["exact"]["return"]}), flush=True)
    contrasts = {}
    for seed in protocol["seeds"]:
        def mean(family, control):
            return float(np.mean([r["policies"][control]["exact"]["return"] for r in results
                                  if r["family"] == family and r["seed"] == seed]))
        a, b, c, d = mean("ordinary", "lightweight"), mean("ordinary", "qpi_selected"), mean("analytic", "lightweight"), mean("analytic", "qpi_selected")
        contrasts[str(seed)] = {"A": a, "B": b, "C": c, "D": d, "B-A": b-a, "D-C": d-c, "C-A": c-a, "D-B": d-b,
                                "interaction": d-c-b+a,
                                "ordinary_qpi_minus_old_qstar": b-mean("ordinary", "original_qstar"),
                                "analytic_qpi_minus_old_qstar": d-mean("analytic", "original_qstar"),
                                "ordinary_qpi_minus_matched_qstar": b-mean("ordinary", "matched_qstar"),
                                "analytic_qpi_minus_matched_qstar": d-mean("analytic", "matched_qstar")}
    descriptive = {key: {"mean": float(np.mean([r[key] for r in contrasts.values()])),
                         "minimum_seed_mean": min(r[key] for r in contrasts.values()),
                         "maximum_seed_mean": max(r[key] for r in contrasts.values())} for key in next(iter(contrasts.values()))}
    verify_source()
    write(out / "SUMMARY.json", {"schema": "hcsn.r12.value.confirmation.v1", "seed_contrasts": contrasts,
          "descriptive": descriptive, "fit_seed_count": 3, "fresh_configs_per_model": 8,
          "case_results": [str(p.relative_to(out)) for p in sorted(out.glob("*/*/RESULT.json"))],
          "scope": protocol["statistical_unit"], "source_freeze_sha256": sha(BASE / "SOURCE_FREEZE.json"),
          "candidate_freeze_sha256": sha(fit / "CANDIDATE_FREEZE.json")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "train", "evaluate"))
    parser.add_argument("--out"); parser.add_argument("--fit")
    args = parser.parse_args()
    if args.stage == "freeze":
        write(BASE / "SOURCE_FREEZE.json", {"schema": "hcsn.r12.value.source.v1", "created_unix_time": time.time(),
              "source_sha256": source_map(), "upstream": upstream(), "formal_training_started": False})
        return
    if not args.out or (args.stage == "evaluate" and not args.fit):
        parser.error("Fresh --out required; evaluate also requires frozen --fit")
    out = Path(args.out).resolve()
    if BASE not in out.parents:
        raise ValueError("Outputs must stay in this research namespace")
    out.mkdir(parents=True, exist_ok=False)
    cpu, wall = time.process_time(), time.perf_counter()
    protocol = json.loads((BASE / "PROTOCOL.json").read_text())
    try:
        if args.stage == "train":
            train(out, protocol)
        else:
            evaluate(out, Path(args.fit).resolve(), protocol)
    except Exception as error:
        write(out / "FAILURE.json", {"error_type": type(error).__name__, "error": str(error),
              "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall})
        raise
    write(out / "PROCESS.json", {"stage": args.stage, "exit_code": 0, "python": platform.python_version(),
          "numpy": np.__version__, "cpu_before_final_receipt": time.process_time() - cpu,
          "wall_before_final_receipt": time.perf_counter() - wall, "includes": "identity verification, all computation, raw serialization; excludes interpreter startup and this final receipt write"})


if __name__ == "__main__":
    main()
