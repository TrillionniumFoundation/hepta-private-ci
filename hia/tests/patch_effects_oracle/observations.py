"""Compare the fixed natural-input corpus using real process and file results."""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess

from .admission import require

NAMES = (
    "add_new", "add_overwrite", "add_nested", "add_invalid_utf8",
    "add_directory", "add_symlink", "delete_existing", "delete_missing",
    "delete_directory", "delete_invalid_utf8", "delete_symlink",
    "update_existing", "update_crlf", "update_missing", "update_directory",
    "update_invalid_utf8", "update_symlink", "move_new", "move_overwrite",
    "move_nested", "move_target_directory", "move_same_path", "move_dot_alias",
    "move_source_symlink", "move_destination_symlink",
    "prefix_then_delete_missing", "prefix_then_update_missing", "mixed_success",
    "empty_patch", "invalid_patch",
)
CONTEXTS = {
    "none": "",
    "present_disabled": json.dumps({
        "permissions": {"type": "disabled"}, "windowsSandboxLevel": "disabled",
    }, separators=(",", ":")),
    "present_restricted_unconfigured": json.dumps({
        "permissions": {"type": "managed",
                        "file_system": {"type": "restricted", "entries": []},
                        "network": "restricted"},
        "windowsSandboxLevel": "disabled",
    }, separators=(",", ":")),
}
METHODS = frozenset((
    "canonicalize", "read_file", "read_file_stream", "read_file_bounded_authorized",
    "read_file_text", "write_file", "create_directory", "get_metadata",
    "read_directory", "walk", "remove", "copy",
))
PATH_HEX = frozenset((
    "fixture_root_hex", "cwd_debug_hex", "sandbox_debug_hex",
    "failure_debug_hex", "display_hex", "debug_hex", "delta_debug_hex",
    "stdout_hex", "stderr_hex",
))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def matrix():
    return [{"id": index, "context": context, "sandbox_json": value,
             "mode": mode, "follow_symlinks": follow, "case": name}
            for index, (context, value, mode, follow, name) in enumerate(
                (context, value, mode, follow, name)
                for context, value in CONTEXTS.items()
                for mode in (0, 1) for follow in (0, 1) for name in NAMES)]


def wire(case):
    result = b"HFXO0001" + struct.pack("<QQ", case["mode"], case["follow_symlinks"])
    for value in (case["case"], case["sandbox_json"]):
        data = value.encode()
        result += struct.pack("<Q", len(data)) + data
    return result


def safe_fixture_root(root):
    # These are controlled qualification output names, not a restriction on
    # production patch paths. This keeps native and Rust/URL Debug spellings
    # byte-identical without a second implementation of Rust string escaping.
    value = os.fsencode(root)
    require(re.fullmatch(rb"/[A-Za-z0-9_./-]+", value) is not None,
            "choose an external work-dir with ASCII letters/digits/_/./- only")
    return value


def number(value):
    require(re.fullmatch(r"0|[1-9][0-9]*", value) is not None,
            "noncanonical observation count")
    return int(value)


def unhex(value):
    require(re.fullmatch(r"(?:[0-9a-f]{2})*", value) is not None,
            "noncanonical observation byte encoding")
    return bytes.fromhex(value)


def parse(raw):
    require(raw.endswith(b"\n"), "missing final observer newline")
    result = {}
    for line in raw[:-1].split(b"\n"):
        key, separator, value = line.partition(b"=")
        require(separator, "malformed observer field")
        key, value = key.decode("ascii"), value.decode("ascii")
        require(key not in result, "duplicate observer field")
        if key.endswith("_hex"):
            unhex(value)
        result[key] = value
    require(result.get("protocol") == "HFXO0001" and
            result.get("observation_complete") == "true",
            "incomplete public observer result")
    return result


def validate_fields(values, case, request, root):
    require(unhex(values["request_hex"]) == request, "executed request echo differs")
    require(unhex(values["fixture_root_hex"]) == os.fsencode(root), "fixture root differs")
    require(unhex(values["case_name_hex"]) == case["case"].encode(), "selected case differs")
    require(unhex(values["sandbox_json_hex"]) == case["sandbox_json"].encode(),
            "actual sandbox context bytes differ")
    present = str(bool(case["sandbox_json"])).lower()
    require(values["sandbox_present"] == present, "actual context presence differs")
    mode = ("NormalizeToLf", "PreserveLineEndings")[case["mode"]]
    follow = str(bool(case["follow_symlinks"])).lower()
    options = f"ApplyPatchOptions {{ update_file_mode: {mode}, follow_symlinks: {follow} }}"
    require(unhex(values["options_debug_hex"]) == options.encode(),
            "actual update mode or symlink option differs")
    require(values["stdout_writer"] == values["stderr_writer"] == "Vec<u8>" and
            values["writer_errors_injected"] == "false", "writer observation differs")
    require(values["status"] in {"success", "error"} and
            values["delta_exact"] in {"true", "false"}, "invalid public result")
    required = {
        "protocol", "request_hex", "case_name_hex", "fixture_root_hex", "cwd_debug_hex",
        "patch_hex", "options_debug_hex", "sandbox_present", "sandbox_json_hex",
        "sandbox_debug_hex", "stdout_writer", "stderr_writer", "writer_errors_injected",
        "before_entries", "after_entries", "status", "delta_exact", "delta_changes",
        "delta_debug_hex", "stdout_hex", "stderr_hex", "fs_events", "observation_complete",
    }
    if values["status"] == "error":
        required.update(("failure_debug_hex", "kind", "display_hex", "debug_hex"))
        require(values["kind"] in {"ParseError", "IoError", "ComputeReplacements",
                                   "PathUri", "ImplicitInvocation"}, "unknown public error variant")
    for prefix in ("before", "after"):
        count = number(values[prefix + "_entries"])
        require(count >= 1, "fixture root snapshot is absent")
        required.update(prefix + "_" + str(i) + "_hex" for i in range(count))
    required.update("fs_event_" + str(i) + "_hex" for i in range(number(values["fs_events"])))
    for index in range(number(values["delta_changes"])):
        prefix = "delta_" + str(index)
        required.update((prefix + "_path_debug_hex", prefix + "_path_native_hex", prefix + "_kind"))
        kind = values[prefix + "_kind"]
        if kind in {"Add", "Delete"}:
            required.add(prefix + "_content_hex")
        if kind == "Add":
            optional = prefix + "_overwritten"
        elif kind == "Update":
            required.update((prefix + "_move_present", prefix + "_old_hex", prefix + "_new_hex"))
            require(values[prefix + "_move_present"] in {"true", "false"}, "invalid move flag")
            if values[prefix + "_move_present"] == "true":
                required.update((prefix + "_move_debug_hex", prefix + "_move_native_hex"))
            optional = prefix + "_overwritten_move"
        else:
            require(kind == "Delete", "unknown delta change variant")
            continue
        required.add(optional + "_present")
        require(values[optional + "_present"] in {"true", "false"}, "invalid overwritten flag")
        if values[optional + "_present"] == "true":
            required.add(optional + "_hex")
    require(set(values) == required, "missing or unexpected public observation fields")


def event_record(text):
    parts = text.split(";")
    if parts[-1] == "":
        parts.pop()
    result = {}
    for part in parts:
        key, separator, value = part.partition("=")
        require(separator and key not in result, "malformed or duplicate callback field")
        result[key] = value
        if key.endswith("_hex"):
            unhex(value)
    return result


def verify_events(values, case):
    operations = collections.Counter()
    pending = {}
    for index in range(number(values["fs_events"])):
        event = event_record(unhex(values["fs_event_" + str(index) + "_hex"]).decode())
        call = number(event["call_id"])
        if event["phase"] == "begin":
            require(call == index and call not in pending, "duplicate or invalid callback ID")
            require(event["operation"] in METHODS, "unknown actual filesystem method")
            require(event["sandbox_present"] == str(bool(case["sandbox_json"])).lower() and
                    event["sandbox_same_reference"] == event["inner_is_local_fs"] == "true",
                    "callback changed executor or sandbox reference")
            pending[call] = event["operation"]
            operations[event["operation"]] += 1
        else:
            require(event["phase"] == "end" and call in pending and
                    event["status"] in {"ok", "error"}, "unpaired or incomplete callback")
            pending.pop(call)
    require(not pending, "a real callback lacks its completion")
    return operations


def actual_tree(root):
    entries = []

    def visit(path):
        relative = os.fsencode(str(path.relative_to(root))) if path != root else b""
        prefix = "path_hex=" + relative.hex()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            entries.append(prefix + ";kind=symlink;target_hex=" +
                           os.fsencode(os.readlink(path)).hex())
        elif stat.S_ISDIR(metadata.st_mode):
            entries.append(prefix + ";kind=directory")
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(metadata.st_mode):
            entries.append(prefix + ";kind=file;contents_hex=" + path.read_bytes().hex())
        else:
            entries.append(prefix + ";kind=other")

    visit(root)
    return entries


def normalize(raw, root):
    forms = [(safe_fixture_root(root), b"<fixture>")]
    for _ in range(3):
        before, after = forms[-1]
        forms.append((before.hex().encode(), after.hex().encode()))
    lines = []
    for line in raw[:-1].split(b"\n"):
        key, _, value = line.partition(b"=")
        name = key.decode()
        path_field = (name in PATH_HEX or
                      re.fullmatch(r"delta_[0-9]+_(?:path|move)_(?:native|debug)_hex", name) or
                      re.fullmatch(r"fs_event_[0-9]+_hex", name))
        if path_field:
            decoded = unhex(value.decode())
            for before, after in reversed(forms):
                decoded = decoded.replace(before, after)
            value = decoded.hex().encode()
        # Request, patch, case, contents, structured old/new fields and both
        # relative tree snapshots are never normalized.
        lines.append(key + b"=" + value)
    return b"\n".join(lines) + b"\n"


def observe(binary, case, request, directory, producer, env):
    directory.mkdir()
    root = directory / "fixture"
    safe_fixture_root(root)
    stdout_path, stderr_path = directory / "stdout.bin", directory / "stderr.bin"
    process = {"valid": False, "argv": [str(binary), str(root)], "cwd": str(producer),
               "request_sha256": digest(request), "fixture": str(root), "timed_out": False}
    try:
        with stdout_path.open("xb") as out, stderr_path.open("xb") as err:
            try:
                completed = subprocess.run(process["argv"], input=request, stdout=out, stderr=err,
                                           cwd=producer, env=env, timeout=30)
                process["returncode"] = completed.returncode
            except subprocess.TimeoutExpired:
                process["returncode"] = None
                process["timed_out"] = True
                raise
        raw, errors = stdout_path.read_bytes(), stderr_path.read_bytes()
        process.update(stdout_bytes=len(raw), stdout_sha256=digest(raw),
                       stderr_bytes=len(errors), stderr_sha256=digest(errors))
        require(process["returncode"] == 0 and not errors, "public observer process failed")
        values = parse(raw)
        validate_fields(values, case, request, root)
        operations = verify_events(values, case)
        actual = actual_tree(root)
        emitted = [unhex(values["after_" + str(i) + "_hex"]).decode()
                   for i in range(number(values["after_entries"]))]
        require(actual == emitted, "independently read final filesystem differs from observer")
        save(directory / "independent-after-tree.json", actual)
        canonical = normalize(raw, root)
        (directory / "normalized.stdout").write_bytes(canonical)
        process.update(valid=True, status=values["status"], delta_exact=values["delta_exact"],
                       delta_changes=number(values["delta_changes"]),
                       filesystem_events=number(values["fs_events"]),
                       filesystem_operations=dict(operations),
                       independent_final_tree_verified=True,
                       normalized_stdout_sha256=digest(canonical))
        return process, canonical
    except Exception as error:
        process["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        for label, path in (("stdout", stdout_path), ("stderr", stderr_path)):
            if path.exists():
                data = path.read_bytes()
                process[label + "_bytes"] = len(data)
                process[label + "_sha256"] = digest(data)
        save(directory / "process.json", process)


def run(binaries, producer, env, output):
    output.mkdir()
    cases = matrix()
    require(len(cases) == 360 and len({(c["context"], c["mode"],
            c["follow_symlinks"], c["case"]) for c in cases}) == 360,
            "the fixed complete public corpus changed")
    require(len({wire(case) for case in cases}) == 360,
            "duplicate executable requests in the complete input matrix")
    save(output / "cases.json", cases)
    report = {"passed": False, "defined_pairs": 360, "cases": [], "skipped": 0,
              "context_scope": {
                  "none": "No context.",
                  "present_disabled": "Actual typed context, same borrowed reference.",
                  "present_restricted_unconfigured":
                      "Natural LOCAL_FS missing-sandbox-runtime result; not OS sandbox qualification.",
              }}
    operations, outcomes = collections.Counter(), collections.Counter()
    try:
        for case in cases:
            directory = output / str(case["id"])
            directory.mkdir()
            request = wire(case)
            (directory / "request.bin").write_bytes(request)
            pair = {**case, "request_sha256": digest(request), "observations": {}, "matched": False}
            report["cases"].append(pair)
            canonical = {}
            for side, binary in binaries.items():
                result, canonical[side] = observe(binary, case, request, directory / side,
                                                  producer, env)
                pair["observations"][side] = result
                save(output / "report.json", report)
            pair["matched"] = canonical["original"] == canonical["native"]
            require(pair["matched"], "complete public observation mismatch: " + str(case))
            original = pair["observations"]["original"]
            operations.update(original["filesystem_operations"])
            outcomes[(case["context"], original["status"], original["delta_exact"])] += 1
        require(len(report["cases"]) == 360, "missing actual public observations")
        report.update(passed=True, semantic_pairs=360, actual_processes=720, mismatches=0,
                      original_filesystem_operations=dict(operations),
                      outcome_counts=[{"context": k[0], "status": k[1], "exact": k[2], "count": v}
                                      for k, v in sorted(outcomes.items())])
        return report
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        save(output / "report.json", report)
