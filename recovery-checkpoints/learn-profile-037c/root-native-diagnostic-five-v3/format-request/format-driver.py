import sys
INPUT_GZIP_BASE64 = ''.join(sys.argv[1:])
INPUT_GZIP_SHA256 = '0ce85aed909d6a7ccb9495b42d2a1646a2c8e52b21d61ac9f51c33d2f835973b'
INPUT_JSON_SHA256 = '6342826638b1d60ece4d2adbc6dd5de5a4bfcbfd99a1ebd8c9e0fe8c6913e344'
import base64
import datetime
import difflib
import gzip
import hashlib
import json
import os
import pathlib
import subprocess
import traceback


RECORDS = pathlib.Path('/home/qian-qi/hepta-learn-037c-evidence/format-native-diagnostic-five-v3')
EXPECTED_SOURCE = '4ab34bbd3ca803213b6eecbaba81af719630f5d0'
EXPECTED_TREE = 'f947d38de96534b3882fba023e51ecd0476c809d'
EXPECTED_RUSTFMT_SHA256 = "342c3d56e8958da0b108108a39e37ceac64ebdd42e6eefafa237d219e5b7eb0c"
EXPECTED_PATHS = {'codex-rs/hepta-agentd/src/circuit_next_use_command_support_tests.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_command_evidence.rs', 'codex-rs/hepta-agentd/src/circuit_original_evaluation_panel_tests.rs', 'codex-rs/hepta-agentd/src/circuit_deep_training_readback_tests.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_command_owner_tests.rs'}


def meta(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def write_bytes(relative, data):
    target = RECORDS / relative
    assert target.is_relative_to(RECORDS)
    assert ".." not in pathlib.PurePosixPath(relative).parts
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def write_json(relative, value):
    write_bytes(relative, (json.dumps(value, indent=2) + "\n").encode())


def add_patch(parts, path, before, after):
    if before == after:
        return
    parts.append("diff --git a/" + path + " b/" + path + "\n")
    parts.append("index " + meta(before)["blob"] + ".." + meta(after)["blob"] + " 100644\n")
    parts.extend(difflib.unified_diff(
        before.decode().splitlines(True), after.decode().splitlines(True),
        fromfile="a/" + path, tofile="b/" + path, n=3,
    ))


compressed = base64.b64decode(INPUT_GZIP_BASE64, validate=True)
assert hashlib.sha256(compressed).hexdigest() == INPUT_GZIP_SHA256
payload_bytes = gzip.decompress(compressed)
assert hashlib.sha256(payload_bytes).hexdigest() == INPUT_JSON_SHA256
payload = json.loads(payload_bytes)
assert payload["source_commit"] == EXPECTED_SOURCE
assert payload["source_tree"] == EXPECTED_TREE
assert len(payload["files"]) == 5
assert {row["path"] for row in payload["files"]} == EXPECTED_PATHS

# Create only: an unknown acknowledgement must be reconciled by the same h key.
# This driver has no checkout, Git, Cargo, target, source-owner or native-test access.
RECORDS.mkdir(mode=0o700)
write_bytes("input-payload.json.gz", compressed)
write_bytes("input-payload.json", payload_bytes)
write_json("input-manifest.json", payload["input_manifest"])
write_json("format-method-provenance.json", payload["format_method_provenance"])
files = {}
for row in payload["files"]:
    path = row["path"]
    assert path in EXPECTED_PATHS and path not in files
    original = base64.b64decode(row["base_base64"], validate=True)
    before = base64.b64decode(row["before_base64"], validate=True)
    assert meta(original) == row["base"]
    assert meta(before) == row["before"]
    files[path] = {"base": original, "before": before, "origin": row["origin"]}
    for category, data in [("base", original), ("before", before), ("postimages", before)]:
        write_bytes(category + "/" + path, data)
write_json("before-format-manifest.json", [
    {"path": path, "origin": item["origin"], "base": meta(item["base"]),
     "before": meta(item["before"])}
    for path, item in sorted(files.items())
])

environment = os.environ.copy()
environment["RUSTUP_HOME"] = "/home/qian-qi/.rustup"
environment["RUSTUP_TOOLCHAIN"] = "1.96.0"
rustup = "/home/qian-qi/.cargo/bin/rustup"
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
toolchain_steps = []
command = None
rustfmt_binary = None
rustc_version = None
rustfmt_version = None
returncode = None
error = None
raw = b""


def toolchain_step(arguments):
    result = subprocess.run(arguments, cwd=RECORDS, env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    toolchain_steps.append({
        "command": arguments, "returncode": result.returncode,
        "stdout": result.stdout.decode(), "stderr": result.stderr.decode(),
    })
    write_json("toolchain-steps.json", toolchain_steps)
    result.check_returncode()
    return result.stdout.decode()


try:
    tool = toolchain_step([rustup, "which", "--toolchain", "1.96.0", "rustfmt"]).strip()
    rustc_version = toolchain_step([rustup, "run", "1.96.0", "rustc", "--version", "--verbose"])
    assert rustc_version.startswith("rustc 1.96.0 "), rustc_version
    rustfmt_version = toolchain_step([tool, "--version"])
    rustfmt_binary = meta(pathlib.Path(tool).read_bytes())
    assert rustfmt_binary["sha256"] == EXPECTED_RUSTFMT_SHA256, rustfmt_binary
    command = [tool, "--edition", "2024", "--config", "imports_granularity=Item,skip_children=true",
               *[str(RECORDS / "postimages" / path) for path in sorted(files)]]
    write_json("rustfmt-launch.json", {"command": command, "cwd": str(RECORDS),
               "RUSTUP_HOME": environment["RUSTUP_HOME"],
               "RUSTUP_TOOLCHAIN": environment["RUSTUP_TOOLCHAIN"]})
    run = subprocess.run(command, cwd=RECORDS, env=environment,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    returncode = run.returncode
    raw = run.stdout
except Exception:
    error = traceback.format_exc()
    write_bytes("failure.txt", error.encode())
finally:
    write_bytes("rustfmt.raw.log", raw)
    combined = []
    formatted = []
    before_patch = []
    after_files = []
    changed = []
    complete_postimages = []
    for path, item in sorted(files.items()):
        after = (RECORDS / "postimages" / path).read_bytes()
        assert (RECORDS / "base" / path).read_bytes() == item["base"]
        assert (RECORDS / "before" / path).read_bytes() == item["before"]
        after_files.append({"path": path, "origin": item["origin"], "base": meta(item["base"]),
                            "before": meta(item["before"]), "after": meta(after)})
        complete_postimages.append({"path": path, "after": meta(after),
                                    "content_base64": base64.b64encode(after).decode()})
        if after != item["before"]:
            changed.append(path)
        add_patch(combined, path, item["base"], after)
        add_patch(formatted, path, item["before"], after)
        add_patch(before_patch, path, item["base"], item["before"])
    assert {str(path.relative_to(RECORDS / "postimages"))
            for path in (RECORDS / "postimages").rglob("*.rs")} == EXPECTED_PATHS
    write_bytes("native-diagnostic-five-prefmt.patch", "".join(before_patch).encode())
    write_bytes("native-diagnostic-five-formatted.patch", "".join(combined).encode())
    write_bytes("format-only.patch", "".join(formatted).encode())
    postimage_payload = (json.dumps(complete_postimages, separators=(",", ":")) + "\n").encode()
    write_bytes("complete-postimages.json.gz", gzip.compress(postimage_payload, mtime=0))
    manifest = {
        "source_commit": EXPECTED_SOURCE, "source_tree": EXPECTED_TREE,
        "input_json": meta(payload_bytes), "input_gzip": meta(compressed),
        "rustc_version": rustc_version, "rustfmt_version": rustfmt_version,
        "rustfmt_binary": rustfmt_binary, "command": command,
        "started_at": started,
        "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "returncode": returncode, "error": error, "raw_log": meta(raw),
        "files": after_files, "format_changed": changed,
        "input_files_preserved": True,
        "checkout_access": False, "target_access": False,
        "native_tests_run": False, "native_stack_fix_proven": False,
        "qualification": "isolated five-file native diagnostic formatting only; no native or ordinary qualification",
        "artifacts": [{"path": name, **meta((RECORDS / name).read_bytes())} for name in
                      ["native-diagnostic-five-prefmt.patch", "native-diagnostic-five-formatted.patch",
                       "format-only.patch", "complete-postimages.json.gz"]],
    }
    write_json("manifest.json", manifest)
    print(json.dumps({"records": str(RECORDS), "returncode": returncode,
          "error": error, "files": len(files), "format_changed": changed,
          "manifest": meta((RECORDS / "manifest.json").read_bytes()),
          "raw_log": meta(raw), "artifacts": manifest["artifacts"],
          "complete_postimages_root": str(RECORDS / "postimages"),
          "checkout_access": False, "target_access": False}, indent=2), flush=True)

raise SystemExit(returncode if returncode is not None and error is None else 1)
