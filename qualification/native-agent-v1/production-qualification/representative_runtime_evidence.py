"""Read private original runtime records; never launch, signal, or repair a job."""

import hashlib
import json
from pathlib import Path


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("runtime evidence is not a regular original file")
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_digest(params):
    keys = ("args", "cpu_quota_percent", "cwd", "env", "executable", "host",
            "memory_max_bytes", "nice", "stdin", "timeout_seconds")
    body = {key: params.get(key) for key in keys}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def bound_job(root, admission):
    params = admission["params"]
    records = [(path, read_json(path)) for path in (root / "controller" / "jobs").glob("*.json")]
    selected = [(path, record) for path, record in records
                if record.get("idempotency_key") == params["idempotency_key"]]
    if len(selected) != 1:
        raise ValueError("original admission has no unique retained runtime job")
    path, record = selected[0]
    if record.get("launch_state") != "launched" or record.get("request_digest") != request_digest(params):
        raise ValueError("original runtime job has no matching full-request launch binding")
    for field in ("host", "executable", "args", "cwd", "idempotency_key"):
        if record.get(field) != params.get(field):
            raise ValueError("runtime job changed admitted field " + field)
    remote = root / "remote" / "jobs" / record["id"]
    if (remote.is_symlink() or remote.resolve() != remote
            or remote.parent != root / "remote" / "jobs"
            or Path(record["remote_job_dir"]).resolve() != remote):
        raise ValueError("original runtime job escaped this experiment's private directory")
    request = read_json(remote / "request.json")
    if request.get("job_id") != record["id"] or request.get("request_digest") != record["request_digest"]:
        raise ValueError("retained remote request changed original job identity")
    return remote, record, {"record_sha256": digest(path), "request_sha256": digest(remote / "request.json")}


def stream_file(remote, stream):
    # Exact stream layout verified on the pinned runtime's completed jobs.
    if stream not in ("stdout", "stderr"):
        raise ValueError("unknown retained runtime stream")
    path = remote / (stream + ".log")
    if path.is_symlink() or not path.is_file():
        raise ValueError("runtime has no regular original " + stream + " log")
    return path


def audit_long_output(root, admission, result):
    remote, job, binding = bound_job(root, admission)
    if len(list((root / "controller" / "jobs").glob("*.json"))) != 1:
        raise ValueError("long output allocated more than one original runtime job")
    reference = result["presentation"]["retained"]
    params = admission["params"]
    expected_binding = {"host": params["host"], "job_id": job["id"],
                        "idempotency_key": params["idempotency_key"],
                        "operation_id": params["idempotency_key"],
                        "runtime_intent_digest": admission["intent_digest"]}
    if any(reference.get(key) != value for key, value in expected_binding.items()):
        raise ValueError("model excerpt rebound the original retained output identity")
    terminal = read_json(remote / "exit.json")
    terminal_sha = digest(remote / "exit.json")
    if (terminal.get("exit_code") != 0 or terminal.get("cancelled") is not False
            or terminal.get("timed_out") is not False or terminal.get("job_id") != job["id"]
            or terminal.get("terminal_publication_protocol") != 1
            or terminal.get("output_complete") is not True or terminal.get("output_durable") is not True):
        raise ValueError("original long-output process lacks a successful terminal record")
    expected = b"".join(f"row={number:08d} value=0123456789abcdef\n".encode() for number in range(32768))
    streams = {}
    for stream, oracle in (("stdout", expected), ("stderr", b"")):
        path = stream_file(remote, stream)
        actual = path.read_bytes()
        if actual != oracle:
            raise ValueError("retained complete " + stream + " differs from the independent generator oracle")
        identity = {"bytes": len(actual), "sha256": hashlib.sha256(actual).hexdigest()}
        if (terminal["log_bytes"][stream] != {"seen": len(actual), "stored": len(actual)}
                or terminal["log_errors"].get(stream) is not None
                or terminal["log_synced"].get(stream) is not True
                or terminal["log_truncated"].get(stream) is not False):
            raise ValueError("original terminal publication does not prove the complete durable " + stream)
        if reference.get(stream) != identity or not actual.decode().startswith(result[stream]):
            raise ValueError("model excerpt lost its exact full-byte digest or prefix")
        streams[stream] = {**identity, "retained_file": str(path.relative_to(root))}
    if digest(remote / "exit.json") != terminal_sha:
        raise ValueError("original terminal publication changed during retained-output audit")
    return {"original_job_id": job["id"], "binding": binding,
            "terminal_sha256": terminal_sha, "streams": streams,
            "model_item_limit_bytes": result["presentation"]["limit_bytes"]}
