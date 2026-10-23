"""Actual owner activation and fresh closed-schema population worker execution."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def fresh_read(
    model,
    version,
    questions,
    output,
    label,
    owner,
    frontier,
    write_json,
    *,
    context=None,
):
    """Actually activate/invoke an owner and run a fresh closed-schema worker.

    All version roots are admitted. Uncovered query outputs remain diagnostic;
    per-query authority is established separately by probe_eligibility.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", label):
        raise ValueError("bounded safe reader label required")
    if (
        type(questions) is not list
        or not 1 <= len(questions) <= 128
        or any(
            type(q) is not str or not 1 <= len(q.encode()) <= 4096 for q in questions
        )
    ):
        raise ValueError("bounded string-only reader queries required")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cwd = output / "reader-cwd"
    cwd.mkdir(exist_ok=True)
    context = json.loads(json.dumps(context or {}, allow_nan=False))
    active = owner.activate(
        label,
        version["directory"],
        version["manifest_sha256"],
        scope=frontier.scope,
        expected_current=None,
        generation=0,
        provider=lambda: frontier,
        allowed_roots=version["roots"],
    )
    if set(active.roots) != set(version["roots"]):
        raise ValueError("version roots must equal admitted active ancestry")
    write_json(
        output / f"{label}-activation.json",
        {
            "active_version": asdict(active),
            "context": context,
            "activated_unix_ns": time.time_ns(),
        },
    )
    request_path, journal_path = (
        output / f"{label}-request.json",
        output / f"{label}-journal.json",
    )

    def invoke(admitted):
        if admitted != active:
            raise ValueError("owner active version changed before worker construction")
        request = {
            "model": str(Path(model).resolve()),
            "snapshot": admitted.directory,
            "manifest_sha256": admitted.manifest_sha256,
            "scope": frontier.scope,
            "allowed_roots": list(admitted.roots),
            "questions": questions,
            "rank": version["rank"],
            "seed": version["seed"],
            "control": "adapter",
        }
        payload = json.dumps(request, sort_keys=True)
        if len(payload.encode()) > 128 * 1024:
            raise ValueError("reader request byte bound exceeded")
        request_sha256 = hashlib.sha256(payload.encode()).hexdigest()
        write_json(request_path, request)
        binding = {
            "context": context,
            "request_sha256": request_sha256,
            "active_version": asdict(admitted),
            "bound_unix_ns": time.time_ns(),
        }
        write_json(output / f"{label}-binding.json", binding)
        started_ns, started = time.time_ns(), time.perf_counter()
        worker = (
            Path(__file__).resolve().parents[1] / "memory_cell" / "parametric_worker.py"
        )
        completed = subprocess.run(
            [sys.executable, "-B", str(worker)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=600,
            check=False,
        )
        finished_ns, wall = time.time_ns(), time.perf_counter() - started
        (output / f"{label}-stdout.json").write_text(completed.stdout)
        (output / f"{label}-stderr.log").write_text(completed.stderr)
        if completed.returncode:
            raise RuntimeError(
                f"fresh reader {label} failed; retained stdout/stderr, exit {completed.returncode}"
            )
        journal = json.loads(completed.stdout)
        if (
            journal.get("schema") != "hepta.parametric-memory.read-journal.v1"
            or journal.get("control") != "adapter"
            or journal.get("request_sha256") != request_sha256
            or any(
                journal.get(key) is not False
                for key in (
                    "fact_input",
                    "retrieval_input",
                    "answer_lexicon_input",
                    "production_accepted",
                )
            )
            or journal.get("admitted_adapter_state_sha256")
            != journal.get("consumed_adapter_state_sha256")
        ):
            raise ValueError(
                "worker binding, input boundary, or immutable state mismatch"
            )
        rows = journal["rows"]
        if [r["question"] for r in rows] != questions or any(
            type(r.get("text")) is not str or r.get("answer_postprocessed") is not False
            for r in rows
        ):
            raise ValueError(
                "raw generation journal is not aligned with requested questions"
            )
        return {
            **journal,
            "fresh_process_wall_seconds": wall,
            "worker_started_unix_ns": started_ns,
            "worker_finished_unix_ns": finished_ns,
            "binding": binding,
        }

    journal = owner.invoke(
        label, frontier.scope, lambda: frontier, invoke, query_roots=active.roots
    )
    journal.update(
        owner_admitted_before_and_after=True,
        active_version=asdict(active),
        owner_query_roots=list(active.roots),
        rank=version["rank"],
        seed=version["seed"],
        request_path=str(request_path),
        journal_path=str(journal_path),
        uncovered_query_outputs_are_diagnostic=True,
    )
    write_json(journal_path, journal)
    return journal
