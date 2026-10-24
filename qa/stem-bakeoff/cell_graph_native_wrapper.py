"""Fixed main-host reducer/publication helper; no caller-selected path or code.

Only new experiment-owned evidence files are written. Native worker collection
is performed by the original owner/adapter, never by this helper. This script
does not read task labels, original checkpoints, or original feature archives.
"""

import time

_ENTRY_WALL = time.perf_counter_ns()
_ENTRY_CPU = time.process_time_ns()

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys


WORKTREE = Path("/home/qian-qi/workspace/hepta-cell-graph-benchmark-20261024")
EVIDENCE = Path("/home/qian-qi/workspace/hepta-cell-graph-evidence-20261024")
PYTHON = "/data/hepta-cell-input-20261024/.venv/bin/python"
DISPATCH = EVIDENCE / "requests-v1" / "dispatch.json"
REDUCER = WORKTREE / "qa" / "stem-bakeoff" / "cell_graph_reduce.py"
REDUCER_SHA = "5ac4bba925d161f8fe3eda5c5c036207d7182ec84733f6c1f310befa0da54efb"
PROTOCOL_SHA = "2c88c2a47f56c05ea86f221ad26806fb5190bd17b8b32a9284a0ae31dfbe85e5"
MAX_INPUT = 1048576
CHUNK_BYTES = 524288
MAX_LEDGER_BYTES = 268435456


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def strict_json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def digest(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value), "SHA256 required")
    return value


def no_symlinks(path):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "fixed absolute path required")
    for part in (path, *path.parents):
        require(not part.is_symlink(), "symlink path rejected")
    return path


def bounded_file(path, limit):
    no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "regular file required")
        data = stream.read(limit + 1)
    require(len(data) <= limit, "bounded regular file required")
    return data


def exclusive(path, data):
    no_symlinks(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    no_symlinks(path)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        require(bounded_file(path, len(data)) == data, "immutable evidence conflict")
        return "identical_existing"
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return "created"


def decode(item, limit=MAX_INPUT):
    require(isinstance(item, dict) and set(item) == {"base64", "sha256"}, "exact bytes/hash envelope required")
    digest(item["sha256"])
    require(isinstance(item["base64"], str) and len(item["base64"]) <= 4 * ((limit + 2) // 3), "bounded base64 required")
    data = base64.b64decode(item["base64"], validate=True)
    require(len(data) <= limit and base64.b64encode(data).decode() == item["base64"] and sha(data) == item["sha256"], "canonical exact bytes/hash required")
    return data


def graph_id(value):
    require(isinstance(value, str) and re.fullmatch(r"b[0-5]-[ABC]", value), "predeclared graph ID required")
    return value


def collection(data, graph, dispatch_sha):
    value = strict_json(data)
    require(value.get("schema") == "hepta.fixed-cell-graph.collection.v1" and value.get("graph_id") == graph and value.get("dispatch_sha256") == dispatch_sha, "collection identity differs")
    return value


def wrapper_cost():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"wrapper_process_wall_ns_before_receipt": time.perf_counter_ns() - _ENTRY_WALL,
        "wrapper_self_cpu_ns_before_receipt": time.process_time_ns() - _ENTRY_CPU,
        "wrapper_reaped_child_cpu_ns_before_receipt": int((child.ru_utime + child.ru_stime) * 1_000_000_000),
        "wrapper_self_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)),
        "scope": "Includes this wrapper's imports/input/verification/storage and elapsed child path. Child CPU overlaps original reducer process accounting; never add both. Excludes time import, final wrapper receipt/stdout publication and native-service/ownerJS costs."}


def preserve_cli_output(folder, stdout, stderr, *, complete, returncode):
    metadata = {"complete_child_return_observed": complete, "returncode": returncode}
    for name, data, cap in (("stdout", stdout, 196608), ("stderr", stderr, 8192)):
        prefix = data[:cap]
        metadata[name] = {"observed_bytes": len(data), "observed_sha256": sha(data),
            "stored_prefix_bytes": len(prefix), "stored_prefix_sha256": sha(prefix),
            "stored_prefix_truncated": len(data) > cap}
        exclusive(folder / ("reducer-cli-" + name + ".bin"), prefix)
    exclusive(folder / "reducer-cli-output.json", canonical(metadata))


def run(value, self_sha):
    require(value.get("schema") == "hepta.fixed-cell-graph.native-wrapper.v1" and value.get("expected_wrapper_sha256") == self_sha, "frozen wrapper identity differs")
    dispatch_sha = digest(value.get("dispatch_sha256"))
    dispatch_data = bounded_file(DISPATCH, MAX_INPUT)
    require(sha(dispatch_data) == dispatch_sha, "fixed remote dispatch changed")
    dispatch = strict_json(dispatch_data)
    require(dispatch.get("protocol_sha256") == PROTOCOL_SHA and dispatch.get("schema") == "hepta.fixed-cell-graph.dispatch.v1", "frozen graph protocol required")
    operation = value.get("operation")
    result = {"schema": "hepta.fixed-cell-graph.native-wrapper-result.v1", "operation": operation,
        "dispatch_sha256": dispatch_sha, "wrapper_sha256": self_sha}
    if operation in ("reduce", "publish"):
        graph = graph_id(value.get("graph_id"))
        require(sum(item["graph_id"] == graph for item in dispatch["graphs"]) == 1, "one registered graph required")
        data = decode(value["collection"])
        collection(data, graph, dispatch_sha)
        folder = EVIDENCE / "graphs" / graph
        result.update(graph_id=graph, collection_sha256=sha(data), collection_publication=exclusive(folder / "collection.json", data))
        if operation == "reduce":
            reducer_data = bounded_file(REDUCER, MAX_INPUT)
            require(sha(reducer_data) == REDUCER_SHA, "original reducer source changed")
            no_symlinks(folder / "reduction")
            require(not (folder / "reduction").exists(), "reduction already attempted; no recomputation retry")
            # Record launch intent before invoking the single original reducer.
            args = [PYTHON, "-u", str(REDUCER), "--dispatch", str(DISPATCH), "--graph-id", graph,
                "--owner-input", str(folder / "collection.json"), "--output", str(folder / "reduction"),
                "--expected-dispatch-sha256", dispatch_sha]
            intent = canonical({"args": args, "cwd": str(WORKTREE), "reducer_sha256": REDUCER_SHA,
                "collection_sha256": sha(data), "dispatch_sha256": dispatch_sha})
            require(not (folder / "reducer-launch.json").exists(), "reducer launch intent already exists")
            exclusive(folder / "reducer-launch.json", intent)
            try:
                completed = subprocess.run(args, cwd=WORKTREE, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=35, check=False)
            except subprocess.TimeoutExpired as error:
                stdout, stderr = error.stdout or b"", error.stderr or b""
                # The exact partial output is evidence, not a successful result.
                preserve_cli_output(folder, stdout, stderr, complete=False, returncode=None)
                exclusive(folder / "reducer-cli-timeout.json", canonical({"timeout_seconds": 35,
                    "stdout_seen_bytes": len(stdout), "stderr_seen_bytes": len(stderr), "successful_completion_observed": False}))
                raise
            preserve_cli_output(folder, completed.stdout, completed.stderr, complete=True, returncode=completed.returncode)
            exclusive(folder / "reducer-cli-exit.json", canonical({"returncode": completed.returncode}))
            require(len(completed.stdout) <= 196608 and len(completed.stderr) <= 8192, "reducer CLI output exceeded fixed bounds; exact observed length/hash and bounded prefixes preserved")
            require(completed.returncode == 0, "original reducer failed; stdout/stderr/exit preserved")
            reduced = strict_json(completed.stdout)
            receipt = bounded_file(folder / "reduction" / "receipt.json", MAX_INPUT)
            require(reduced.get("graph_id") == graph and reduced.get("status") in ("completed", "failed") and reduced.get("receipt_sha256") == sha(receipt), "original reduction receipt hash differs")
            saved = strict_json(receipt)
            require(saved.get("graph_id") == graph and saved.get("dispatch_sha256") == dispatch_sha and saved.get("collection_sha256") == sha(data) and saved.get("status") == reduced["status"], "original reducer receipt identity differs")
            result["reduction"] = reduced
        else:
            owner_data = decode(value["owner"])
            owner = strict_json(owner_data)
            require(owner.get("schema") == "hepta.fixed-cell-graph.owner.v1" and owner.get("graph_id") == graph and owner.get("dispatch_sha256") == dispatch_sha, "owner publication identity differs")
            result.update(owner_sha256=sha(owner_data), owner_publication=exclusive(folder / "owner.json", owner_data))
    elif operation == "recovery":
        request = value.get("request_id")
        require(request in ("b0-A-s0", "b0-B-s0", "b0-C-s0"), "only frozen recovery IDs allowed")
        data = decode(value["record"])
        record = strict_json(data)
        require(record.get("schema") == "hepta.fixed-cell-graph.recovery.v1" and record.get("request_id") == request and record.get("dispatch_sha256") == dispatch_sha, "recovery identity differs")
        result.update(request_id=request, record_sha256=sha(data), publication=exclusive(EVIDENCE / "graphs" / "recovery" / (request + ".json"), data))
    elif operation in ("raw_chunk", "raw_seal"):
        ledger_sha = digest(value.get("ledger_sha256"))
        length, total = value.get("ledger_bytes"), value.get("total_chunks")
        require(type(length) is int and 0 < length <= MAX_LEDGER_BYTES and type(total) is int and total == (length + CHUNK_BYTES - 1) // CHUNK_BYTES, "bounded exact ledger census required")
        folder = EVIDENCE / "raw" / ledger_sha
        exclusive(folder / "manifest.json", canonical({"dispatch_sha256": dispatch_sha, "sha256": ledger_sha, "bytes": length, "chunks": total, "chunk_bytes": CHUNK_BYTES}))
        if operation == "raw_chunk":
            index = value.get("index")
            require(type(index) is int and 0 <= index < total, "registered chunk index required")
            data = decode(value["chunk"], CHUNK_BYTES)
            require(len(data) == min(CHUNK_BYTES, length - index * CHUNK_BYTES), "exact chunk length required")
            result.update(index=index, chunk_sha256=sha(data), publication=exclusive(folder / f"part-{index:06d}.bin", data))
        else:
            hasher = hashlib.sha256()
            for index in range(total):
                data = bounded_file(folder / f"part-{index:06d}.bin", CHUNK_BYTES)
                require(len(data) == min(CHUNK_BYTES, length - index * CHUNK_BYTES), "missing/truncated ledger chunk")
                hasher.update(data)
            require(hasher.hexdigest() == ledger_sha, "full original ledger SHA differs")
            destination = no_symlinks(folder / "ledger.json")
            # Verify complete chunks before exclusive assembly; never overwrite.
            if destination.exists():
                verify = hashlib.sha256()
                with destination.open("rb") as stream:
                    for data in iter(lambda: stream.read(CHUNK_BYTES), b""):
                        verify.update(data)
                require(destination.stat().st_size == length and verify.hexdigest() == ledger_sha, "existing ledger conflicts")
                disposition = "identical_existing"
            else:
                with destination.open("xb") as stream:
                    for index in range(total):
                        stream.write(bounded_file(folder / f"part-{index:06d}.bin", CHUNK_BYTES))
                    stream.flush()
                    os.fsync(stream.fileno())
                disposition = "created"
            result.update(ledger_sha256=ledger_sha, ledger_bytes=length, publication=disposition)
    else:
        raise ValueError("unrecognized fixed evidence operation")
    result["wrapper_cost"] = wrapper_cost()
    return result


def main():
    require(sys.executable == PYTHON, "fixed main interpreter required")
    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    require(len(data) <= MAX_INPUT, "native stdin exceeds1MiB")
    self_sha = sha(bounded_file(Path(__file__), MAX_INPUT))
    result = run(strict_json(data), self_sha)
    # Persist exact result before stdout; enclosing owner includes this write.
    envelope_sha = sha(data)
    result_data = canonical(result)
    exclusive(EVIDENCE / "native-wrapper-receipts" / (envelope_sha + ".json"), result_data)
    sys.stdout.buffer.write(result_data)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
