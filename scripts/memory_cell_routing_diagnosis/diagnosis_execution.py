"""Fresh raw decoder observations and actual frozen learned-parent features."""

import gc
from importlib.metadata import version as package_version
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from diagnosis_common import canonical, configure, file_sha, retain


def cpu_snapshot():
    try:
        import resource
    except ImportError:
        return {"parent_cpu_seconds": time.process_time(), "child_cpu_seconds": None}
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "parent_cpu_seconds": time.process_time(),
        "child_cpu_seconds": children.ru_utime + children.ru_stime,
    }


def cpu_delta(before):
    after = cpu_snapshot()
    return {
        name: after[name] - value if value is not None else None
        for name, value in before.items()
    }


def runtime():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: package_version(name)
            for name in (
                "torch",
                "transformers",
                "peft",
                "numpy",
                "safetensors",
                "tokenizers",
            )
        },
    }


def partial_work(output):
    """Failure ledger distinguishes submitted queries from retained actual rows."""
    submitted = visible = admitted = input_tokens = generated_tokens = 0
    for request_path in sorted(Path(output).rglob("*-request.json")):
        request = json.loads(request_path.read_text())
        if request.get("control") != "adapter":
            continue
        submitted += len(request["questions"])
        stem = request_path.name.removesuffix("-request.json")
        journal_path = request_path.with_name(stem + "-journal.json")
        raw_path = request_path.with_name(stem + "-stdout.json")
        try:
            journal = json.loads(
                (journal_path if journal_path.exists() else raw_path).read_text()
            )
        except (OSError, ValueError):
            continue
        rows = journal.get("rows", [])
        if [row.get("question") for row in rows] != request["questions"]:
            continue
        visible += len(rows)
        admitted += (
            len(rows) if journal.get("owner_admitted_before_and_after") is True else 0
        )
        input_tokens += sum(row["input_tokens"] for row in rows)
        generated_tokens += sum(row["generated_tokens"] for row in rows)
    features = [
        json.loads(path.read_text())
        for path in Path(output).glob("seed-*/parent-features/worker/receipt.json")
    ]
    feature_requested = sum(
        len(json.loads(path.read_text())["questions"])
        for path in Path(output).glob("seed-*/parent-features/request.json")
    )
    feature_visible = sum(value["model_forwards"] for value in features)
    return {
        "decoder_queries_submitted": submitted,
        "decoder_raw_rows_visible": visible,
        "decoder_rows_with_completed_owner_checks": admitted,
        "visible_input_tokens": input_tokens,
        "visible_generated_tokens": generated_tokens,
        "parent_feature_forwards_requested": feature_requested,
        "parent_feature_forwards_visible": feature_visible,
        "unretained_work_may_have_occurred_before_process_failure": submitted > visible
        or feature_requested > feature_visible,
        "exact_total_model_work_known_after_failure": False,
    }


def retain_timeout(error, output, prefix):
    for name, payload in (("stdout.json", error.output), ("stderr.log", error.stderr)):
        if isinstance(payload, str):
            payload = payload.encode()
        (Path(output) / (prefix + name)).write_bytes(payload or b"")
    retain(
        Path(output) / (prefix + "timeout.json"),
        {
            "timeout_seconds": error.timeout,
            "partial_streams_retained": True,
            "unobserved_model_work_possible": True,
            "automatic_retry": False,
        },
    )


def fresh_rows(model, version, questions, output, label, scope, *, context=None):
    from parametric_owner import Frontier, ParametricOwner
    from population_worker import fresh_read

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    owner = ParametricOwner(output / "owner.sqlite")
    frontier = Frontier(scope, 1, ())
    rows, journals, before, started = [], [], cpu_snapshot(), time.perf_counter()
    for batch, offset in enumerate(range(0, len(questions), 128)):
        try:
            journal = fresh_read(
                model,
                version,
                questions[offset : offset + 128],
                output,
                f"{label}-{batch:02d}",
                owner,
                frontier,
                retain,
                context={
                    "phase": "causal_development_diagnosis",
                    "decoder_weights_fixed": True,
                    **(context or {}),
                },
            )
        except subprocess.TimeoutExpired as error:
            retain_timeout(error, output, f"{label}-{batch:02d}-")
            raise
        rows.extend(journal["rows"])
        journals.append(
            {
                "path": journal["journal_path"],
                "sha256": file_sha(journal["journal_path"]),
                "fresh_process_wall_seconds": journal["fresh_process_wall_seconds"],
            }
        )
    cost = {
        "queries": len(rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "generated_tokens": sum(r["generated_tokens"] for r in rows),
        "generation_seconds": sum(r["seconds"] for r in rows),
        "wall_seconds": time.perf_counter() - started,
        "fresh_processes": len(journals),
        **cpu_delta(before),
    }
    receipt = {
        "version": version,
        "journals": journals,
        "cost": cost,
        "gold_or_source_values_in_reader_request": False,
    }
    retain(output / "receipt.json", receipt)
    return rows, receipt


def parent_features(repo, model, version, questions, output, scope):
    """A short-lived process releases all parent tensors before final readers."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    request = {
        "repo": str(Path(repo).resolve()),
        "model": model,
        "version": version,
        "questions": questions,
        "output": str(output / "worker"),
        "scope": scope,
    }
    payload = canonical(request)
    if len(payload) > 128 * 1024 or len(questions) != 424:
        raise ValueError("registered bounded parent feature request required")
    retain(output / "request.json", request)
    before, started = cpu_snapshot(), time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve())],
            input=payload,
            capture_output=True,
            cwd=output,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        retain_timeout(error, output, "")
        raise
    (output / "stdout.json").write_bytes(completed.stdout)
    (output / "stderr.log").write_bytes(completed.stderr)
    if completed.returncode:
        raise RuntimeError(
            f"parent feature worker failed; retained stdout/stderr, exit {completed.returncode}"
        )
    receipt = json.loads(completed.stdout)
    destination = Path(receipt["path"])
    if (
        receipt["model_forwards"] != len(questions)
        or receipt["optimizer_updates"] != 0
        or receipt["version"] != version
        or receipt["adapter_enabled"] is not True
        or destination != output / "worker/parent-features.npy"
        or file_sha(destination) != receipt["sha256"]
        or [row["question"] for row in receipt["prompts"]] != questions
    ):
        raise ValueError(
            "parent worker request, feature file or model receipt mismatch"
        )
    vectors = np.load(destination, allow_pickle=False)
    if list(vectors.shape) != receipt["shape"] or not np.isfinite(vectors).all():
        raise ValueError("finite parent feature matrix with declared shape required")
    receipt["worker_cost"] = {
        key: receipt[key]
        for key in ("wall_seconds", "parent_cpu_seconds", "child_cpu_seconds")
    }
    receipt.update(
        wall_seconds=time.perf_counter() - started,
        **cpu_delta(before),
        worker_process_exited=True,
        feature_worker_processes=1,
        request_sha256=file_sha(output / "request.json"),
    )
    retain(output / "receipt.json", receipt)
    return vectors, receipt


def _encode_parent_features(model, version, questions, output, scope):
    """Encode question prompts using the actual trained parent, with no updates."""
    import torch
    from experience_inference import frozen_adapter_mode
    from native import digest
    from parametric_model import SourceMemoryCell, adapter_digest
    from parametric_owner import Frontier, ParametricOwner
    from pretrained import frozen_digest

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    owner = ParametricOwner(output / "owner.sqlite")
    frontier = Frontier(scope, 1, ())
    active = owner.activate(
        "parent-features",
        version["directory"],
        version["manifest_sha256"],
        scope=scope,
        expected_current=None,
        generation=0,
        provider=lambda: frontier,
        allowed_roots=version["roots"],
    )
    before, started = cpu_snapshot(), time.perf_counter()

    def encode(selected):
        if selected != active:
            raise ValueError("parent version changed")
        torch.set_num_threads(2)
        cell = SourceMemoryCell(model, rank=version["rank"], seed=version["seed"])
        cell.load(
            selected.directory,
            expected_manifest_sha256=selected.manifest_sha256,
            scope=scope,
            allowed_roots=set(selected.roots),
            revoked=set(),
        )
        adapter_before = adapter_digest(cell.reader.model)
        vectors, tokens, prompts = [], 0, []
        forward_start = time.perf_counter()
        for question in questions:
            ids = cell.prompt_ids(question)
            x = torch.tensor([ids], dtype=torch.long)
            with frozen_adapter_mode(cell.reader.model, enabled=True):
                result = cell.reader.model(
                    input_ids=x,
                    attention_mask=torch.ones_like(x),
                    output_hidden_states=True,
                    use_cache=False,
                )
                vectors.append(
                    result.hidden_states[-1][0].float().mean(dim=0).cpu().numpy().copy()
                )
            tokens += len(ids)
            prompts.append(
                {
                    "question": question,
                    "prompt_sha256": digest(ids),
                    "input_tokens": len(ids),
                }
            )
        if (
            adapter_digest(cell.reader.model) != adapter_before
            or frozen_digest(cell.reader.model) != cell.reader.base_digest
        ):
            raise ValueError("feature extraction changed parent parameters")
        receipt = {
            "model_forwards": len(questions),
            "input_tokens": tokens,
            "forward_seconds": time.perf_counter() - forward_start,
            "adapter_enabled": True,
            "adapter_state_sha256": adapter_before,
            "base_identity": cell.reader.identity,
            "optimizer_updates": 0,
            "feature_recipe": "final-hidden-state-full-prompt-mean",
            "prompts": prompts,
        }
        values = np.stack(vectors)
        del cell
        gc.collect()
        return values, receipt

    vectors, receipt = owner.invoke("parent-features", scope, lambda: frontier, encode)
    destination = output / "parent-features.npy"
    np.save(destination, vectors, allow_pickle=False)
    receipt.update(
        version=version,
        path=str(destination),
        sha256=file_sha(destination),
        bytes=destination.stat().st_size,
        shape=list(vectors.shape),
        wall_seconds=time.perf_counter() - started,
        **cpu_delta(before),
    )
    retain(output / "receipt.json", receipt)
    return vectors, receipt


if __name__ == "__main__":
    payload = sys.stdin.buffer.read(128 * 1024 + 1)
    request = json.loads(payload)
    if (
        len(payload) > 128 * 1024
        or set(request) != {"repo", "model", "version", "questions", "output", "scope"}
        or type(request["questions"]) is not list
        or len(request["questions"]) != 424
        or any(
            type(q) is not str or not 1 <= len(q.encode()) <= 4096
            for q in request["questions"]
        )
    ):
        raise ValueError("closed bounded parent-feature request required")
    output = Path(request["output"]).resolve()
    if Path(__file__).resolve().parent not in output.parents:
        raise ValueError("feature evidence must stay in the diagnosis directory")
    configure(request["repo"])
    _, receipt = _encode_parent_features(
        request["model"],
        request["version"],
        request["questions"],
        output,
        request["scope"],
    )
    print(json.dumps(receipt, sort_keys=True))
