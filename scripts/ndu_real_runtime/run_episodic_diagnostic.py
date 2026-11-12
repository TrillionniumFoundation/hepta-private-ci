"""Frozen MEM12 generated-task diagnostic, never MEM5/MEM9 or production admission.

Eight generated sources share one task template. A deterministic writer exits
before fresh reader/model processes. The ordinary reference is BM25; this does
not introduce a learned selector or claim an advantage over BM25 itself.
No authenticated-observer implementation, natural-task benefit, model update,
original native owner or cold-owner recovery is supplied by this experiment.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import sys
import time
import uuid

from .episodic_diagnostic_bindings import verify_writer
from .episodic_diagnostic_report import build_report, selected_text
from .episodic_isolation import run_isolated_actor
from .episodic_local_provider import LocalProviderProfile, run_local_provider
from .episodic_local_worker import WORKER
from .episodic_memory import EpisodicStore, canonical_bytes
from .episodic_provider_handoff import (
    _canonical,
    _read_regular,
    _sync_directory,
    _write,
)
from .episodic_retrieval import read_memory, verify_read_receipt

COLORS = ("red", "orange", "yellow", "green", "blue", "purple", "pink", "white")
ARMS = {
    "on_bm25": ("on", "bm25", None),
    "off": ("off", "bm25", None),
    "delete": ("on", "bm25", "delete"),
    "replace": ("on", "bm25", "replace"),
    "retrieval_off": ("retrieval_off", "bm25", None),
    "delivery_off": ("delivery_off", "bm25", None),
    "exact_kv": ("on", "exact_kv", None),
    "finite_icl": ("on", "icl", None),
    "uniform_replay": ("on", "uniform_replay", None),
    "retention_off": ("on", "bm25", "empty"),
}
ACTOR = b"""import json
from pathlib import Path
task = json.loads(Path("/input/task.json").read_bytes())
memory = Path("/input/memory.txt")
notes = [] if not memory.exists() else [json.loads(line)["text"]
 for line in memory.read_text().splitlines() if line]
prompt = ("Use only the saved dispatch memo to answer the question. "
 "If the memo does not contain the answer, reply UNKNOWN. "
 "Reply with one color word only.\\nSaved memo:\\n" + "\\n".join(notes)
 + "\\nQuestion: " + task["question"] + "\\nAnswer:")
print(json.dumps({"model": task["model"], "input": prompt, "store": False,
 "max_output_tokens": 32, "temperature": 0}, sort_keys=True,
 separators=(",", ":"), ensure_ascii=False, allow_nan=False))
"""
SOURCES = (
    "ndu_real_runtime/run_episodic_diagnostic.py",
    "ndu_real_runtime/episodic_diagnostic_report.py",
    "ndu_real_runtime/episodic_diagnostic_bindings.py",
    "ndu_real_runtime/episodic_memory.py",
    "ndu_real_runtime/episodic_retrieval.py",
    "ndu_real_runtime/episodic_receipt.py",
    "ndu_real_runtime/episodic_isolation.py",
    "ndu_real_runtime/episodic_local_provider.py",
    "ndu_real_runtime/episodic_local_worker.py",
    "ndu_real_runtime/episodic_provider_handoff.py",
    "hepta_ci_exec.py",
)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def save(path, value):
    _write(path, canonical_bytes(value))


def source_pins():
    scripts = Path(__file__).resolve().parents[1]
    return {name: pin((scripts / name).read_bytes()) for name in SOURCES}


_LOADED_SOURCES = source_pins()


def prepare(output, profile, cohort_id):
    """Freeze every case, arm, parser, model/runtime and source before generation."""
    if (
        not isinstance(cohort_id, str)
        or re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", cohort_id) is None
    ):
        raise ValueError("bounded filesystem-safe cohort identity required")
    profile = asdict(LocalProviderProfile(**profile))
    if source_pins() != _LOADED_SOURCES:
        raise ValueError("loaded experiment source changed")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(uuid.uuid4().hex)
    cases = []
    for index in range(8):
        facts = []
        for color in rng.sample(COLORS, 3):
            key = "parcel-" + rng.randbytes(6).hex()
            facts.append(
                {"key": key, "color": color, "text": f"{key} requires a {color} badge."}
            )
        target = rng.choice(facts)
        case_id = f"source-{index + 1:02d}"
        cases.append(
            {
                "case_id": case_id,
                "source_id": case_id,
                "facts": facts,
                "truth": target["color"],
                "replacement": COLORS[
                    (COLORS.index(target["color"]) + 1) % len(COLORS)
                ],
                "public_task": {
                    "model": profile["model_name"],
                    "key": target["key"],
                    "query": target["key"] + " badge color",
                    "question": f"What color badge must the courier use for {target['key']}?",
                },
                "replay_seed": rng.randrange(2**63),
                "arm_order": rng.sample(list(ARMS), len(ARMS)),
            }
        )
    plan = {
        "schema": "hepta.mem12.controlled-diagnostic.v1",
        "cohort_id": cohort_id,
        "registered_at_unix_ns": time.time_ns(),
        "profile": profile,
        "sources": source_pins(),
        "actor": pin(ACTOR),
        "provider_worker": pin(WORKER.encode()),
        "selector": "mem12-full-output-color-v1; independent of MEM5 OCR public_rule",
        "arms": {name: list(value) for name, value in ARMS.items()},
        "cases": cases,
        "limits": {
            "context_bytes": 2048,
            "retrieval_records": 2,
            "output_tokens": 32,
            "input_tokens": 1024,
            "provider_seconds": 60,
        },
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
        "source_kind": "generated arbitrary assignments; one shared task template",
        "writer_kind": "deterministic source ingestion; no A model call",
        "retention_off": "discard A retained state for this reader, not a saved A write cost",
        "replace": "wrong-fact intervention; original scoring truth stays fixed",
        "cost_policy": "equal limits, measured unequal costs; common A cost reported once",
    }
    _write(output / "ACTOR.py", ACTOR)
    save(output / "PLAN.json", plan)
    save(output / "PLAN_PIN.json", pin(canonical_bytes(plan)))
    return plan


def load_plan(output, check_sources=False):
    raw = _read_regular(output / "PLAN.json", 262144)
    if pin(raw) != json.loads(_read_regular(output / "PLAN_PIN.json", 1024)):
        raise ValueError("frozen plan changed")
    plan = json.loads(raw)
    if (
        plan["schema"] != "hepta.mem12.controlled-diagnostic.v1"
        or len(plan["cases"]) != 8
        or plan["arms"] != {name: list(value) for name, value in ARMS.items()}
        or pin(_read_regular(output / "ACTOR.py", 65536)) != plan["actor"]
    ):
        raise ValueError("frozen protocol changed")
    if check_sources and (
        plan["sources"] != source_pins() or plan["sources"] != _LOADED_SOURCES
    ):
        raise ValueError("execution source differs from frozen plan")
    return plan, pin(raw)["sha256"]


def writer(request_path):
    """A ingests source text; caller observes process exit before any C launch."""
    request = json.loads(request_path.read_bytes())
    store = EpisodicStore(
        request_path.parent / "authority.sqlite",
        namespace="mem12",
        max_records=16,
        max_serialized_bytes=32768,
    )
    case = request["case"]
    for fact in case["facts"]:
        store.put(
            case["source_id"],
            fact["key"],
            fact["text"],
            provenance={
                "source_uri": "generated://mem12/"
                + request["cohort_id"]
                + "/"
                + case["source_id"],
                "source_sha256": pin(fact["text"].encode())["sha256"],
                "source_version": "A-v1",
                "episode_id": case["case_id"] + "-A",
            },
        )
    store.export_snapshot(request_path.parent / "snapshot.json")
    print(
        json.dumps(
            {
                "pid": os.getpid(),
                "session_id": uuid.uuid4().hex,
                "snapshot": pin((request_path.parent / "snapshot.json").read_bytes()),
            }
        )
    )


def _writer_observation(output, plan, case):
    root = output / case["case_id"] / "writer"
    if root.exists():
        return (
            json.loads((root / "RECEIPT.json").read_bytes())
            if (root / "RECEIPT.json").exists()
            else {"status": "UNKNOWN"}
        )
    root.mkdir(parents=True)
    save(
        root / "REQUEST.json",
        {
            "case": {key: case[key] for key in ("case_id", "source_id", "facts")},
            "cohort_id": plan["cohort_id"],
        },
    )
    started = time.time_ns()
    scripts = str(Path(__file__).resolve().parents[1])
    command = [
        sys.executable,
        "-B",
        "-m",
        "ndu_real_runtime.run_episodic_diagnostic",
        "--writer",
        str(root / "REQUEST.json"),
    ]
    try:
        child = subprocess.run(
            command,
            env={**os.environ, "PYTHONPATH": scripts},
            capture_output=True,
            timeout=30,
            check=False,
        )
        _write(root / "stdout.bin", child.stdout)
        _write(root / "stderr.bin", child.stderr)
        receipt = {
            "status": "EXITED" if child.returncode == 0 else "FAILED",
            "returncode": child.returncode,
            "process": json.loads(child.stdout) if child.returncode == 0 else None,
        }
    except subprocess.TimeoutExpired as error:
        _write(root / "stdout.bin", error.stdout or b"")
        _write(root / "stderr.bin", error.stderr or b"")
        receipt = {"status": "TIMEOUT", "process": None}
    receipt.update(
        started_at_unix_ns=started,
        exited_at_unix_ns=time.time_ns(),
        wall_seconds=(time.time_ns() - started) / 1e9,
    )
    if receipt["status"] == "EXITED":
        receipt["database"] = pin((root / "authority.sqlite").read_bytes())
    save(root / "RECEIPT.json", receipt)
    return receipt


def reader_store(output, arm_root, plan, case, mutation):
    """Fork independent research worlds; this is not original-owner recovery."""
    target = arm_root / "authority.sqlite"
    if mutation != "empty":
        verify_writer(output, plan, case)
        source = output / case["case_id"] / "writer" / "authority.sqlite"
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as old:
            with sqlite3.connect(target) as new:
                old.backup(new)
        verify_writer(output, plan, case)
    store = EpisodicStore(
        target, namespace="mem12", max_records=16, max_serialized_bytes=32768
    )
    key = case["public_task"]["key"]
    if mutation == "delete":
        store.revoke(source_id=case["source_id"], key=key)
    elif mutation == "replace":
        text = f"{key} requires a {case['replacement']} badge."
        store.put(
            case["source_id"],
            key,
            text,
            provenance={
                "source_uri": "generated://mem12/wrong-fact-intervention",
                "source_sha256": pin(text.encode())["sha256"],
                "source_version": "counterfactual-v2",
                "episode_id": case["case_id"] + "-replace",
            },
        )
    return store


def run_arm(output, plan, plan_sha, case, arm, writer_receipt):
    root = output / case["case_id"] / arm
    if root.exists():
        return  # An interrupted arm is UNKNOWN; never create a replacement key.
    root.mkdir()
    _sync_directory(root.parent)
    row = {
        "case_id": case["case_id"],
        "arm": arm,
        "protocol_sha256": plan_sha,
        "status": "SETUP_FAILED",
        "physical_generations": 0,
        "request_id": ":".join((plan["cohort_id"], case["case_id"], arm)),
        "started_at_unix_ns": time.time_ns(),
        "correct": None,
    }
    save(root / "STARTED.json", row)
    try:
        if writer_receipt["status"] != "EXITED":
            row["status"] = "WRITER_UNAVAILABLE"
            return
        verify_writer(output, plan, case)
        mode, strategy, mutation = ARMS[arm]
        store = (
            None if mode == "off" else reader_store(output, root, plan, case, mutation)
        )
        row["reader_store_bytes"] = 0 if store is None else store.path.stat().st_size
        memory = read_memory(
            store,
            session_id=row["request_id"],
            source_ids=[case["source_id"]],
            query=case["public_task"]["query"],
            key=case["public_task"]["key"],
            mode=mode,
            strategy=strategy,
            limit=plan["limits"]["retrieval_records"],
            max_context_bytes=plan["limits"]["context_bytes"],
            seed=case["replay_seed"],
        )
        if not verify_read_receipt(memory):
            raise ValueError("memory delivery receipt mismatch")
        save(root / "MEMORY.json", memory)
        launch = run_isolated_actor(
            root / "actor",
            ACTOR,
            case["public_task"],
            mode="off" if mode == "off" else "on",
            memory_context=memory["context"],
        )
        row["actor_status"] = launch["status"]
        if launch["status"] != "EXECUTED":
            row["status"] = "ACTOR_UNAVAILABLE"
            return
        request = _read_regular(root / "actor" / "actor-output.bin", 65536)
        launch_raw = _read_regular(root / "actor" / "RECEIPT.json", 1048576)
        row["physical_generations"] = None
        provider_start = time.perf_counter()
        provider = run_local_provider(
            root / "provider",
            request,
            request_id=row["request_id"],
            launch_sha256=pin(launch_raw)["sha256"],
            profile=LocalProviderProfile(**plan["profile"]),
            timeout_seconds=plan["limits"]["provider_seconds"],
        )
        row["provider_wall_seconds_with_setup"] = time.perf_counter() - provider_start
        _write(root / "PROVIDER.json", _canonical(provider))
        row.update(
            status=provider["status"],
            provider_pin=pin(_canonical(provider)),
            memory_pin=pin((root / "MEMORY.json").read_bytes()),
            request_pin=pin(request),
        )
        if provider["status"] == "RETURNED":
            row["physical_generations"] = 1
            row["correct"] = (
                selected_text(provider["result"].get("text")) == case["truth"]
            )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        row.update(
            status="UNKNOWN" if row["physical_generations"] is None else "SETUP_FAILED",
            error=type(error).__name__ + ": " + str(error),
        )
    finally:
        row["ended_at_unix_ns"] = time.time_ns()
        row["wall_seconds"] = (
            row["ended_at_unix_ns"] - row["started_at_unix_ns"]
        ) / 1e9
        save(root / "ROW.json", row)


def report(output):
    output = Path(output).resolve()
    plan, plan_sha = load_plan(output)
    return build_report(output, plan, plan_sha)


def run(output):
    output = Path(output).resolve()
    plan, plan_sha = load_plan(output, check_sources=True)
    for case in plan["cases"]:
        observed = _writer_observation(output, plan, case)
        for arm in case["arm_order"]:
            run_arm(output, plan, plan_sha, case, arm, observed)
    result = report(output)
    if not (output / "REPORT.json").exists():
        save(output / "REPORT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "run", "report", "writer"):
        action.add_argument("--" + name, type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--cohort-id")
    args = parser.parse_args()
    if args.writer:
        writer(args.writer)
        return
    if args.prepare:
        if args.profile is None or args.cohort_id is None:
            parser.error("prepare requires --profile and --cohort-id")
        result = prepare(
            args.prepare, json.loads(args.profile.read_bytes()), args.cohort_id
        )
    else:
        result = run(args.run) if args.run else report(args.report)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
