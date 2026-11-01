"""Freeze-bound additive confirmation using the unchanged R12 executor."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from experiments.hcsn_regeneration_content_20261031 import policy, policy_audit, policy_run
from experiments.hcsn_regeneration_content_20261031.content_tasks import multimodal_support
from experiments.hcsn_validation_r12_20261031.value import audit, calibration, run as inherited
from .guard import TailStop, trajectory_dominance
from .dominance import all_history_dominance


BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2]
FIT = inherited.BASE / "evidence/training_01"
sha, write, encoded, Log = inherited.sha, inherited.write, inherited.encoded, inherited.Log


def input_paths():
    """Include every pinned inherited source/artifact checked by the loader."""
    inherited.verify_source()
    old_source = json.loads((inherited.OLD / "SOURCE_FREEZE.json").read_text())
    old_candidates = json.loads((inherited.OLD / "CANDIDATE_FREEZE.json").read_text())
    r12_source = json.loads((inherited.BASE / "SOURCE_FREEZE.json").read_text())
    candidates = json.loads((FIT / "CANDIDATE_FREEZE.json").read_text())
    if candidates["source_freeze_sha256"] != sha(inherited.BASE / "SOURCE_FREEZE.json"):
        raise ValueError("Inherited candidates no longer bind the inherited sources")
    paths = [inherited.OLD / name for name in ("SOURCE_FREEZE.json", "CANDIDATE_FREEZE.json")]
    paths += [inherited.OLD / p for p in old_source["source_sha256"]]
    paths += [inherited.OLD / p for p in old_candidates["artifact_sha256"]]
    paths += [inherited.BASE / p for p in r12_source["source_sha256"]]
    paths += [inherited.BASE / "SOURCE_FREEZE.json", FIT / "CANDIDATE_FREEZE.json",
              inherited.BASE / "TRAINING_01_PROCESS.json"]
    for family in ("ordinary", "analytic"):
        for seed in (11, 23, 37):
            for name in ("selected.json", "matched_qstar.json"):
                path = FIT / f"{family}_s{seed}" / name
                if sha(path) != candidates["artifact_sha256"][str(path.relative_to(FIT))]:
                    raise ValueError("Inherited selected controller changed")
                paths.append(path)
    return sorted(set(paths))


def source_map():
    paths = list(BASE.glob("*.py")) + [BASE / "PROTOCOL.json", BASE / "README.md", BASE.parent / "__init__.py"]
    return {str(p.relative_to(REPO)): sha(p) for p in sorted(paths)}


def verify(publication=False):
    freeze = json.loads((BASE / "SOURCE_FREEZE.json").read_text())
    if freeze["source_sha256"] != source_map():
        raise ValueError("R13 source/protocol changed after freeze")
    if freeze["inherited_input_sha256"] != {str(p.relative_to(REPO)): sha(p) for p in input_paths()}:
        raise ValueError("Inherited input identity changed")
    if publication:
        receipt = json.loads((BASE / "SOURCE_PUBLICATION_READBACK.json").read_text())
        if not receipt.get("verified") or receipt["source_freeze_sha256"] != sha(BASE / "SOURCE_FREEZE.json"):
            raise ValueError("Source publication readback not verified")
        policy_run.commit(receipt["commit_sha"])
        expected = {**freeze["source_sha256"], str((BASE / "SOURCE_FREEZE.json").relative_to(REPO)): sha(BASE / "SOURCE_FREEZE.json")}
        if receipt["files_sha256"] != expected:
            raise ValueError("Remote readback does not cover every frozen R13 value source")
    return freeze


def controllers(family, seed):
    model, original, model_sha = inherited.load_pair(family, seed)
    tag = f"{family}_s{seed}"
    base = {"lightweight": inherited.controller(original["best_lightweight"]),
            "original_qstar": inherited.controller(original["value"]),
            "matched_qstar": inherited.controller(json.loads((FIT/tag/"matched_qstar.json").read_text())),
            "qpi_selected": inherited.controller(json.loads((FIT/tag/"selected.json").read_text()))}
    controls = {name: value for pair in ([(n, c), (n+"_tailstop", TailStop(c))] for n, c in base.items()) for name, value in pair}
    return model, controls, model_sha


def counters(controls, reset=False):
    result = {n: dict(c.counts) for n, c in controls.items() if isinstance(c, TailStop)}
    if reset:
        for c in controls.values():
            if isinstance(c, TailStop):
                c.reset_counts()
    return result


def paired(graph, controls, count, seed, sink):
    rows = {n: dict(returns=[], correctness=[], fees=[], actor_cpu=0., actor_wall=0., stages_cpu={}) for n in controls}
    checks, names = [], list(controls)
    for index, original in enumerate(policy_audit.sampled_worlds(graph.config, multimodal_support, count, seed)):
        manifest, executed = original.manifest(), {}
        for name in names[index % len(names):] + names[:index % len(names)]:
            world = policy_audit.World(manifest["world_id"], manifest["hidden_label_evaluator_only"],
                    manifest["outcomes_evaluator_only"], graph.config, multimodal_support)
            result = policy_audit.execute(graph.model, graph.config, multimodal_support, controls[name], world, graph)
            if any(step["guard_rejected"] for step in result["steps"]):
                raise AssertionError("Unexpected illegal-action fallback")
            row = rows[name]
            for plural, singular in (("returns", "return"), ("correctness", "correct"), ("fees", "fee")):
                row[plural].append(result[singular])
            row["actor_cpu"] += result["total_cpu_seconds"]
            row["actor_wall"] += result["total_wall_seconds"]
            for stage, elapsed in result["phase_cpu_seconds"].items():
                row["stages_cpu"][stage] = row["stages_cpu"].get(stage, 0.) + elapsed
            executed[name] = result
            sink({"controller": name, "source": manifest, "execution": result})
        for name in names[::2]:
            check = trajectory_dominance(executed[name], executed[name+"_tailstop"], graph.config.skip_cost)
            checks.append({"controller": name, "world_id": manifest["world_id"], **check})
    return rows, checks


def confirm(out):
    verify(publication=True)
    protocol = json.loads((BASE / "PROTOCOL.json").read_text())
    write(out/"STARTED.json", dict(unix_time=time.time(), source_freeze_sha256=sha(BASE/"SOURCE_FREEZE.json"),
          source_readback_sha256=sha(BASE/"SOURCE_PUBLICATION_READBACK.json"), fresh=True))
    for family in protocol["families"]:
        for seed in protocol["seeds"]:
            model, controls, model_sha = controllers(family, seed)
            for index, config in enumerate(calibration.configurations(protocol, "fresh")):
                cpu, wall = time.process_time(), time.perf_counter()
                case = out/f"{family}_s{seed}"/config.name
                case.mkdir(parents=True)
                graph = policy_run.build_graph(model, config)
                counters(controls, reset=True)
                evaluated = {n: calibration.evaluate_policy(graph, c) for n, c in controls.items()}
                graph_counts = counters(controls, reset=True)
                dominance, statistics = {}, {}
                for name in protocol["controllers"]:
                    left, right = evaluated[name], evaluated[name+"_tailstop"]
                    dominance[name], statistics[name], statistics[name+"_tailstop"] = all_history_dominance(graph, left, right)
                states = Log(case, "states")
                for history, node in graph.nodes.items():
                    states.add({"history": history, "state_sha256": policy.state_digest(node["state"]),
                        "public_features": node["features"], "qstar": node["q"],
                        "policies": {n: dict(qpi=r["q"][history], scores=r["predictions"][history],
                        chosen=r["choices"][history], occupancy=r["occupancy"].get(history, 0.),
                        continuation_statistics=statistics[n][history]) for n, r in evaluated.items()}})
                states.flush()
                raw = Log(case, "paired")
                measured, path_checks = paired(graph, controls, protocol["paired_worlds_per_config"],
                                                13103100 + seed*100 + index, raw.add)
                raw.flush()
                paired_counts = counters(controls, reset=True)
                occupied = [(sum(r["occupancy"].get(h, 0.) for r in evaluated.values()), h)
                            for h in graph.nodes if 0 < len(h) < len(config.dts)]
                occupied = [p for p in occupied if p[0] > 0]
                observed = [p for p in occupied if any(item >= 0 for item in p[1])]
                occupied = observed or occupied
                prefixes = [()] + ([min(occupied, key=lambda p: (-p[0], len(p[1]), p[1]))[1]] if occupied else [])
                forced, checks = Log(case, "forced"), []
                for history in prefixes:
                    for name, control in controls.items():
                        for action in graph.nodes[history]["q"]:
                            check = audit.conditional_execution(graph, control, history, action,
                                    evaluated[name]["q"][history][action],
                                    lambda row, name=name: forced.add({"controller": name, **row}))
                            checks.append({"controller": name, **check})
                forced.flush()
                summary = dict(family=family, seed=seed, config=config.payload(), model_sha256=model_sha,
                    histories=len(graph.nodes), initial_stop=graph.nodes[()]["q"]["STOP"],
                    oracle=graph.nodes[()]["value"], policies={}, exact_dominance=dominance,
                    trajectory_dominance=path_checks, forced_prefixes=prefixes, forced_checks=checks,
                    wrapper_counts=dict(graph=graph_counts, paired=paired_counts, forced=counters(controls)),
                    evidence_parts=dict(states=states.parts, paired=raw.parts, forced=forced.parts))
                for name, result in evaluated.items():
                    exact = result["exact"]
                    fee = exact["expected_reads"]*config.read_cost + exact["expected_skips"]*config.skip_cost
                    summary["policies"][name] = dict(exact=exact, correctness=exact["return"]+fee,
                        root_action=result["choices"][()], metrics=calibration.metrics(graph, result),
                        actual_paired=measured[name], below_initial_stop=exact["return"] < summary["initial_stop"]-2e-10)
                summary.update(cpu_before_receipt=time.process_time()-cpu, wall_before_receipt=time.perf_counter()-wall)
                write(case/"RESULT.json", summary)
                print(encoded(dict(completed=f"{family}_s{seed}/{config.name}")), flush=True)
    verify(publication=True)
    from .analysis import summarize
    summarize(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "evaluate", "supervise"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.stage == "freeze":
        write(BASE/"SOURCE_FREEZE.json", dict(schema="hcsn.r13.value.source.v1", unix_time=time.time(),
              confirmation_started=False, source_sha256=source_map(),
              inherited_input_sha256={str(p.relative_to(REPO)):sha(p) for p in input_paths()}))
        return
    if args.out is None or BASE not in args.out.resolve().parents:
        parser.error("A fresh output path inside the R13 value namespace is required")
    out = args.out.resolve()
    if args.stage == "supervise":
        if out.exists():
            raise ValueError("Existing output cannot be overwritten")
        cpu, wall = time.process_time(), time.perf_counter()
        stdout_path, stderr_path = BASE/(out.name+"_STDOUT.log"), BASE/(out.name+"_STDERR.log")
        command = [sys.executable, "-B", "-m", __package__+".run", "evaluate", "--out", str(out)]
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        receipt = dict(exit_code=process.returncode, child_cpu_seconds=usage.ru_utime+usage.ru_stime,
            wall_seconds=time.perf_counter()-wall, supervisor_cpu_seconds=time.process_time()-cpu,
            max_rss_kib=usage.ru_maxrss, energy_joules=None,
            command=command, logs={str(p.relative_to(REPO)):dict(sha256=sha(p), bytes=p.stat().st_size)
                                  for p in (stdout_path, stderr_path)},
            includes="Fresh child interpreter startup/imports/verification/all evaluation/serialization/exit; nested actor times are not added again.")
        write(BASE/(out.name+"_PROCESS.json"), receipt)
        raise SystemExit(process.returncode)
    out.mkdir(parents=True, exist_ok=False)
    cpu, wall = time.process_time(), time.perf_counter()
    try:
        confirm(out)
    except Exception as error:
        write(out/"FAILURE.json", dict(error_type=type(error).__name__, error=str(error),
              cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall))
        raise
    write(out/"PROCESS_BODY.json", dict(cpu_seconds=time.process_time()-cpu,
          wall_seconds=time.perf_counter()-wall, python=platform.python_version(), numpy=np.__version__,
          energy_joules=None, scope="Body including verification; excludes interpreter startup and final receipt write."))


if __name__ == "__main__":
    main()
