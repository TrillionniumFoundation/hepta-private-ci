#!/usr/bin/env python3
"""Linux two-node Cell transport of an owner-pinned real training result.

This verifies transport/receipt bindings, never grants installation or model
qualification. The caller supplies the input SHA and independently computed
TCM1 IDs before any pack command. No download metadata is a trust root.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import time

SCHEMA = "hepta-neural-candidate-transport-input-v1"
BINARY_SCHEMA = "hepta-neural-candidate-transport-binary-input-v2"
NAMES = ("artifact.safetensors", "target-contract.json", "wrapped-adapter.json")
CHUNK = 1048576
MAX_MEMBER = 2 * CHUNK
MAX_JSON = 4 * CHUNK
SECONDS = 35
CACHE = [
    "--cache-max-bytes",
    str(16 * CHUNK),
    "--cache-max-chunks",
    "64",
    "--cache-max-manifests",
    "16",
    "--cache-max-db-bytes",
    str(32 * CHUNK),
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def closed(value, keys):
    require(
        type(value) is dict and set(value) == set(keys.split()), "closed input fields"
    )


def digest(value):
    require(
        type(value) is str and re.fullmatch("[0-9a-f]{64}", value), "lowercase SHA256"
    )
    return value


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode(raw):
    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def read_regular(path, maximum):
    path = Path(path)
    require(path.is_absolute(), "absolute pinned path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            "bounded regular file",
        )
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(
            len(raw) == before.st_size
            and all(getattr(before, k) == getattr(after, k) for k in fields),
            "pinned file changed during read",
        )
    return raw


def pinned(pin, maximum=MAX_JSON):
    closed(pin, "path sha256")
    raw = read_regular(pin["path"], maximum)
    require(
        hashlib.sha256(raw).hexdigest() == digest(pin["sha256"]),
        "external raw file pin",
    )
    return raw


def semantic_id(tag, raw):
    name = tag.encode()
    return hashlib.sha256(
        b"TRNM-PON1\0"
        + struct.pack("<H", len(name))
        + name
        + struct.pack("<I", len(raw))
        + raw
    ).hexdigest()


def manifest_bytes(context, raw):
    closed(context, "family base parent tokenizer layout runtime")
    family = context["family"]
    require(
        type(family) is str and re.fullmatch("[A-Za-z0-9._-]{1,64}", family),
        "Cell family",
    )
    require(0 < len(raw) <= MAX_MEMBER, "original narrow material bound")
    body = b"TCM1" + bytes([len(family)]) + family.encode()
    body += b"".join(
        bytes.fromhex(digest(context[k]))
        for k in ("base", "parent", "tokenizer", "layout", "runtime")
    )
    chunks = [raw[start : start + CHUNK] for start in range(0, len(raw), CHUNK)]
    body += (
        struct.pack(">Q", len(raw))
        + hashlib.sha256(raw).digest()
        + struct.pack(">II", CHUNK, len(chunks))
    )
    return body + b"".join(
        struct.pack(">I", len(chunk)) + hashlib.sha256(chunk).digest()
        for chunk in chunks
    )


def manifest_id(context, raw):
    return hashlib.sha256(
        b"trnm.cell-manifest.v1\0" + manifest_bytes(context, raw)
    ).hexdigest()


def preflight(value):
    binary_training = type(value) is dict and value.get("schema") == BINARY_SCHEMA
    context_key = (
        "binary_observed_execution" if binary_training else "observation_execution"
    )
    suffix = "binary-observed-v2" if binary_training else "observed-v1"
    closed(
        value,
        "schema binary training completion parent child runtime context members "
        + context_key,
    )
    require(
        value["schema"] == (BINARY_SCHEMA if binary_training else SCHEMA),
        "explicit neural candidate transport profile",
    )
    records = {
        key: decode(pinned(value[key]))
        for key in ("training", "completion", "parent", "child")
    }
    pinned(value["runtime"])
    binary = pinned(value["binary"], 128 * CHUNK)
    require(
        binary.startswith(b"\x7fELF") and os.access(value["binary"]["path"], os.X_OK),
        "pinned Linux Cell ELF",
    )
    trained, completion, parent, child = (
        records[k] for k in ("training", "completion", "parent", "child")
    )
    for expected, item in ((1, parent), (2, child)):
        closed(
            item,
            "schema generation operation_id directory contract adapter file_sha256",
        )
        require(
            item["schema"] == "hepta-smollm-parent-material-v1"
            and type(item["generation"]) is int
            and item["generation"] == expected
            and Path(item["directory"]).is_absolute(),
            "actual original parent to generation-two child",
        )
        for key in ("contract", "adapter", "file_sha256"):
            digest(item[key])
    observation = value[context_key]
    fields = "plan_sha256 profile observer model_plan"
    if binary_training:
        fields += " recipe training_rows independent_source_rows row_exposures optimizer_steps"
    closed(observation, fields)
    require(
        observation["profile"]
        == (
            "canonical-positive-zero-binary-batch-observed-v2"
            if binary_training
            else "canonical-parent-original-task-observed-execution-v1"
        ),
        "original model plan and explicitly selected training observation",
    )
    for key in ("plan_sha256", "observer", "model_plan"):
        digest(observation[key])
    if binary_training:
        for key in ("recipe", "training_rows"):
            digest(observation[key])
        require(
            all(
                type(observation[key]) is int and observation[key] == expected
                for key, expected in (
                    ("independent_source_rows", 10),
                    ("row_exposures", 100),
                    ("optimizer_steps", 10),
                )
            ),
            "ten independent rows with exactly one hundred actual exposures",
        )
    require(
        trained["schema"] == "llm-runtime-parent-step-actual-" + suffix
        and trained["outcome"] == completion["outcome"] == "success"
        and trained["operation"] == "train"
        and trained["actual_backend"] == trained["actual_device"] == "cpu"
        and trained["training_changed_from_setup"] is True
        and completion["schema"] == "llm-runtime-parent-step-result-" + suffix
        and completion["completion_verified"] is True
        and completion["actual_receipt_sha256"] == value["training"]["sha256"]
        and completion["input"] == trained["input"]
        and completion["attempt_binding"] == trained["attempt_binding"]
        and trained[context_key] == completion[context_key] == observation,
        "actual source-bound training and completed original supervisor receipt",
    )
    supervisor = completion["supervisor"]
    require(
        supervisor["outcome"] == "success"
        and type(supervisor["exit_code"]) is int
        and supervisor["exit_code"] == 0
        and supervisor["stop_reason"] is None
        and supervisor["waited_child_reaped"] is True
        and supervisor["owned_child_reap_resolved"] is True
        and supervisor["owned_child_echild_observed"] is False
        and supervisor["waited_child_observation_error"] is None
        and supervisor["budget"] == {"wall_seconds": 1800, "rss_bytes": 16 * 1024**3}
        and supervisor["terminal_reconciliation_profile"]
        == "explicit-linux-owned-exit-worker-pidfd-v4",
        "unchanged real training budget and resolved owned process",
    )
    policy = supervisor["exit_observation_profile"]
    require(
        policy["profile"] == "linux-owned-exit-worker-pidfd-v4"
        and policy["maximum_drain_ns"] == 100000000
        and hashlib.sha256(canonical(policy)).hexdigest() == observation["observer"],
        "original 100ms policy pin",
    )
    require(
        trained["parent"]
        == {k: parent[k] for k in ("contract", "adapter", "file_sha256")}
        and trained["parent_readback"] == parent["adapter"]
        and child["contract"] == parent["contract"]
        and trained["candidate"] == {k: child[k] for k in ("adapter", "file_sha256")}
        and child["operation_id"] == trained["attempt_id"]
        and child["adapter"] != parent["adapter"]
        and child["file_sha256"] != parent["file_sha256"],
        "actual parent consumption and changed child bytes",
    )
    training = trained["training"]
    require(
        type(training["steps"]) is int
        and training["steps"] == 10
        and type(training["tokens"]) is int
        and type(training["supervised_tokens"]) is int
        and 0 < training["supervised_tokens"] <= training["tokens"],
        "original ten actual training steps",
    )
    require(
        type(trained["source"]) is dict
        and trained["source"]
        and all(digest(v) for v in trained["source"].values()),
        "bound original training source identities",
    )
    if binary_training:
        binary_work(value, trained, observation)
    require(
        type(value["members"]) is dict and set(value["members"]) == set(NAMES),
        "exact three downloaded members",
    )
    payloads = {}
    for name in NAMES:
        member = value["members"][name]
        closed(member, "path sha256 bytes manifest_id")
        require(
            Path(member["path"]) == Path(child["directory"]) / name,
            "candidate member directory binding",
        )
        raw = pinned({k: member[k] for k in ("path", "sha256")}, MAX_MEMBER)
        require(
            type(member["bytes"]) is int
            and len(raw) == member["bytes"]
            and manifest_id(value["context"], raw) == digest(member["manifest_id"]),
            "external exact TCM1 pin",
        )
        payloads[name] = raw
    contract, adapter = (decode(payloads[name]) for name in NAMES[1:])
    require(
        payloads[NAMES[1]] == canonical(contract)
        and payloads[NAMES[2]] == canonical(adapter)
        and semantic_id("target-decoder-adapter-contract-v1", payloads[NAMES[1]])
        == child["contract"]
        and semantic_id("wrapped-decoder-lora-material-v1", payloads[NAMES[2]])
        == child["adapter"]
        and adapter["contract"] == child["contract"]
        and value["members"][NAMES[0]]["sha256"] == child["file_sha256"],
        "original semantic and raw child IDs",
    )
    context = value["context"]
    require(
        context
        == {
            "family": "smollm2-135m-cpu-dev-v1",
            "base": contract["backbone"]["index_root"],
            "parent": child["file_sha256"],
            "tokenizer": contract["tokenizer"]["files_root"],
            "layout": child["contract"],
            "runtime": value["runtime"]["sha256"],
        },
        "actual consumer Cell context binds raw child, contract, backbone, tokenizer and worker",
    )
    return records, payloads


def binary_work(value, trained, context):
    """Bind the separate workload; the original completed trainer owns the trace."""
    training = trained["training"]
    objective = training["objective"]
    closed(
        objective,
        "profile execution recipe source_sha256 optimizer_steps microsteps independent_source_rows row_exposures answer_tokens eos_tokens actual_input_tokens trace same_work_as_legacy_ten_single_rows loss_scope",
    )
    require(
        objective["profile"] == context["profile"]
        and objective["execution"] == context
        and objective["recipe"] == context["recipe"]
        and objective["source_sha256"] == trained["source"]["binary_answer_observed"]
        and objective["same_work_as_legacy_ten_single_rows"] is False
        and objective["loss_scope"]
        == "ten-row-mean-two-original-answer-token-CE-gradient-per-optimizer-step",
        "separate binary objective and actual source binding",
    )
    for key, expected in (
        ("optimizer_steps", 10),
        ("microsteps", 100),
        ("independent_source_rows", 10),
        ("row_exposures", 100),
        ("answer_tokens", 100),
        ("eos_tokens", 0),
    ):
        require(
            type(objective[key]) is int and objective[key] == expected,
            "exact binary work counts",
        )
    require(
        type(objective["actual_input_tokens"]) is int
        and objective["actual_input_tokens"] == training["tokens"]
        and 100 <= training["tokens"] <= 12800
        and training["supervised_tokens"] == 100,
        "actual binary token accounting",
    )
    trace = objective["trace"]
    closed(trace, "path bytes sha256")
    require(
        Path(trace["path"])
        == Path(value["training"]["path"]).parent / "binary-training-trace-v2.jsonl"
        and type(trace["bytes"]) is int
        and 0 < trace["bytes"] <= CHUNK,
        "actual bounded training trace role",
    )
    raw = pinned({key: trace[key] for key in ("path", "sha256")}, CHUNK)
    require(len(raw) == trace["bytes"] and raw.endswith(b"\n"), "complete trace bytes")
    events = [decode(line) for line in raw.splitlines()]
    require(
        len(events) == 112
        and events[0]["event"] == "start"
        and events[0]["input"] == trained["input"]
        and events[0]["recipe"] == context["recipe"]
        and events[0]["plan_sha256"] == context["plan_sha256"]
        and events[0]["source"] == objective["source_sha256"]
        and sum(row["event"] == "microstep" for row in events) == 100
        and sum(row["event"] == "optimizer-step" for row in events) == 10
        and events[-1]["event"] == "complete"
        and events[-1]["optimizer_steps"] == 10
        and events[-1]["microsteps"] == 100
        and events[-1]["tokens"] == training["tokens"]
        and events[-1]["supervised_tokens"] == 100,
        "complete actual binary trace binding; not independent model qualification",
    )


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("shared 35 second transport budget exhausted")
    return value


def save_new(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def transport(value, output, input_sha256, deadline):
    output = Path(output)
    require(
        sys.platform.startswith("linux") and output.is_absolute(),
        "explicit Linux output",
    )
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    report = {
        "schema": (
            "hepta-neural-candidate-transport-binary-result-v2"
            if value["schema"] == BINARY_SCHEMA
            else "hepta-neural-candidate-transport-result-v1"
        ),
        "outcome": "failed",
        "input_sha256": digest(input_sha256),
        "installation_authority": False,
        "model_qualification": False,
        "commands": [],
        "members": {},
        "server": None,
    }
    server = None
    logs = []

    def command(label, args):
        remaining(deadline)
        out = (output / (label + ".stdout.log")).open("xb")
        err = (output / (label + ".stderr.log")).open("xb")
        start = time.monotonic_ns()
        with out, err:
            child = subprocess.Popen(
                [value["binary"]["path"], *args],
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
            )
            row = {"argv": [value["binary"]["path"], *args], "pid": child.pid}
            report["commands"].append(row)
            try:
                child.wait(timeout=remaining(deadline))
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=1)
                row.update(
                    returncode=child.returncode, elapsed_ns=time.monotonic_ns() - start
                )
        remaining(deadline)
        require(child.returncode == 0, "Cell command failed: " + label)
        return decode(read_regular(output / (label + ".stdout.log"), 65536))

    try:
        records, payloads = preflight(value)
        remaining(deadline)
        supplier, receiver = output / "supplier-node", output / "receiver-node"
        supplier.mkdir(mode=0o700)
        receiver.mkdir(mode=0o700)
        target = output / "downloaded"
        target.mkdir(mode=0o700)
        store, cache = supplier / "cells.sqlite3", receiver / "cells.sqlite3"
        for name in NAMES:
            member = value["members"][name]
            args = ["pack", "--store", str(store), *CACHE, "--input", member["path"]]
            for key in ("family", "base", "parent", "tokenizer", "layout", "runtime"):
                args += ["--" + key, value["context"][key]]
            packed = command("pack-" + name, args + ["--chunk-bytes", str(CHUNK)])
            require(
                packed
                == {
                    "schema": "trnm.cell.pack.v1",
                    "manifest": member["manifest_id"],
                    "payload_sha256": member["sha256"],
                    "bytes": member["bytes"],
                    "chunks": math.ceil(member["bytes"] / CHUNK),
                },
                "pack must match external owner pin",
            )
        logs = [
            (output / ("server." + channel + ".log")).open("xb")
            for channel in ("stdout", "stderr")
        ]
        serve = [
            value["binary"]["path"],
            "serve",
            "--store",
            str(store),
            "--bind",
            "127.0.0.1:0",
            "--seconds",
            str(max(1, math.floor(remaining(deadline)))),
            "--request-ms",
            "2000",
            "--max-connections",
            "256",
            "--bounded-workers",
            "1",
            "--max-served-bytes",
            str(2 * sum(len(raw) for raw in payloads.values()) + 6 * CHUNK),
        ]
        server = subprocess.Popen(
            serve, stdin=subprocess.DEVNULL, stdout=logs[0], stderr=logs[1]
        )
        report["server"] = {"pid": server.pid, "argv": serve, "reaped": False}
        while True:
            remaining(deadline)
            require(server.poll() is None, "actual supplier exited before readiness")
            raw = (output / "server.stdout.log").read_bytes()
            require(len(raw) <= 65536, "bounded supplier stdout")
            if b"\n" in raw:
                listen = decode(raw.split(b"\n", 1)[0])
                require(
                    listen["schema"] == "trnm.cell.listen.v1"
                    and re.fullmatch(r"127\.0\.0\.1:[1-9][0-9]{0,4}", listen["address"])
                    and int(listen["address"].split(":")[1]) <= 65535,
                    "actual loopback endpoint",
                )
                break
            time.sleep(min(0.005, remaining(deadline)))
        report["server"]["endpoint"] = listen["address"]
        for name in NAMES:
            member = value["members"][name]
            response_limit = 2 * member["bytes"] + 2 * CHUNK + 320
            overall_ms = math.floor(remaining(deadline) * 1000)
            require(
                overall_ms >= 10,
                "remaining shared deadline below native request minimum",
            )
            downloaded = command(
                "fetch-" + name,
                [
                    "fetch",
                    "--store",
                    str(cache),
                    *CACHE,
                    "--manifest",
                    member["manifest_id"],
                    "--peers",
                    listen["address"],
                    "--output",
                    str(target / name),
                    "--max-bytes",
                    str(member["bytes"]),
                    "--overall-ms",
                    str(overall_ms),
                    "--parallelism",
                    "1",
                    "--request-ms",
                    str(min(2000, overall_ms)),
                    "--max-connections",
                    "64",
                    "--max-response-bytes",
                    str(response_limit),
                ],
            )
            require(
                downloaded["schema"] == "trnm.cell.fetch.v1"
                and downloaded["manifest"] == member["manifest_id"]
                and downloaded["payload_sha256"] == member["sha256"]
                and downloaded["bytes"] == member["bytes"]
                and downloaded["cached_chunks"] == 0
                and downloaded["downloaded_bytes"] == member["bytes"]
                and downloaded["downloaded_chunks"]
                == math.ceil(member["bytes"] / CHUNK)
                and downloaded["suppliers"] == 1
                and 0 < downloaded["connection_attempts"] <= 64
                and downloaded["max_response_bytes"] == response_limit
                and 0 < downloaded["received_response_bytes"] <= response_limit,
                "real fresh-node download receipt",
            )
            require(
                read_regular(target / name, MAX_MEMBER) == payloads[name],
                "complete downloaded member bytes",
            )
            report["members"][name] = downloaded
        require(not store.samefile(cache), "independent node databases")
        preflight(
            value
        )  # Original pins and source bytes must still match after transport.
        report.update(
            outcome="success",
            receiver=str(receiver),
            downloaded_directory=str(target),
            parent=records["parent"],
            child=records["child"],
            context=value["context"],
            training_receipt_sha256=value["training"]["sha256"],
            **{
                (
                    "binary_observed_execution"
                    if value["schema"] == BINARY_SCHEMA
                    else "observation_execution"
                ): value[
                    "binary_observed_execution"
                    if value["schema"] == BINARY_SCHEMA
                    else "observation_execution"
                ]
            },
            same_host=True,
            independent_nodes=2,
        )
        remaining(deadline)
    except Exception as error:
        report.update(outcome="failed", error=f"{type(error).__name__}: {error}")
    finally:
        if server is not None:
            if server.poll() is None:
                server.terminate()
            try:
                server.wait(timeout=max(0.001, min(1, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=1)
            report["server"].update(returncode=server.returncode, reaped=True)
        for stream in logs:
            stream.close()
        if time.monotonic() > deadline:
            report.update(
                outcome="failed",
                error="shared 35 second deadline exceeded including cleanup",
            )
        save_new(output / "transport-result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--expected-input-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    deadline = time.monotonic() + SECONDS
    value = decode(pinned({"path": args.input, "sha256": args.expected_input_sha256}))
    report = transport(value, args.output, args.expected_input_sha256, deadline)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["outcome"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
