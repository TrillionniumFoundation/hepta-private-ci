"""Cold bounded subprocesses and byte pins for the registered event stream."""

from dataclasses import asdict
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

from evolution_common import digest, file_digest, read_json, require, retain
from longitudinal_protocol import BASE_IDENTITY, BASELINE

LOCAL_SOURCE = [
    "evolution_common.py",
    "longitudinal_protocol.py",
    "longitudinal_campaign.py",
    "longitudinal_scoring.py",
    "longitudinal_runtime.py",
    "longitudinal_trial.py",
    "longitudinal_runner.py",
    "topology_contract.py",
    "topology_owner.py",
    "topology_store.py",
]
BASE_FILES = [
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
]


def source_identity(repo):
    repo = Path(repo).resolve()
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    require(head == BASELINE, "wrong baseline revision")
    original = {
        str(p.relative_to(repo)): file_digest(p)
        for p in sorted((repo / "scripts").glob("memory_cell*/*.py"))
    }
    local = {name: file_digest(Path(__file__).parent / name) for name in LOCAL_SOURCE}
    return dict(baseline=head, repository_files=original, local_files=local)


def pin_start(repo, model, output, protocol, campaign_sha):
    source = source_identity(repo)
    inventory = {
        name: dict(
            bytes=(model / name).stat().st_size, sha256=file_digest(model / name)
        )
        for name in BASE_FILES
    }
    require(digest(inventory) == BASE_IDENTITY, "publisher base inventory mismatch")
    environment = {
        d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
    }
    retain(output / "source-identity.json", source)
    retain(output / "base-inventory.json", inventory)
    retain(
        output / "runtime-versions.json",
        dict(python=sys.version, executable=sys.executable, distributions=environment),
    )
    retain(output / "protocol.json", protocol)
    for name in source["local_files"]:
        target = output / "source-snapshot" / "driver" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((Path(__file__).parent / name).read_bytes())
    for name in source["repository_files"]:
        target = output / "source-snapshot" / "baseline" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((repo / name).read_bytes())
    retain(
        output / "start.json",
        dict(
            campaign_sha256=campaign_sha,
            protocol_sha256=digest(protocol),
            source_identity_sha256=digest(source),
            started_unix_ns=time.time_ns(),
            base_identity=BASE_IDENTITY,
            model_invocation_started=False,
        ),
    )
    return source


def imports(repo):
    for name in ("memory_cell", "memory_cell_service", "memory_cell_network"):
        sys.path.insert(0, str(repo / "scripts" / name))
    from memory_service import MemoryService
    from model_process import run_child, run_decoder

    require(
        Path(sys.modules["memory_service"].__file__).resolve().parent
        == repo / "scripts/memory_cell_service",
        "wrong memory service import",
    )
    return MemoryService, run_child, run_decoder


def train(service, model, output, label, steps, protocol, repo, run_child):
    arguments = [
        "--root",
        str(service.root),
        "--scope",
        service.store.scope,
        "--cell-id",
        service.store.cell_id,
        "--role",
        service.store.role,
        "--base",
        str(model),
        "--steps",
        str(steps),
        "--rank",
        str(protocol["rank"]),
        "--seed",
        str(protocol["seed"]),
        "--learning-rate",
        str(protocol["learning_rate"]),
        "--once",
    ]
    receipt = run_child(
        repo / "scripts/memory_cell_service/training_worker.py",
        arguments,
        timeout=protocol["runtime_limits"]["train_timeout_seconds"],
        receipt_dir=output / "processes",
        operation="longitudinal-trainer",
    )
    retain(output / (label + ".process.json"), receipt)
    return json.loads(receipt["stdout"])


def wait_candidate(service, job_id, future):
    started = time.monotonic_ns()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        row = service.queue.status(job_id)
        directories = list(service.artifacts.glob(f"job-{job_id}-attempt-*"))
        if row and row["state"] == "running" and directories:
            require(not future.done(), "trainer ended before adversarial event")
            return dict(
                job_id=job_id,
                status=row["state"],
                candidate_directory=str(directories[0]),
                observed_monotonic_ns=time.monotonic_ns(),
                wait_ns=time.monotonic_ns() - started,
            )
        if future.done():
            future.result()
            raise RuntimeError(
                "no running candidate directory before trainer completion"
            )
        time.sleep(0.02)
    raise TimeoutError("background candidate construction not observed")


def apply_events(service, events):
    records = []
    for item in events:
        started = time.monotonic_ns()
        if item["kind"] == "write":
            receipt = service.write(
                item["source_id"], item["entity"], item["relation"], item["value"]
            )
        elif item["kind"] == "correct":
            receipt = service.correct(
                item["source_id"], item["value"], item["expected_revision"]
            )
        else:
            require(item["kind"] == "revoke", "unregistered source event")
            receipt = service.revoke(item["source_id"], item["expected_revision"])
        read = service.read(item["entity"], item["relation"])
        records.append(
            dict(
                event=item,
                receipt=asdict(receipt),
                immediate_overlay=asdict(read),
                started_monotonic_ns=started,
                finished_monotonic_ns=time.monotonic_ns(),
            )
        )
    return records


def background_job(records):
    require(
        records and records[-1]["receipt"]["training_job_id"] is not None,
        "source event did not enqueue background training",
    )
    return records[-1]["receipt"]["training_job_id"]


def deny_dirty_reads(service, entities):
    calls, rows = [], []
    for entity in sorted(set(entities) | {"unregistered-entity"}):
        response = service.invoke_parameter(
            entity, "color", "Return the stored color.", lambda *_: calls.append(entity)
        )
        rows.append(dict(entity=entity, result=response))
    require(
        not calls
        and all(
            r["result"]["status"] in ("unavailable", "unknown", "revoked", "conflict")
            for r in rows
        ),
        "dirty typed admission invoked a model",
    )
    return dict(rows=rows, model_callbacks=len(calls))


def read_panel(
    store,
    cell_id,
    snapshot,
    questions,
    model,
    output,
    label,
    control,
    protocol,
    run_decoder,
):
    selected = store.snapshot()["cells"][cell_id]
    request = dict(
        model=str(model),
        snapshot=selected["directory"],
        manifest_sha256=selected["manifest_sha256"],
        scope=snapshot["scope"],
        allowed_roots=selected["roots"],
        questions=questions,
        rank=protocol["rank"],
        seed=protocol["seed"],
        control=control,
    )
    retain(output / (label + ".request.json"), request)
    cwd = output / "reader-cwd"
    cwd.mkdir(exist_ok=True)
    journal = store.invoke(
        cell_id,
        [f["source_digest"] for f in snapshot["facts"]],
        lambda _: run_decoder(
            request,
            timeout=protocol["runtime_limits"]["read_timeout_seconds"],
            cwd=cwd,
            receipt_dir=output / "processes",
        ),
    )
    retain(output / (label + ".journal.json"), journal)
    return journal


def costs(output):
    training = [
        read_json(p)["training"]
        for p in sorted(
            (output / "source-owner/artifacts").glob("*/checkpoint/lineage.json")
        )
    ]
    children = [read_json(p) for p in sorted(output.rglob("*.stderr.result.json"))]
    rows, unknown = [], []
    for child in children:
        try:
            value = json.loads(child["stdout"])
        except (ValueError, TypeError):
            unknown.append(dict(pid=child["pid"], receipt_path=child["receipt_path"]))
            continue
        if value.get("schema") == "hepta.parametric-memory.read-journal.v1":
            rows.extend(value["rows"])
    return dict(
        saved_training_attempts=len(training),
        saved_optimizer_updates=sum(t["steps"] for t in training),
        saved_training_input_tokens=sum(t["input_tokens"] for t in training),
        saved_training_seconds=sum(t["seconds"] for t in training),
        retained_child_receipts=len(children),
        unique_child_pids=sorted({c["pid"] for c in children}),
        counted_raw_rows=len(rows),
        decoder_input_tokens=sum(r["input_tokens"] for r in rows),
        generated_tokens=sum(r["generated_tokens"] for r in rows),
        generation_seconds=sum(r["seconds"] for r in rows),
        child_wall_seconds=sum(c["wall_seconds"] for c in children),
        incomplete_stdout=unknown,
        retained_bytes_before_result=sum(
            p.stat().st_size for p in output.rglob("*") if p.is_file()
        ),
        failed_attempt_totals_are_lower_bounds=True,
        duplicated_embedded_receipts_counted=False,
    )
