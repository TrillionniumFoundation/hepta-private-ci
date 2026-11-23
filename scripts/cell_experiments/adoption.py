"""Research selection, fresh use and a separately loaded process.

This owns an experiment journal, not CellOwner, agentd, HEPLCP or FinalUse.
No command, module or executable is taken from a model/task manifest.
"""

import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


class EvidenceError(ValueError):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, reason, status="FAILED"):
    if not condition:
        raise EvidenceError(status, reason)


def need(value, names):
    require(isinstance(value, dict), "expected an evidence object")
    require(
        all(k in value for k in names.split()), "missing fields: " + names, "BLOCKED"
    )


def read_json(path):
    raw = Path(path).read_bytes()
    require(len(raw) <= 16 * 1024 * 1024, "JSON exceeds input limit")

    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def verify_manifest(manifest, artifact_root):
    need(manifest, "schema family runtime files parent")
    require(manifest["schema"] == "hepta.experimental-model.v1", "model schema")
    require(isinstance(manifest["family"], str) and manifest["family"], "model family")
    require(isinstance(manifest["runtime"], dict), "frozen numeric/runtime profile")
    files = manifest["files"]
    require(
        isinstance(files, list) and 0 < len(files) <= 256,
        "complete model files required",
        "BLOCKED",
    )
    root, seen, roles = Path(artifact_root).resolve(strict=True), set(), set()
    for item in files:
        need(item, "path role bytes sha256")
        relative = Path(item["path"])
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            "model path must stay inside artifact root",
        )
        path = (root / relative).resolve(strict=True)
        require(
            path.is_relative_to(root) and path.is_file(),
            "model file escaped artifact root",
        )
        require(str(path) not in seen, "duplicate model file")
        seen.add(str(path))
        roles.add(item["role"])
        require(
            type(item["bytes"]) is int and path.stat().st_size == item["bytes"],
            "model file size mismatch",
        )
        observed = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                observed.update(block)
        require(observed.hexdigest() == item["sha256"], "model file hash mismatch")
    require(
        {"base", "tokenizer"} <= roles,
        "base and tokenizer materials required",
        "BLOCKED",
    )
    return digest(manifest)


def validate(request):
    need(request, "plan parent candidate training evaluation c_tasks artifact_root")
    require(all(request[k] is not None for k in request), "missing input", "BLOCKED")
    plan, train, evaluation = (request[k] for k in ("plan", "training", "evaluation"))
    need(
        plan,
        "schema operation_id frozen_at_ns training_owner evaluation_owner parent_model_digest train_sources b_tasks c_tasks",
    )
    require(plan["schema"] == "hepta.e6.plan.v1", "plan schema")
    require(
        isinstance(plan["operation_id"], str) and 0 < len(plan["operation_id"]) <= 128,
        "operation ID",
    )
    for receipt in (train, evaluation):
        need(receipt, "status")
        status = receipt["status"]
        require(
            status == "COMPLETE",
            "upstream receipt is " + str(status),
            status if status in ("BLOCKED", "FAILED", "INCOMPLETE") else "INCOMPLETE",
        )
        need(receipt, "plan_digest owner started_at_ns completed_at_ns")
        require(
            receipt["plan_digest"] == digest(plan), "receipt does not bind frozen plan"
        )
    scope = plan.get("evidence_scope", "independent")
    require(scope in ("independent", "engineering"), "unknown evidence scope")
    require(
        scope == "engineering",
        "independent scope requires original authenticated B/C and controller evidence; this research coordinator has no authentication authority",
        "BLOCKED",
    )
    timeout = plan.get("cold_timeout_seconds", 120)
    require(
        type(timeout) in (int, float) and 0 < timeout <= 600 and math.isfinite(timeout),
        "cold timeout",
    )
    need(train, "parent_model_digest candidate_model_digest steps parameter_change")
    need(evaluation, "rows")
    times = [
        plan["frozen_at_ns"],
        train["started_at_ns"],
        train["completed_at_ns"],
        evaluation["started_at_ns"],
        evaluation["completed_at_ns"],
    ]
    require(
        all(type(t) is int and 0 < t <= time.time_ns() for t in times)
        and times == sorted(times),
        "freeze/training/evaluation chronology",
    )
    require(
        train["owner"] == plan["training_owner"]
        and evaluation["owner"] == plan["evaluation_owner"]
        and train["owner"] != evaluation["owner"],
        "distinct declared B owner required",
        "BLOCKED",
    )
    parent = verify_manifest(request["parent"], request["artifact_root"])
    candidate = verify_manifest(request["candidate"], request["artifact_root"])
    require(
        plan["parent_model_digest"] == parent
        and train["parent_model_digest"] == parent
        and train["candidate_model_digest"] == candidate
        and request["candidate"]["parent"] == parent,
        "training/parent/candidate lineage",
    )
    require(
        type(train["steps"]) is int
        and train["steps"] > 0
        and type(train["parameter_change"]) is bool,
        "actual training receipt required",
    )
    weights = lambda model: sorted(
        (f["role"], f["sha256"])
        for f in model["files"]
        if f["role"] in ("base", "weights", "adapter")
    )
    require(
        train["parameter_change"]
        == (weights(request["parent"]) != weights(request["candidate"])),
        "parameter-change claim disagrees with weight artifacts",
    )
    panels = [plan["b_tasks"], plan["c_tasks"]]
    require(
        all(isinstance(rows, list) and rows for rows in panels),
        "B and C panels required",
        "BLOCKED",
    )
    tasks = [row for panel in panels for row in panel]
    for row in tasks:
        need(row, "task_id source_id task_digest")
        require(
            all(isinstance(row[k], str) and row[k] for k in ("task_id", "source_id"))
            and isinstance(row["task_digest"], str)
            and len(row["task_digest"]) == 64,
            "task/source identity is missing or malformed",
        )
    require(
        isinstance(plan["train_sources"], list)
        and all(isinstance(s, str) and s for s in plan["train_sources"]),
        "training source identities",
    )
    sources = [set(plan["train_sources"])] + [
        {r["source_id"] for r in rows} for rows in panels
    ]
    require(
        all(sources)
        and not any(sources[i] & sources[j] for i in range(3) for j in range(i)),
        "A/B/C declared source groups must be disjoint",
        "BLOCKED",
    )
    require(
        len({r["task_id"] for r in tasks}) == len(tasks)
        and len({r["task_digest"] for r in tasks}) == len(tasks),
        "B/C duplicate task identity",
    )
    baselines = plan.get("baseline_models", {"parent": parent})
    require(
        isinstance(baselines, dict)
        and baselines.get("parent") == parent
        and "candidate" not in baselines,
        "baseline model bindings",
    )
    models = {**baselines, "candidate": candidate}
    expected = {(arm, row["task_id"]): row for arm in models for row in plan["b_tasks"]}
    rows = evaluation["rows"]
    require(
        isinstance(rows, list) and len(rows) == len(expected),
        "B is incomplete",
        "INCOMPLETE",
    )
    groups, seen = {}, set()
    for row in rows:
        require(
            isinstance(row, dict)
            and all(
                k in row
                for k in (
                    "arm",
                    "task_id",
                    "task_digest",
                    "source_id",
                    "loaded_model_digest",
                    "success",
                    "output_digest",
                )
            ),
            "B row is incomplete",
            "INCOMPLETE",
        )
        key = (row["arm"], row["task_id"])
        require(
            key in expected and key not in seen,
            "B task missing, duplicated or unexpected",
        )
        seen.add(key)
        require(
            all(row[k] == expected[key][k] for k in ("task_digest", "source_id"))
            and row["loaded_model_digest"] == models[row["arm"]],
            "B source/model binding",
        )
        require(
            type(row["success"]) is bool
            and isinstance(row["output_digest"], str)
            and len(row["output_digest"]) == 64
            and all(c in "0123456789abcdef" for c in row["output_digest"]),
            "B outcome receipt",
        )
        groups.setdefault(row["arm"], {}).setdefault(row["source_id"], []).append(
            row["success"]
        )
    scores = {
        arm: sum(sum(v) / len(v) for v in grouped.values()) / len(grouped)
        for arm, grouped in groups.items()
    }
    gain = plan.get("minimum_gain", 0.0)
    require(
        type(gain) in (int, float) and math.isfinite(gain) and gain >= 0,
        "selection margin",
    )
    adopted = (
        train["parameter_change"]
        and scores["candidate"] > max(scores[a] for a in baselines) + gain
    )
    supplied = request["c_tasks"]
    require(
        isinstance(supplied, list) and len(supplied) == len(plan["c_tasks"]),
        "C inputs incomplete",
        "BLOCKED",
    )
    from .data import validate_record

    for declared, task in zip(plan["c_tasks"], supplied):
        need(task, "task_id task_digest source_id record")
        validate_record(task["record"], require_outcome=False)
        require(
            all(task[k] == declared[k] for k in ("task_id", "task_digest", "source_id"))
            and all(task[k] == task["record"][k] for k in ("task_id", "source_id"))
            and task["record"]["split"] == "confirmation"
            and digest(task["record"]) == task["task_digest"],
            "C changed since freeze or has wrong split",
        )
    from .adoption_future import validate_d

    selected_manifest = request["candidate" if adopted else "parent"]
    validate_d(request, sys.modules[__name__], selected_manifest["runtime"])
    return (
        ("ADOPTED" if adopted else "NO_UPDATE"),
        (candidate if adopted else parent),
        scores,
    )


def load_predictor(manifest, root):
    from .coding_sft import load_predictor as load

    return load(manifest, Path(root))


def prediction(predictor, record, selected):
    require(predictor.model_digest == selected, "loaded model identity mismatch")
    result = predictor.predict(record)
    require(
        isinstance(result.get("answer"), str) and len(result["answer"]) <= 1024 * 1024,
        "prediction answer missing or too large",
    )
    require(
        result["loaded_model_digest"] == selected, "prediction used a different model"
    )
    require(
        all(
            type(result[k]) is int and result[k] >= 0
            for k in ("input_tokens", "output_tokens")
        )
        and type(result["elapsed_seconds"]) in (int, float)
        and math.isfinite(result["elapsed_seconds"])
        and result["elapsed_seconds"] >= 0,
        "prediction measurements",
    )
    return result


def comparable(result):
    return {
        k: result[k]
        for k in ("answer", "input_tokens", "output_tokens", "loaded_model_digest")
    }


def recover(spec, expected_digest=None):
    if expected_digest is not None:
        require(digest(spec) == expected_digest, "cold request changed")
    selected = verify_manifest(spec["manifest"], spec["artifact_root"])
    with closing(sqlite3.connect(f"file:{spec['database']}?mode=ro", uri=True)) as db:
        row = db.execute(
            "SELECT binding,selected FROM selections WHERE operation=?",
            (spec["operation_id"],),
        ).fetchone()
    require(row == (spec["binding"], selected), "cold durable selection changed")
    from .adoption_future import admit_d, execute_d

    require(
        "d_tasks" not in spec or expected_digest is not None,
        "D requires the original cold request digest",
    )
    admit_d(spec, sys.modules[__name__])
    predictor = load_predictor(spec["manifest"], spec["artifact_root"])
    try:
        from .adoption_costs import predict

        result = predict(
            predictor,
            spec["record"],
            selected,
            Path(spec["database"]).parent,
            "cold_C_replay",
            sys.modules[__name__],
        )
        new_tasks = execute_d(predictor, spec, selected, result, sys.modules[__name__])
        require(
            verify_manifest(spec["manifest"], spec["artifact_root"]) == selected,
            "cold materials changed",
        )
        recovered = {
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "selected_model_digest": selected,
            "prediction": result,
        }
        if new_tasks is not None:
            recovered["D"] = new_tasks
        return recovered
    finally:
        predictor.close()


def execute(request, output):
    """Run one immutable operation; ambiguous prior attempts require reconciliation."""
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    report = dict(
        schema="hepta.e6.result.v1",
        status="BLOCKED",
        model_decision=None,
        ordinary_daemon_qualification=False,
        hepta_final_use_accepted=False,
        native_learning_join_status="MISSING_ORIGINAL_NATIVE_MATERIALS",
        independent_control_authenticated=False,
        settlement_verified=False,
        costs_complete=False,
        energy_joules=None,
        production_activation=False,
        authority="DENY_ALL",
        qualification="HOLD_NO_GO",
    )
    plan_view = request.get("plan", {}) if isinstance(request, dict) else {}
    plan_view = plan_view if isinstance(plan_view, dict) else {}
    c_records = (
        [
            t["record"]
            for t in request.get("c_tasks", [])
            if isinstance(t, dict) and isinstance(t.get("record"), dict)
        ]
        if isinstance(request, dict) and isinstance(request.get("c_tasks"), list)
        else []
    )
    report.update(
        evidence_scope=plan_view.get("evidence_scope", "independent"),
        independent_e6_status="BLOCKED",
        declared_time_ordered=plan_view.get("time_ordered"),
        C_source_exposure=[
            {
                k: r.get(k)
                for k in (
                    "source_id",
                    "origin_kind",
                    "exposure",
                    "split",
                    "available_at",
                )
            }
            for r in c_records
        ],
        independent_e6_gaps=[
            "original B provenance/execution authentication unavailable",
            "source separation and dataset time order are not independently authenticated",
            "trainer/evaluator controller independence is not authenticated",
            "prospective unexposed C is not authenticated",
        ],
    )
    if any(
        r.get("origin_kind") == "curated_development"
        or r.get("exposure") == "development"
        for r in c_records
    ):
        report["independent_e6_gaps"].append(
            "C includes curated or development-exposed records"
        )
    db, predictor, inserted = None, None, False
    started = time.monotonic()
    try:
        # Detach caller-owned nested objects before validation or any callback.
        request = json.loads(canonical(request))
        decision, selected, scores = validate(request)
        plan = request["plan"]
        binding = digest(request)
        manifest = request["candidate"] if decision == "ADOPTED" else request["parent"]
        from .adoption_journal import completed_report, open_selection

        db = open_selection(
            root,
            plan["operation_id"],
            binding,
            selected,
            decision,
            sys.modules[__name__],
        )
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT binding,report,selected,decision FROM selections WHERE operation=?",
            (plan["operation_id"],),
        ).fetchone()
        if prior:
            db.rollback()
            require(
                prior[0] == binding, "operation was already bound to different evidence"
            )
            old = completed_report(
                root,
                prior[1],
                binding,
                selected,
                decision,
                digest(plan),
                sys.modules[__name__],
            )
            if old is not None:
                return old
            report.update(model_decision=prior[3], selected_model_digest=prior[2])
            raise EvidenceError(
                "INCOMPLETE",
                "prior selected operation requires reconciliation; no task repeated",
            )
        db.execute(
            "INSERT INTO selections VALUES(?,?,?,?,NULL)",
            (plan["operation_id"], binding, selected, decision),
        )
        db.commit()
        inserted = True
        report.update(
            status="INCOMPLETE",
            model_decision=decision,
            selected_model_digest=selected,
            plan_digest=digest(plan),
            evidence_binding=binding,
            B_scores=scores,
            B_declared_source_and_time_bindings_checked=True,
            C=[],
        )
        save(root / "REQUEST.json", request)
        save(root / "DECISION.json", report)
        predictor = load_predictor(manifest, request["artifact_root"])
        from .data import verify_answer

        for task in request["c_tasks"]:
            c_started = time.time_ns()
            from .adoption_costs import predict

            result = predict(
                predictor,
                task["record"],
                selected,
                root,
                "hot_C",
                sys.modules[__name__],
            )
            outcome = verify_answer(task["record"], result["answer"])
            report["C"].append(
                dict(
                    task_id=task["task_id"],
                    task_digest=task["task_digest"],
                    source_id=task["source_id"],
                    prediction=result,
                    outcome=outcome,
                    started_at_ns=c_started,
                    completed_at_ns=time.time_ns(),
                )
            )
            save(root / "C_RECEIPTS.json", report["C"])
        predictor.close()
        predictor = None
        spec = dict(
            manifest=manifest,
            artifact_root=str(Path(request["artifact_root"]).resolve()),
            database=str(root / "selection.sqlite"),
            operation_id=plan["operation_id"],
            binding=binding,
            record=request["c_tasks"][-1]["record"],
        )
        if "d_tasks" in request:
            spec.update(
                d_tasks=request["d_tasks"],
                replay_expected=comparable(report["C"][-1]["prediction"]),
            )
        save(root / "COLD_REQUEST.json", spec)
        timeout = plan.get("cold_timeout_seconds", 120)
        require(
            type(timeout) in (int, float)
            and math.isfinite(timeout)
            and 0 < timeout <= 600,
            "cold timeout",
        )
        command = [
            sys.executable,
            "-m",
            "cell_experiments.adoption",
            "--recover",
            str(root / "COLD_REQUEST.json"),
            "--recover-sha256",
            digest(spec),
        ]
        cold_start = time.monotonic()
        try:
            child = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as error:
            save(
                root / "COLD_PROCESS.json",
                dict(
                    status="TIMEOUT",
                    seconds=time.monotonic() - cold_start,
                    stdout=str(error.stdout or ""),
                    stderr=str(error.stderr or ""),
                ),
            )
            raise EvidenceError(
                "INCOMPLETE", "cold process exceeded its budget"
            ) from error
        process = dict(
            returncode=child.returncode,
            stdout=child.stdout,
            stderr=child.stderr,
            seconds=time.monotonic() - cold_start,
        )
        save(root / "COLD_PROCESS.json", process)
        require(child.returncode == 0, "cold process failed; original logs retained")
        cold = json.loads(child.stdout)
        require(
            type(cold["pid"]) is int
            and cold["pid"] != os.getpid()
            and cold["ppid"] == os.getpid(),
            "cold process identity",
        )
        require(
            cold["selected_model_digest"] == selected
            and comparable(cold["prediction"])
            == comparable(report["C"][-1]["prediction"]),
            "cold prediction differs",
        )
        require(
            verify_manifest(manifest, request["artifact_root"]) == selected,
            "selected materials changed",
        )
        require(
            db.execute(
                "SELECT binding,selected FROM selections WHERE operation=?",
                (plan["operation_id"],),
            ).fetchone()
            == (binding, selected),
            "durable selection changed during execution",
        )
        report.update(
            status=decision,
            cold=cold,
            cold_wall_seconds=process["seconds"],
            cold_process_digest=digest(process),
            cold_scope="new process, same last-C inference input; no additional independent task",
            costs_complete=False,
            energy_joules=None,
        )
        if "d_tasks" in request:
            from .adoption_future import measured_costs

            require(
                cold.get("D") == read_json(root / "D_RECEIPTS.json")
                and len(cold["D"]) == len(request["d_tasks"]),
                "D receipts incomplete",
            )
            report.update(
                D=cold["D"],
                fresh_D_status="COMPLETE_ENGINEERING",
                cold_scope="new process; checked last-C replay followed by distinct frozen D tasks; independent provenance unauthenticated",
            )
            report["execution_costs"] = measured_costs(report)
    except FileNotFoundError as error:
        report.update(status="INCOMPLETE" if inserted else "BLOCKED", reason=str(error))
    except EvidenceError as error:
        report.update(status=error.status, reason=str(error))
    except Exception as error:
        report.update(status="FAILED", reason=f"{type(error).__name__}: {error}")
    finally:
        if predictor is not None:
            try:
                predictor.close()
            except Exception as error:
                report.update(
                    status="FAILED", cleanup_error=f"{type(error).__name__}: {error}"
                )
        report["wall_seconds"] = time.monotonic() - started
        if inserted:
            from .adoption_costs import collect, measured_costs

            report["inference_attempts"] = collect(root, sys.modules[__name__])
            report["execution_costs"] = measured_costs(report["inference_attempts"])
        if db is not None:
            if inserted:
                db.execute(
                    "UPDATE selections SET report=? WHERE operation=?",
                    (canonical(report).decode(), request["plan"]["operation_id"]),
                )
            db.close()
    save(
        root
        / (
            "RESULT.json"
            if inserted
            or not any(
                (root / name).exists()
                for name in ("RESULT.json", "ADMISSION.json", "selection.sqlite")
            )
            else f"ATTEMPT-{time.time_ns()}.json"
        ),
        report,
    )
    return json.loads(canonical(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recover", type=Path)
    parser.add_argument("--recover-sha256")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.recover:
        if not args.recover_sha256:
            parser.error("--recover-sha256 is required for a cold process")
        result = recover(read_json(args.recover), args.recover_sha256)
    else:
        if not args.input or not args.output:
            parser.error("--input and --output are required")
        result = execute(read_json(args.input), args.output)
    print(canonical(result).decode())


if __name__ == "__main__":
    main()
