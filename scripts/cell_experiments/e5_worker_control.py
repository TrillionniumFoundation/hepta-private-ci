"""Run two registered public paired evaluations under a balanced worker schedule."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from . import adoption, coding_sft, data

PROTOCOL = (
    Path(__file__).resolve().parents[2]
    / "qualification/e5-worker-readback-20261123/PROTOCOL.json"
)
PROTOCOL_HASH = "b7991574f51813d7017a0eb5480f044e4887ecbf80ac1461df2ed9115fd64206"


def protocol():
    raw = PROTOCOL.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROTOCOL_HASH:
        raise ValueError("registered worker control changed")
    return json.loads(raw)


def allocation(study):
    points = []
    for users in study["users"]:
        for regime, budget in study["regimes"].items():
            units = budget if regime == "fixed_total" else budget * users
            if units % users or units < users:
                raise ValueError("unequal or missing user exposure")
            for workers in study["workers"]:
                points.append(
                    dict(
                        regime=regime,
                        users=users,
                        workers=workers,
                        updates=units,
                        updates_per_user=units // users,
                    )
                )
    return points


def intervals(jobs, start, end):
    events = {}
    for job in jobs:
        begin, finish = job["start_ns"], job["end_ns"]
        if not start <= begin < finish <= end:
            raise ValueError("job outside measured batch")
        events[begin] = events.get(begin, 0) + 1
        events[finish] = events.get(finish, 0) - 1
    active, previous, elapsed = 0, start, {}
    for tick, movement in sorted(events.items()):
        elapsed[active] = elapsed.get(active, 0) + tick - previous
        active += movement
        previous = tick
    elapsed[0] = elapsed.get(0, 0) + end - previous
    return {n: t for n, t in elapsed.items() if t}


def inspect(output, request, expected):
    result = adoption.read_json(output / "RESULT.json")
    if result["request_sha256"] != expected:
        raise ValueError("wrong paired result")
    rows = []
    for arm, committed in zip(
        ("parent", "candidate"), result["cold_receipts"], strict=True
    ):
        receipt = adoption.read_json(output / arm / "END.json")
        if (
            receipt != committed
            or receipt["request_sha256"] != expected
            or receipt["arm"] != arm
        ):
            raise ValueError("cold receipt differs")
        if len(receipt["row_hashes"]) != len(request["future"]) + len(
            request["retention"]
        ):
            raise ValueError("cold row inventory differs")
        index = 0
        for panel in ("future", "retention"):
            for task in request[panel]:
                row = adoption.read_json(output / arm / f"{index:04d}.json")
                pred = row["prediction"]
                measured = pred.get("circuit_trace", {}).get("cost")
                score = data.verify_answer(task, pred["answer"])
                if (
                    row["panel"] != panel
                    or row["task_sha256"] != data.digest(task)
                    or pred["loaded_model_digest"] != data.digest(request[arm])
                    or receipt["row_hashes"][index] != data.digest(row)
                    or pred["pid"] != receipt["pid"]
                    or data.digest(score) != data.digest(row["outcome"])
                ):
                    raise ValueError("retained paired row differs")
                rows.append(
                    dict(
                        arm=arm,
                        panel=panel,
                        model=pred["loaded_model_digest"],
                        input=score["input_sha256"],
                        answer=score["answer_sha256"],
                        passed=score["success"],
                        model_calls=measured["model_calls"] if measured else 1,
                        input_tokens=measured["input_tokens"]
                        if measured
                        else pred["input_tokens"],
                        output_tokens=measured["output_tokens"]
                        if measured
                        else pred["output_tokens"],
                    )
                )
                index += 1
    return dict(
        counts=result["counts"],
        rows=rows,
        future_delta=result["future_success_count_delta"],
        retention=result["old_parent_successes_preserved"],
    )


def evaluate(job, material, root, env, training_modules, fixture_flag):
    name, expected = job["name"], job["request_sha256"]
    out = root / name
    start = time.monotonic_ns()
    command = [
        sys.executable,
        "-m",
        "cell_experiments.paired_cold",
        str(material / "request.json"),
        expected,
        str(material),
        str(out),
    ]
    cwd = None
    if training_modules:
        # PEFT serializes the supplied base directory into the signed model material.
        # Refit from the relative path recorded in the original public fixture.
        fixture = "circuit-fitted-controls-final" if name == "circuit" else "plain"
        cwd = root.resolve()
        command = [sys.executable, "-m", training_modules[name], fixture_flag, fixture]
        out = root / fixture / "evaluation"
    with (root / f"{name}.log").open("xb") as log:
        result = subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=cwd
        )
    row = dict(request=expected, start_ns=start, returncode=result.returncode)
    if result.returncode == 0:
        try:
            req = adoption.read_json(out / "REQUEST.json")
            if data.digest(req) != expected:
                raise ValueError("archived request changed")
            row["observation"] = inspect(out, req, expected)
        except (OSError, ValueError, KeyError, adoption.EvidenceError) as error:
            row["inspection_failure"] = str(error)
    row["end_ns"] = time.monotonic_ns()
    return row


def batch(jobs, materials, workers, root, env, training_modules, fixture_flag):
    root.mkdir(mode=0o700)
    start = time.monotonic_ns()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = [
            pool.submit(
                evaluate, job, material, root, env, training_modules, fixture_flag
            )
            for job, material in zip(jobs, materials, strict=True)
        ]
        finished = [future.result() for future in pending]
    end = time.monotonic_ns()
    spans = intervals(finished, start, end)
    completed = {j["request"] for j in finished if "observation" in j}
    latencies = sorted((j["end_ns"] - start) / 1e9 for j in finished)
    seconds = (end - start) / 1e9
    return dict(
        workers=workers,
        start_ns=start,
        end_ns=end,
        seconds=seconds,
        job_concurrency_nanoseconds=spans,
        peak_admitted_jobs=max(spans),
        p95_submission_to_verdict_seconds=latencies[
            math.ceil(0.95 * len(latencies)) - 1
        ],
        offered_unique_pairs=len(jobs),
        completed_unique_pairs=len(completed),
        failures=len(jobs) - len(completed),
        completed_unique_pairs_per_hour=3600 * len(completed) / seconds,
        jobs=finished,
    )


def run(plain, circuit, out, *, train=False, release_trainer=False):
    plan = protocol()
    jobs = plan["jobs"]
    training_modules = {}
    plan_hash = PROTOCOL_HASH
    if train:
        training_bytes = PROTOCOL.with_name("TRAINING_PROTOCOL.json").read_bytes()
        plan_hash = hashlib.sha256(training_bytes).hexdigest()
        if (
            plan_hash
            != "74e928e9bb12be4edb5a92fa06490d9495051bf7d7aec50b3ea100cc712d2ee4"
        ):
            raise ValueError("registered training control changed")
        training = json.loads(training_bytes)
        training_modules = training["training_modules"]
        if (
            training["blocks"] != plan["blocks"]
            or training["worker_protocol_sha256"] != PROTOCOL_HASH
        ):
            raise ValueError("worker protocol differs")
        plan["scope"] = training["scope"]
    fixture_flag = "--fixture"
    if release_trainer:
        correction = PROTOCOL.with_name("RELEASE_TRAINER_PROTOCOL.json").read_bytes()
        if (
            not train
            or json.loads(correction)["parent_training_protocol_sha256"] != plan_hash
            or hashlib.sha256(correction).hexdigest()
            != "fafa22c8e0f9aefd05de380efc787318556392e5c3b11bd3c88e5f6df30581ff"
        ):
            raise ValueError("registered training recovery differs")
        plan_hash = hashlib.sha256(correction).hexdigest()
        fixture_flag = "--fit-exec"
        plan["scope"] += " Trainer address space released before evaluation."
    materials = [plain.resolve(), circuit.resolve()]
    for job, directory in zip(jobs, materials, strict=True):
        if (
            data.digest(adoption.read_json(directory / "request.json"))
            != job["request_sha256"]
        ):
            raise ValueError("unexpected fixture or order")
    if len({j["request_sha256"] for j in jobs}) != len(jobs):
        raise ValueError("duplicate evaluation identity")
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    results = []
    for block, ordering in enumerate(plan["blocks"], start=1):
        for workers in ordering:
            name = f"block-{block}-workers-{workers}"
            observation = batch(
                jobs,
                materials,
                workers,
                out / name,
                env,
                training_modules,
                fixture_flag,
            )
            coding_sft.write_new(out / name / "BATCH.json", observation)
            results.append(observation)

    def projections(batch_row):
        return {
            j["request"]: j["observation"]
            for j in batch_row["jobs"]
            if "observation" in j
        }

    baseline = projections(results[0])
    matched = len(baseline) == len(jobs) and all(
        projections(r) == baseline for r in results
    )
    realized = all(r["peak_admitted_jobs"] == r["workers"] for r in results)
    speeds = {}
    if matched and realized:
        for workers in sorted({r["workers"] for r in results}):
            speeds[workers] = statistics.median(
                r["completed_unique_pairs_per_hour"]
                for r in results
                if r["workers"] == workers
            )
    future_inputs = {
        row["input"]
        for obs in baseline.values()
        for row in obs["rows"]
        if row["panel"] == "future"
    }
    report = dict(
        protocol_sha256=plan_hash,
        clock="coordinator monotonic_ns",
        python=sys.version.split()[0],
        blocks=plan["blocks"],
        runs=results,
        scope=plan["scope"],
        distinct_future_input_hashes_in_baseline=sorted(future_inputs),
        matched_outputs_and_work=matched,
        requested_overlap_observed=realized,
        median_pairs_per_hour=speeds,
        authenticated_training_users=0,
        independent_future_users=0,
        authenticated_adoptions_observed=0,
        unique_adopted_candidates_per_hour=None,
        human_scale_observations=[],
        human_allocation_only=allocation(plan["human_study"]),
    )
    coding_sft.write_new(out / "SUMMARY.json", report)
    return matched and realized


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("plain", "circuit", "output"):
        parser.add_argument(arg, type=Path)
    parser.add_argument(
        "--train",
        action="store_true",
        help="fit each public fixture from scratch before cold scoring",
    )
    parser.add_argument(
        "--release-trainer",
        action="store_true",
        help="replace each trainer process with the paired cold evaluator after fitting",
    )
    args = parser.parse_args()
    if not run(
        args.plain,
        args.circuit,
        args.output,
        train=args.train,
        release_trainer=args.release_trainer,
    ):
        parser.exit(1, "paired observations or worker overlap differed; see summary\n")


if __name__ == "__main__":
    main()
