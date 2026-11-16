"""E2: bounded JSON artifact interaction; no generated code or shell execution."""

import copy
import hashlib
import json
import math
from pathlib import Path
import time

from . import data
from .coding_sft import load_predictor
from .data_builder import oracle_answer

MAX_ACTION_BYTES = 16384


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data.canonical(value) + b"\n")


def _finish(path, value):
    value = {**value, "receipt_sha256": data.digest(value)}
    _save(path, value)
    return value


def _parse(answer):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    value = json.loads(answer, object_pairs_hook=unique)
    data.canonical(value)
    if not isinstance(value, dict):
        raise ValueError("artifact must be a JSON object")
    return value


def _prompt(record, observation=None):
    original = record["task"]["input"]
    if observation is None:
        return original
    return (
        original
        + "\nObserved own artifact attempt; return corrected JSON only:\n"
        + data.canonical(observation).decode()
    )


def _step(predictor, record, prompt, state, directory, number, apply):
    started, cpu = time.perf_counter(), time.process_time()
    before = copy.deepcopy(state)
    request = {"record_id": record["record_id"], "task": {"input": prompt}}
    _save(
        directory / f"request-{number}.json",
        {
            "request": request,
            "policy_digest": predictor.model_digest,
            "started_at_ns": time.time_ns(),
            "automatic_retry": False,
        },
    )
    generated = predictor.predict(request)
    _save(
        directory / f"generation-{number}.json",
        {"request": request, "output": generated},
    )
    if generated.get("loaded_model_digest") != predictor.model_digest:
        raise ValueError("generated output has a different policy identity")
    if (
        "input_sha256" in generated
        and generated["input_sha256"] != hashlib.sha256(prompt.encode()).hexdigest()
    ):
        raise ValueError("generated output is bound to a different input")
    answer = generated.get("answer")
    if not isinstance(answer, str) or len(answer.encode()) > MAX_ACTION_BYTES:
        raise ValueError("generated action exceeds bounded artifact contract")
    for key in ("input_tokens", "output_tokens"):
        if type(generated.get(key)) is not int or generated[key] < 0:
            raise ValueError("invalid measured token cost")
    if (
        not isinstance(generated.get("elapsed_seconds"), (float, int))
        or not math.isfinite(generated["elapsed_seconds"])
        or generated["elapsed_seconds"] < 0
    ):
        raise ValueError("invalid generation wall cost")
    try:
        parsed, parse_ok = _parse(answer), True
    except (ValueError, TypeError, RecursionError):
        parsed, parse_ok = None, False
    applied = apply and parse_ok
    if applied:
        path = directory / f"artifact-{number}.json"
        with path.open("xb") as stream:
            stream.write(answer.encode())
        observed = path.read_text()
        if observed != answer:
            raise ValueError("artifact write/readback differs")
        state = {
            "artifact": parsed,
            "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "artifact_name": path.name,
        }
    else:
        observed = answer
    verification = data.verify_answer(record, observed)
    semantic_ok = parse_ok and verification["success"]
    feedback = {"parse_ok": parse_ok, "semantic_ok": semantic_ok}
    receipt = _finish(
        directory / f"step-{number}.json",
        {
            "schema": "hepta.cell-experiments.artifact-step.v1",
            "task_id": record["task_id"],
            "record_digest": data.record_digest(record),
            "policy_digest": predictor.model_digest,
            "input": prompt,
            "raw_output": answer,
            "state_before": before,
            "state_after": state,
            "applied": applied,
            "execution_kind": "local_json_artifact" if applied else "none",
            "feedback": feedback,
            "verification": verification,
            "generation_cost": generated,
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "production_eligible": False,
        },
    )
    observation = {"state": state, "last_output": answer, "feedback": feedback}
    return receipt, state, observation


def _reference(record, directory):
    started, cpu = time.perf_counter(), time.process_time()
    answer = oracle_answer(record)
    verification = data.verify_answer(record, answer)
    if not verification["success"]:
        raise ValueError("training reference failed its semantic verifier")
    return _finish(
        directory / "reference.json",
        {
            "provider": "deterministic_reference",
            "external_model": False,
            "answer": answer,
            "input_sha256": hashlib.sha256(
                record["task"]["input"].encode()
            ).hexdigest(),
            "source_sha256": hashlib.sha256(
                Path(__file__).with_name("data_builder.py").read_bytes()
            ).hexdigest(),
            "verification": verification,
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "model_calls": 0,
        },
    )


def _example(record, arm, number, prompt, target, reference, step=None):
    result = copy.deepcopy(record)
    result.update(
        record_id=f"{record['record_id']}-{arm}-{number}",
        teacher_id=None,
        observed_at=int(time.time()),
        available_at=int(time.time()),
        origin_kind="curated_development",
        exposure="development",
    )
    result.pop("model_digest", None)
    result.pop("teacher_output_receipt_sha256", None)
    result.pop(
        "features", None
    )  # The new stateful input requires a new feature binding.
    result["task"]["input"], result["final_answer"] = prompt, target
    context = {"provider": "deterministic_reference", "external_model": False}
    if step:
        context.update(
            student_output=step["raw_output"],
            applied=step["applied"],
            feedback=step["feedback"],
            step_receipt_sha256=step["receipt_sha256"],
        )
    result["trajectory"] = [
        {
            "index": 0,
            "actor": "environment",
            "kind": "observation",
            "content": data.canonical(context).decode(),
            "executed": False,
            "receipt_sha256": step["receipt_sha256"]
            if step
            else reference["receipt_sha256"],
        },
        {
            "index": 1,
            "actor": "curator",
            "kind": "correction",
            "content": target,
            "executed": False,
            "receipt_sha256": reference["receipt_sha256"],
        },
    ]
    result["supervision"] = {
        "provider": "deterministic_reference",
        "external_model": False,
        "reference_receipt_sha256": reference["receipt_sha256"],
    }
    result["interaction"] = {
        "arm": arm,
        "parent_record_digest": data.record_digest(record),
        "student_step": step["receipt_sha256"] if step else None,
        "original_task_and_source_count_unchanged": True,
    }
    verification = data.verify_answer(result, target)
    result["verified_outcome"] = {
        "success": verification["success"],
        "receipt_sha256": verification["receipt_sha256"],
        "verifier_name": record["task"]["verifier"]["name"],
        "verifier_version": record["task"]["verifier"]["version"],
    }
    return result, verification


def _prepare(records, manifest, out, max_steps, collecting):
    data.validate_records(records)
    if type(max_steps) is not int or not 1 <= max_steps <= 4:
        raise ValueError("maximum calls must be an integer from 1 to 4")
    if collecting and any(
        r["split"] != "train" or not r["authorization"]["training_allowed"]
        for r in records
    ):
        raise ValueError(
            "reference supervision is permitted for authorized A records only"
        )
    if not collecting and any(
        r["split"] not in ("selection", "confirmation") for r in records
    ):
        raise ValueError("evaluation requires B/C records")
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    _save(
        root / "STARTED.json",
        {
            "records_digest": data.digest(records),
            "model_digest": data.digest(manifest),
            "max_model_calls_per_task_per_arm": max_steps,
            "started_at": time.time_ns(),
            "collecting": collecting,
            "automatic_retry": False,
        },
    )
    return root


def _summary(receipts, reserved_calls, references=()):
    return {
        "model_calls": len(receipts),
        "input_tokens": sum(r["generation_cost"]["input_tokens"] for r in receipts),
        "output_tokens": sum(r["generation_cost"]["output_tokens"] for r in receipts),
        "generation_wall_seconds": sum(
            r["generation_cost"]["elapsed_seconds"] for r in receipts
        ),
        "step_cpu_seconds": sum(r["cpu_seconds"] for r in receipts),
        "artifact_writes": sum(r["applied"] for r in receipts),
        "reserved_model_calls": reserved_calls,
        "unused_model_calls": reserved_calls - len(receipts),
        "reference_calls": len(references),
        "reference_wall_seconds": sum(r["wall_seconds"] for r in references),
        "reference_cpu_seconds": sum(r["cpu_seconds"] for r in references),
    }


def collect(train_records, parent_manifest, artifact_root, out, max_steps=2):
    root = _prepare(train_records, parent_manifest, out, max_steps, True)
    predictor, started = None, time.perf_counter()
    arms = {name: [] for name in ("demonstration", "shadow", "controlled")}
    steps = {name: [] for name in arms}
    references = {name: [] for name in arms}
    try:
        load_started = time.perf_counter()
        predictor = load_predictor(parent_manifest, artifact_root)
        load_seconds = time.perf_counter() - load_started
        if predictor.model_digest != data.digest(parent_manifest):
            raise ValueError("loaded parent identity mismatch")
        for index, record in enumerate(train_records):
            for arm in arms:
                directory = root / arm / f"task-{index}"
                reference = _reference(record, directory)
                references[arm].append(reference)
                state, prompt = {"artifact": None}, _prompt(record)
                count = max_steps if arm == "controlled" else 1
                for number in range(count):
                    step = None
                    if arm != "demonstration":
                        step, state, observation = _step(
                            predictor,
                            record,
                            prompt,
                            state,
                            directory,
                            number,
                            arm == "controlled",
                        )
                        steps[arm].append(step)
                    supervised_prompt = (
                        _prompt(record, observation)
                        if arm == "controlled" and not step["feedback"]["semantic_ok"]
                        else prompt
                    )
                    example, verification = _example(
                        record,
                        arm,
                        number,
                        supervised_prompt,
                        reference["answer"],
                        reference,
                        step,
                    )
                    arms[arm].append(example)
                    _save(
                        directory / f"supervision-{number}.json",
                        {"record": example, "verification": verification},
                    )
                    if arm != "controlled" or step["feedback"]["semantic_ok"]:
                        break
                    prompt = supervised_prompt
        for arm, records in arms.items():
            data.build_sft_examples(records, "trajectory")
            with (root / (arm + ".jsonl")).open("xb") as stream:
                stream.write(b"".join(data.canonical(r) + b"\n" for r in records))
        result = {
            "schema": "hepta.cell-experiments.interaction-collection.v1",
            "status": "COMPLETE_DEVELOPMENT_COLLECTION",
            "source_records": len(train_records),
            "model_digest": predictor.model_digest,
            "records": {arm: len(rows) for arm, rows in arms.items()},
            "cost": {
                arm: _summary(rows, len(train_records) * max_steps, references[arm])
                for arm, rows in steps.items()
            },
            "max_model_calls_per_task_per_arm": max_steps,
            "actual_calls_equal": len({len(v) for v in steps.values()}) == 1,
            "external_teacher_runs": 0,
            "independent_e2": "BLOCKED",
            "production_eligible": False,
            "model_load_seconds": load_seconds,
            "wall_seconds": time.perf_counter() - started,
        }
        _save(root / "RESULT.json", result)
        return result
    except BaseException as error:
        _save(
            root / "FAILED.json",
            {"status": "INCOMPLETE", "error": repr(error), "automatic_retry": False},
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()


def evaluate(manifest, artifact_root, records, out, max_steps=2):
    root = _prepare(records, manifest, out, max_steps, False)
    predictor, started, results, steps = None, time.perf_counter(), [], []
    try:
        load_started = time.perf_counter()
        predictor = load_predictor(manifest, artifact_root)
        load_seconds = time.perf_counter() - load_started
        if predictor.model_digest != data.digest(manifest):
            raise ValueError("loaded evaluation policy identity mismatch")
        for index, record in enumerate(records):
            directory = root / f"task-{index}"
            directory.mkdir()
            state, prompt, attempts = {"artifact": None}, _prompt(record), []
            for number in range(max_steps):
                step, state, observation = _step(
                    predictor, record, prompt, state, directory, number, True
                )
                steps.append(step)
                attempts.append(step["receipt_sha256"])
                if step["feedback"]["semantic_ok"]:
                    break
                prompt = _prompt(record, observation)
            results.append(
                {
                    "task_id": record["task_id"],
                    "record_digest": data.record_digest(record),
                    "success": step["feedback"]["semantic_ok"],
                    "attempt_receipts": attempts,
                    "unused_model_calls": max_steps - len(attempts),
                }
            )
        result = {
            "schema": "hepta.cell-experiments.interaction-evaluation.v1",
            "status": "COMPLETE_DEVELOPMENT_EVALUATION",
            "model_digest": predictor.model_digest,
            "tasks": results,
            "successes": sum(r["success"] for r in results),
            "denominator": len(records),
            "cost": _summary(steps, len(records) * max_steps),
            "max_model_calls_per_task": max_steps,
            "gold_feedback_exposed": False,
            "independent_e2": "BLOCKED",
            "production_eligible": False,
            "model_load_seconds": load_seconds,
            "wall_seconds": time.perf_counter() - started,
        }
        _save(root / "RESULT.json", result)
        return result
    except BaseException as error:
        _save(
            root / "FAILED.json",
            {"status": "INCOMPLETE", "error": repr(error), "automatic_retry": False},
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()
