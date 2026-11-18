"""Bounded two-stage A-only calls to the user's existing local teacher service."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

WEIGHT = "/home/qq/local-llm/models/Qwen3.8-Flash-Next-Uncensored-IQ4XS-NGQ4.gguf"
WEIGHT_SHA256 = "cedf1e08063f6df77926e1169f67b327dcc6301b5b329589615bdf09d4895f7e"
ALIAS = "qwen38-flash-next-uc"
URL = "http://127.0.0.1:8080"


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


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def require(value, message):
    if not value:
        raise ValueError(message)


def stat_identity(path):
    s = path.stat()
    return {
        "device": s.st_dev,
        "inode": s.st_ino,
        "size": s.st_size,
        "mtime_ns": s.st_mtime_ns,
        "ctime_ns": s.st_ctime_ns,
    }


def existing_server():
    matches = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            argv = [
                x.decode() for x in (path / "cmdline").read_bytes().split(b"\0") if x
            ]
            if (
                argv
                and Path(argv[0]).name == "llama-server"
                and WEIGHT in argv
                and "--port" in argv
                and argv[argv.index("--port") + 1] == "8080"
            ):
                matches.append((path, argv))
        except (OSError, UnicodeDecodeError):
            continue
    require(len(matches) == 1, "one already configured teacher service required")
    process, argv = matches[0]
    credential = None
    if "--api-key-file" in argv:
        path = Path(argv[argv.index("--api-key-file") + 1])
        require(
            path.stat().st_size <= 65536, "configured credential file exceeds bound"
        )
        lines = [
            x.strip()
            for x in path.read_text().splitlines()
            if x.strip() and not x.lstrip().startswith("#")
        ]
        credential = lines[0] if lines else None
    elif "--api-key" in argv:
        credential = argv[argv.index("--api-key") + 1].split(",")[0]
    require(bool(credential), "existing configured client authentication required")
    executable = (process / "exe").resolve(strict=True)
    identity = {
        "pid": int(process.name),
        "executable": str(executable),
        "executable_sha256": file_sha(executable),
        "process_start_ticks": (process / "stat")
        .read_text()
        .rsplit(") ", 1)[1]
        .split()[19],
    }
    return identity, credential


def request(route, credential, payload=None):
    headers = {"Authorization": "Bearer " + credential}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    call = urllib.request.Request(
        URL + route,
        headers=headers,
        data=None if payload is None else canonical(payload),
    )
    with urllib.request.urlopen(call, timeout=180) as response:
        raw = response.read(1048577)
        require(len(raw) <= 1048576, "server response exceeds bound")
        return json.loads(raw)


def idle(credential):
    slots = request("/slots", credential)
    require(
        isinstance(slots, list) and slots, "observable existing server slots required"
    )
    summary = [
        {key: row.get(key) for key in ("id", "is_processing", "id_task", "n_ctx")}
        for row in slots
    ]
    require(
        all(row["is_processing"] is False for row in summary),
        "another existing workload is active; no new model request sent",
    )
    return summary


def main(stage, root, run, commit):
    records = read(root / "A_RECORDS.json")
    require(
        len(records) == 6
        and all(
            row["split"] == "train" and row["authorization"]["training_allowed"]
            for row in records
        ),
        "only the original six authorized A tasks may be sent",
    )
    require(
        digest(records)
        == "f3206c37a200890561b47b3823a39a5419189d06861c161f5c92ca7de5c6d644",
        "original A source differs",
    )
    weight = read(root / "WEIGHT_IDENTITY.json")
    require(
        weight["hash_recomputed"]
        and weight["sha256"] == WEIGHT_SHA256
        and stat_identity(Path(WEIGHT)) == weight["file_identity"],
        "weight bytes or identity changed",
    )
    server, credential = existing_server()
    protocol = read(root / "PROTOCOL.json")
    if stage == "first":
        run.mkdir(exist_ok=False)
        properties = request("/props", credential)
        models = request("/v1/models", credential)
        require(
            properties["model_path"] == WEIGHT and properties["model_alias"] == ALIAS,
            "actual existing teacher model differs",
        )
        require(
            any(row["id"] == ALIAS for row in models["data"]), "model listing differs"
        )
        freeze = {
            "schema": "hepta.local-teacher-freeze.v1",
            "source_commit": commit,
            "script_sha256": file_sha(Path(__file__)),
            "protocol": protocol,
            "records_digest": digest(records),
            "weight_identity": weight,
            "server": server,
            "model_listing": models,
            "chat_template_sha256": hashlib.sha256(
                properties["chat_template"].encode()
            ).hexdigest(),
            "slots_before": idle(credential),
            "created_at_ns": time.time_ns(),
            "security_configuration_changed": False,
            "credentials_retained": False,
        }
        write(run / "FREEZE.json", freeze)
    else:
        freeze = read(run / "FREEZE.json")
        require(
            read(run / "FIRST_COMPLETE.json")["model_calls"] == 6,
            "complete first-stage original outputs required",
        )
        require(
            freeze["server"] == server
            and freeze["protocol"] == protocol
            and freeze["script_sha256"] == file_sha(Path(__file__)),
            "frozen service or protocol changed",
        )
    directory = run / stage
    directory.mkdir(exist_ok=False)
    started, completed, requests_sent = time.perf_counter(), [], 0
    try:
        for index, record in enumerate(records):
            require(
                existing_server()[0] == freeze["server"],
                "existing service identity changed",
            )
            require(
                stat_identity(Path(WEIGHT))
                == freeze["weight_identity"]["file_identity"],
                "frozen weight source changed",
            )
            slots_before = idle(credential)
            messages = record["task"].get("messages") or [
                {"role": "user", "content": record["task"]["input"]}
            ]
            if stage == "second":
                previous = read(run / "first" / f"OUTPUT-{index}.json")
                verification = read(root / "FIRST_VERIFICATIONS.json")[index]
                require(
                    verification["record_id"] == record["record_id"]
                    and verification["answer_sha256"]
                    == hashlib.sha256(previous["answer"].encode()).hexdigest()
                    and verification["verifier_source_sha256"]
                    == protocol["verifier_source_sha256"],
                    "feedback is not bound to the actual first teacher output",
                )
                feedback = read(root / "FIRST_FEEDBACK.json")[index]
                require(
                    feedback["verification_digest"] == digest(verification),
                    "feedback binding differs",
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": previous["answer"]},
                    {"role": "tool", "content": feedback["content"]},
                ]
            wire = [
                {
                    "role": "user" if row["role"] == "tool" else row["role"],
                    "content": ("Tool observation:\n" if row["role"] == "tool" else "")
                    + row["content"],
                }
                for row in messages
            ]
            payload = {
                "model": ALIAS,
                "messages": wire,
                **protocol["request_parameters"],
            }
            write(
                directory / f"REQUEST-{index}.json",
                {
                    "record_id": record["record_id"],
                    "logical_messages": messages,
                    "payload": payload,
                    "slots_before": slots_before,
                },
            )
            tick = time.perf_counter()
            requests_sent += 1
            raw = request("/v1/chat/completions", credential, payload)
            elapsed = time.perf_counter() - tick
            write(
                directory / f"RAW_RESPONSE-{index}.json",
                {
                    "raw_response": raw,
                    "wall_seconds": elapsed,
                    "request_digest": digest(payload),
                },
            )
            require(
                len(raw.get("choices", [])) == 1, "single real teacher output required"
            )
            choice = raw["choices"][0]
            answer = choice["message"].get("content")
            require(
                answer is None or isinstance(answer, str),
                "teacher content type differs",
            )
            observed = {
                "record_id": record["record_id"],
                "raw_response": raw,
                "answer": answer or "",
                "wall_seconds": elapsed,
                "usage": raw.get("usage"),
                "request_digest": digest(payload),
                "logical_messages_digest": digest(messages),
                "freeze_digest": digest(freeze),
                "response_retained_before_postflight": True,
            }
            write(directory / f"OUTPUT-{index}.json", observed)
            server_after, slots_after = existing_server()[0], idle(credential)
            write(
                directory / f"POSTFLIGHT-{index}.json",
                {"server": server_after, "slots": slots_after},
            )
            require(
                server_after == freeze["server"], "teacher service changed during call"
            )
            completed.append(
                {"record_id": record["record_id"], "output_digest": digest(observed)}
            )
        write(
            run
            / ("FIRST_COMPLETE.json" if stage == "first" else "SECOND_COMPLETE.json"),
            {
                "model_calls": len(completed),
                "outputs": completed,
                "wall_seconds": time.perf_counter() - started,
                "full_system_cost_known": False,
            },
        )
    except BaseException as error:
        write(
            directory / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "completed_calls": len(completed),
                "wall_seconds": time.perf_counter() - started,
                "requests_sent": requests_sent,
                "responses_received": len(list(directory.glob("RAW_RESPONSE-*.json"))),
                "automatic_retry": False,
                "unknown_generation_is_not_replayed": True,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("first", "second"))
    parser.add_argument("root", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("--source-commit", required=True)
    arguments = parser.parse_args()
    main(arguments.stage, arguments.root, arguments.run, arguments.source_commit)
