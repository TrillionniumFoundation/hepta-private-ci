"""Original-byte consistency for the generated diagnostic, not authentication."""

import json
import sqlite3

from .episodic_memory import canonical_bytes, digest, validate_record
from .episodic_provider_handoff import _canonical, _pin as pin, _read_regular


def verify_writer(output, plan, case):
    root = output / case["case_id"] / "writer"
    receipt = json.loads(_read_regular(root / "RECEIPT.json", 65536))
    request = _read_regular(root / "REQUEST.json", 65536)
    stdout = _read_regular(root / "stdout.bin", 65536)
    process = json.loads(stdout)
    database = _read_regular(root / "authority.sqlite", 1048576)
    snapshot = _read_regular(root / "snapshot.json", 65536)
    expected_request = {
        "case": {key: case[key] for key in ("case_id", "source_id", "facts")},
        "cohort_id": plan["cohort_id"],
    }
    if (
        request != canonical_bytes(expected_request)
        or receipt["status"] != "EXITED"
        or type(receipt["returncode"]) is not int
        or receipt["returncode"] != 0
        or receipt["process"] != process
        or pin(database) != receipt["database"]
        or pin(snapshot) != process["snapshot"]
        or type(process["pid"]) is not int
        or process["pid"] <= 0
        or not isinstance(process["session_id"], str)
        or not process["session_id"]
        or not plan["registered_at_unix_ns"]
        < receipt["started_at_unix_ns"]
        < receipt["exited_at_unix_ns"]
    ):
        raise ValueError("A writer custody or chronology changed")
    envelope = json.loads(snapshot)
    body = envelope["body"]
    records = [validate_record(record) for record in body["records"]]
    if (
        envelope["sha256"] != digest(body)
        or body["schema"] != "hepta.mem6.snapshot.v1"
        or body["namespace"] != "mem12"
        or body["generation"] != 3
        or len(records) != 3
    ):
        raise ValueError("A snapshot does not bind its original three facts")
    for sequence, (record, fact) in enumerate(zip(records, case["facts"]), 1):
        expected = {
            "namespace": "mem12",
            "source_id": case["source_id"],
            "key": fact["key"],
            "text": fact["text"],
            "version": 1,
            "write_sequence": sequence,
            "dependencies": [],
            "provenance": {
                "source_uri": "generated://mem12/"
                + plan["cohort_id"]
                + "/"
                + case["source_id"],
                "source_sha256": pin(fact["text"].encode())["sha256"],
                "source_version": "A-v1",
                "episode_id": case["case_id"] + "-A",
            },
        }
        if any(record[key] != value for key, value in expected.items()):
            raise ValueError("A retained facts differ from frozen source")
    with sqlite3.connect(
        (root / "authority.sqlite").as_uri() + "?mode=ro", uri=True
    ) as db:
        values = [
            json.loads(row[0]) for row in db.execute("SELECT payload FROM records")
        ]
        meta = json.loads(db.execute("SELECT value FROM meta WHERE id=1").fetchone()[0])
    if (
        sorted(values, key=lambda row: row["write_sequence"]) != records
        or meta["authority_id"] != body["authority_id"]
        or meta["generation"] != body["generation"]
    ):
        raise ValueError("A database and snapshot differ")
    return receipt


def verify_actor(root, plan, case, mode, delivered, writer):
    raw = _read_regular(root / "actor" / "RECEIPT.json", 1048576)
    launch = json.loads(raw)
    stdout = _read_regular(root / "actor" / "stdout.bin", 1048576)
    stderr = _read_regular(root / "actor" / "stderr.bin", 1048576)
    request = _read_regular(root / "actor" / "actor-output.bin", 65536)
    first, separator, actor_output = stdout.partition(b"\n")
    bootstrap = json.loads(first)
    names = {"mnt", "pid", "net", "ipc", "uts", "user"}
    if (
        launch["status"] != "EXECUTED"
        or type(launch["returncode"]) is not int
        or launch["returncode"] != 0
        or launch["source_unchanged"] is not True
        or launch["capture_truncated"] is not False
        or launch["input_transport"] != "sealed-memfd-ro-bind-data"
        or launch["launcher_sha256"]
        != plan["sources"]["ndu_real_runtime/episodic_isolation.py"]["sha256"]
        or launch["session_id"] == writer["process"]["session_id"]
        or launch["process_identity"]["launcher_pid"] == writer["process"]["pid"]
        or not writer["exited_at_unix_ns"]
        <= launch["started_at_unix_ns"]
        < launch["ended_at_unix_ns"]
        or separator != b"\n"
        or actor_output != request
        or bootstrap != launch["bootstrap"]
        or pin(stdout) != launch["stdout"]
        or pin(stderr) != launch["stderr"]
        or pin(request) != launch["actor_output"]
        or bootstrap["bootstrap"] != "hepta.mem9.namespace.v1"
        or any(
            bootstrap[key] is not True
            for key in ("home_empty", "cache_empty", "workspace_empty")
        )
        or set(bootstrap["namespaces"]) != names
        or set(launch["host_namespaces"]) != names
        or any(
            not isinstance(bootstrap["namespaces"][key], str)
            or bootstrap["namespaces"][key] == launch["host_namespaces"][key]
            for key in names
        )
    ):
        raise ValueError("C actor original bootstrap or A-to-C chronology changed")
    inputs = root / "actor" / "inputs"
    if (
        _read_regular(inputs / "task.json", 65536)
        != canonical_bytes(case["public_task"])
        or pin(_read_regular(inputs / "actor.py", 65536)) != plan["actor"]
    ):
        raise ValueError("C actor inputs differ from frozen source")
    if mode == "off":
        if (inputs / "memory.txt").exists() or delivered["context"]:
            raise ValueError("memory-off input is present")
    elif _read_regular(inputs / "memory.txt", 65536) != delivered["context"].encode():
        raise ValueError("actual actor memory input changed")
    return raw


def verify_admission(directory, provider, plan, request_id, launch_raw, request):
    dependencies = {
        name.rsplit("/", 1)[-1]: plan["sources"][name]
        for name in (
            "hepta_ci_exec.py",
            "ndu_real_runtime/episodic_provider_handoff.py",
            "ndu_real_runtime/episodic_local_worker.py",
        )
    }
    expected = {
        "schema": "hepta.mem11.local-provider.v1",
        "request_id": request_id,
        "launch_sha256": pin(launch_raw)["sha256"],
        "request": pin(request),
        "profile": plan["profile"],
        "worker": plan["provider_worker"],
        "timeout_seconds": plan["limits"]["provider_seconds"],
        "provider_source": plan["sources"][
            "ndu_real_runtime/episodic_local_provider.py"
        ],
        "dependency_sources": dependencies,
    }
    if _read_regular(directory / "ADMISSION.json", 65536) != _canonical(
        expected
    ) or any(provider.get(key) != value for key, value in expected.items()):
        raise ValueError("provider admission differs from frozen source or request")
