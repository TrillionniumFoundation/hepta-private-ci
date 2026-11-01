"""Engineering replay of all archived states; this is not new confirmation."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import Planner
from .compression import GROUPS, ProjectionPrecisionError, project
from .fast_compression import FastProjectionLaw, fast_project


HERE = Path(__file__).resolve().parent


def run(folder):
    started = time.process_time()
    archives, beliefs, actions, stops = {}, 0, 0, 0
    maximum, likelihood_error = 0., 0.
    sampled, cache = None, {}
    for result_path in sorted(folder.glob("*/RESULT.json")):
        result = json.loads(result_path.read_text())
        calibration = HERE.parent / "addressed_decision_r15_20261101/run_01/calibration"
        fitted = json.loads(gzip.decompress((calibration / f"{result['seed']}.json.gz").read_bytes()))
        law = FastProjectionLaw(Law.from_payload(fitted["models"]["hx"]["payload"]))
        states = []
        for entry in result["archives"]:
            path = result_path.parent / entry["file"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == entry["sha256"]
            archives[path.relative_to(folder).as_posix()] = digest
            for world in json.loads(gzip.decompress(path.read_bytes())):
                for arm in world["arms"].values():
                    states.extend(np.asarray(saved["beliefs"]) for saved in arm["states"])
                old = world["arms"]["block2"]
                for saved, query in zip(old["states"], old["queries"], strict=True):
                    key = (result["seed"], query["dt"], query["price_scale"])
                    if key not in cache:
                        cache[key] = Planner(law, query["dt"], .025 * key[2], .07 * key[2],
                                             projection="block2")
                    planner = cache[key]
                    p = np.asarray(saved["beliefs"])[query["key"]]
                    expected = query["actions"][0]["action"] if query["actions"] else "STOP"
                    assert planner.choose(p, 3) == expected
                    actions += 1
                    if expected == "STOP":
                        assert planner.answer(p, 3) == query["answer"]
                        stops += 1
        batch = np.concatenate(states)
        beliefs += len(batch)
        if sampled is None:
            sampled = batch[:1024].copy()
        for mode in GROUPS:
            old, new = project(batch, mode), fast_project(batch, mode)
            maximum = max(maximum, float(np.max(abs(old - new))))
            assert maximum < 2e-14 and not np.any((batch > 0) & (new == 0))
            for emission in (law.E_read, law.E_refresh):
                likelihood_error = max(likelihood_error, float(np.max(abs(batch @ emission - new @ emission))))
    assert len(archives) == 128 and beliefs == 221184 and actions == 6144
    assert likelihood_error < 2e-14
    malformed = [np.zeros(40), np.ones(39) / 39, np.r_[[-.1], np.full(39, 1.1 / 39)],
                 np.r_[[np.nan], np.zeros(39)], np.r_[[np.inf], np.zeros(39)]]
    tiny = np.zeros(40)
    tiny[0], tiny[5] = 1e-200, 1.
    rejections = 0
    for mode in GROUPS:
        for p in malformed + [tiny]:
            exceptions = []
            for function in (project, fast_project):
                try:
                    function(p, mode)
                except (ValueError, ProjectionPrecisionError) as error:
                    exceptions.append(type(error).__name__)
            assert len(exceptions) == 2 and exceptions[0] == exceptions[1]
            rejections += 1
    timing = {}
    for mode in GROUPS:
        timing[mode] = {}
        for batch_size in (1, 32):
            costs = {"old": [], "fast": []}
            for repeat in range(5):
                order = (("old", project), ("fast", fast_project))
                for name, function in (order if repeat % 2 == 0 else order[::-1]):
                    begin = time.process_time()
                    for start in range(0, 1024, batch_size):
                        p = sampled[start] if batch_size == 1 else sampled[start:start + batch_size]
                        function(p, mode)
                    costs[name].append(time.process_time() - begin)
            timing[mode][str(batch_size)] = dict(cpu_seconds=costs, median_fast_over_old=float(
                np.median(costs["fast"]) / np.median(costs["old"])))
    return dict(schema="hcsn-r16-fast-engineering-replay-v1", passed=True,
                reused_archives_sha256=archives, recorded_beliefs=beliefs,
                compared_projection_outputs=beliefs * 3, first_actions_replayed=actions,
                stop_answers_replayed=stops, maximum_projection_difference=maximum,
                maximum_current_emission_difference=likelihood_error,
                rejection_pairs=rejections, serial_projection_timing=timing,
                new_scientific_confirmation=False, namespace18_not_used=True,
                process_cpu_seconds=time.process_time() - started,
                source_sha256={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                               for name in ("compression.py", "fast_compression.py", "fast_checks.py")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=HERE / "run_01")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.process_time()
    try:
        result = run(args.run)
    except Exception:
        result = dict(passed=False, traceback=traceback.format_exc(),
                      process_cpu_seconds=time.process_time() - started)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "reused_archives_sha256"}, sort_keys=True))
    if not result["passed"]:
        raise RuntimeError("Engineering replay failed; original failure is preserved")
