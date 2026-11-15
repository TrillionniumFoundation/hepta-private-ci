"""Length-delimited transport and full process/file observations; no update algorithm."""
import json
import os
from pathlib import Path
import re
import resource
import struct
import subprocess

from .identity import sha

HEX_FIELDS = frozenset(("path_hex", "cwd_hex", "cwd_debug_hex", "file_before_hex",
    "content_hex", "diff_hex", "display_hex", "debug_hex", "delta_debug_hex",
    "stdout_hex", "stderr_hex", "file_after_hex"))
PATH_FIELDS = frozenset(("path_hex", "cwd_hex", "cwd_debug_hex", "display_hex",
                        "debug_hex", "delta_debug_hex", "stderr_hex"))
FIELDS = HEX_FIELDS | frozenset(("protocol", "status", "kind", "delta_exact",
    "delta_changes", "file_exists", "file_is_directory", "file_read_error_kind"))


def word(value):
    if not isinstance(value, int) or not 0 <= value < 2**64:
        raise ValueError("integer outside the u64 wire range")
    return struct.pack("<Q", value)


def blob(value):
    value = value.encode("utf-8") if isinstance(value, str) else value
    return word(len(value)) + value


def strings(values):
    return word(len(values)) + b"".join(blob(value) for value in values)


def encode(case, mode, route):
    source = bytes.fromhex(case["source_bytes_hex"]) if "source_bytes_hex" in case else case["source"].encode()
    output = b"HUPD0001" + word(mode) + word(route) + word(case["file_kind"]) + blob(source)
    output += word(len(case["chunks"]))
    for chunk in case["chunks"]:
        output += word(chunk["context"] is not None)
        if chunk["context"] is not None:
            output += blob(chunk["context"])
        output += strings(chunk["old"]) + strings(chunk["new"]) + word(len(chunk["indices"]))
        output += b"".join(word(a) + word(b) for a, b in chunk["indices"])
        output += word(chunk["eof"])
    return output + blob(case["patch"]), source


def decode_request(data):
    """Independent bounded decoder used only to verify the harness serialization."""
    position = 8

    def number():
        nonlocal position
        if position + 8 > len(data):
            raise ValueError("short request word")
        value = struct.unpack_from("<Q", data, position)[0]
        position += 8
        return value

    def payload():
        nonlocal position
        size = number()
        if size > len(data) - position:
            raise ValueError("short request payload")
        value = data[position:position + size]
        position += size
        return value

    def text_list():
        return [payload().decode("utf-8") for _ in range(number())]

    if data[:8] != b"HUPD0001":
        raise ValueError("wrong wire magic")
    mode, route, file_kind, source = number(), number(), number(), payload()
    chunks = []
    for _ in range(number()):
        context = payload().decode() if number() else None
        old, new = text_list(), text_list()
        indices = [[number(), number()] for _ in range(number())]
        chunks.append({"context": context, "old": old, "new": new, "indices": indices, "eof": bool(number())})
    patch = payload().decode()
    if position != len(data):
        raise ValueError("trailing request bytes")
    return {"mode": mode, "route": route, "file_kind": file_kind, "source": source,
            "chunks": chunks, "patch": patch}


def file_state(fixture, destination):
    path = fixture / "input.txt"
    state = {"fixture_exists": fixture.exists(), "exists": path.exists(),
             "is_directory": path.is_dir(), "is_symlink": path.is_symlink()}
    if path.is_file():
        data = path.read_bytes()
        saved = destination / "file-after.bin"
        saved.write_bytes(data)
        state.update(bytes=len(data), sha256=sha(saved), contents_hex=data.hex())
    return state


def decode_output(raw, fixture):
    lines = raw.split(b"\n")
    if not lines or lines[-1] != b"":
        raise ValueError("missing final output newline")
    values = {}
    for line in lines[:-1]:
        key, separator, value = line.partition(b"=")
        key, value = key.decode("ascii"), value.decode("ascii")
        if not separator or key in values or key not in FIELDS:
            raise ValueError("unknown, malformed or duplicate output field")
        if key in HEX_FIELDS and re.fullmatch("[0-9a-f]*", value) is None:
            raise ValueError("noncanonical byte encoding")
        values[key] = value
    if values.get("protocol") != "HUPD0001":
        raise ValueError("missing public API result marker")
    if bytes.fromhex(values["cwd_hex"]) != str(fixture).encode():
        raise ValueError("emitted fixture root differs from the actual supplied root")
    if bytes.fromhex(values["path_hex"]) != str(fixture / "input.txt").encode():
        raise ValueError("emitted file path differs from the actual supplied path")
    debug = bytes.fromhex(values["cwd_debug_hex"])
    if not debug.startswith(b'"') or not debug.endswith(b'"'):
        raise ValueError("missing actual Rust Debug root spelling")
    roots = sorted({str(fixture).encode(), debug[1:-1]}, key=len, reverse=True)
    output = []
    for line in lines[:-1]:
        key, _, value = line.partition(b"=")
        if key.decode() in PATH_FIELDS:
            decoded = bytes.fromhex(value.decode())
            for root in roots:
                decoded = decoded.replace(root, b"<FIXTURE>")
            value = decoded.hex().encode()
        output.append(key + b"=" + value)
    return values, b"\n".join(output) + b"\n", roots


def no_core():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def observe(binary, request, source, case, mode, route, destination):
    destination.mkdir()
    fixture = destination / "fixture"
    env = os.environ.copy()
    env["RUST_BACKTRACE"] = "0"
    timed_out = False
    try:
        process = subprocess.run([str(binary), str(fixture)], input=request,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            preexec_fn=no_core, timeout=20)
        stdout, stderr, code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, code = error.stdout or b"", error.stderr or b"", None
        timed_out = True
    (destination / "stdout.bin").write_bytes(stdout)
    (destination / "stderr.bin").write_bytes(stderr)
    state = file_state(fixture, destination)
    result = {"executed": True, "returncode": code, "timed_out": timed_out,
              "stdout_bytes": len(stdout), "stdout_sha256": sha(destination / "stdout.bin"),
              "stderr_bytes": len(stderr), "stderr_sha256": sha(destination / "stderr.bin"),
              "independent_file_state": state, "valid": False}
    if timed_out:
        result["outcome"] = "timeout"
        return result
    if code != 0:
        panic = code == 101 and b"panicked at" in stderr
        result.update(outcome="panic" if panic else "process-failure",
                      valid=panic and case["precondition"],
                      post_panic_state_equivalence_required=False)
        return result
    if case["precondition"]:
        result["outcome"] = "unexpected-nonpanic"
        return result
    values, normalized, roots = decode_output(stdout, fixture)
    if values.get("status") not in {"success", "error"}:
        raise ValueError("missing actual public API outcome")
    normalized_stderr = stderr
    for root in roots:
        normalized_stderr = normalized_stderr.replace(root, b"<FIXTURE>")
    (destination / "normalized.stdout").write_bytes(normalized)
    (destination / "normalized.stderr").write_bytes(normalized_stderr)
    state_matches = (values.get("file_exists") == str(state["exists"]).lower()
        and values.get("file_is_directory") == str(state["is_directory"]).lower()
        and ("contents_hex" not in state or values.get("file_after_hex") == state["contents_hex"]))
    unchanged = (state.get("contents_hex") == source.hex() if case["file_kind"] == 0 else
                 not state["exists"] if case["file_kind"] == 1 else state["is_directory"])
    unchanged_required = route == 0 or values["status"] == "error"
    checks = {}
    for key, expected in case["predictions"].get(f"{mode}/{route}", {}).items():
        if key == "content":
            checks[key] = values.get("content_hex") == expected.encode().hex()
        elif key == "display_contains":
            checks[key] = expected.encode() in bytes.fromhex(values.get("display_hex", ""))
        elif key == "display_suffix":
            checks[key] = bytes.fromhex(values.get("display_hex", "")).endswith(expected.encode())
        else:
            checks[key] = values.get(key) == expected
    result.update(outcome=values["status"], fields=values,
        normalized_stdout_sha256=sha(destination / "normalized.stdout"),
        normalized_stderr_sha256=sha(destination / "normalized.stderr"),
        file_unchanged=unchanged, unchanged_required=unchanged_required,
        emitted_state_matches_independent_read=state_matches, predictions=checks,
        valid=state_matches and (not unchanged_required or unchanged) and all(checks.values()))
    return result
