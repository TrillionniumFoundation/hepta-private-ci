"""Run production Windows token/ACL code in an isolated, locked native probe.

The output distinguishes completed observations from permissions satisfying the
original invariants. This diagnostic never alters the main Cargo workspace.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib

if __package__:
    from . import ops_windows_acl_probe_package as packaging
else:
    import ops_windows_acl_probe_package as packaging


RELATIVE = Path("experiments/multimodal_output_portfolio/closure_20261028")
PRODUCTION = tuple(
    f"codex-rs/windows-sandbox-rs/src/{name}.rs"
    for name in ("token", "acl", "acl_deny", "winutil", "legacy_admission", "elevated_admission")
)
CONFIG = (
    "codex-rs/Cargo.lock",
    "codex-rs/Cargo.toml",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/windows-sandbox-rs/Cargo.toml",
    ".github/workflows/ndu-windows-storage-probe.yml",
    "codex-rs/.cargo/config.toml",
    "experiments/multimodal_output_portfolio/closure_20261028/ops_windows_acl_probe_package.py",
)
HARNESS = ("ops_windows_acl_probe.rs", "ops_windows_acl_probe_support.rs")



REPAIRS = {"partial.repair.root", "partial.repeat.root", "partial.repair.file", "partial.repeat.file"}
ALLOWED_OPS = {f"broad.allowed.{index}.{operation}" for index in range(2) for operation in ("create", "delete_file", "delete_directory")}
REFUSED_OPS = {f"broad.refuse.{operation}" for operation in ("overwrite", "create", "delete_file", "delete_directory", "delete_protected")}
CHECKS = REPAIRS | ALLOWED_OPS | REFUSED_OPS | {
    "partial.before.overwrite_allowed", "partial.full_read_preserved",
    "partial.after.overwrite", "partial.after.create", "partial.final.content_preserved",
    "partial.final.no_created_file", "broad.full_read_preserved",
    "broad.final.outside_content_preserved", "broad.final.outside_directory_preserved",
    "broad.final.protected_directory_preserved", "broad.final.no_outside_created_file",
}
OPS = ALLOWED_OPS | REFUSED_OPS | {"partial.before.overwrite", "partial.after.read", "partial.after.overwrite", "partial.after.create", "broad.outside.read"}
OPEN_LABELS = {"partial.after.file", "partial.after.parent", "broad.outside.file", "broad.outside.parent", "broad.allowed.file", "broad.allowed.parent", "broad.protected.directory"}
OPEN_MASKS = {
    "read_data": "00000001", "write_data_or_add_file": "00000002",
    "append_data_or_add_directory": "00000004", "write_attributes": "00000100",
    "read_control": "00020000", "delete": "00010000", "delete_and_write_data": "00010002",
    "delete_child": "00000040", "delete_child_and_add_file": "00000042",
    "generic_read": "80000000", "generic_write": "40000000", "generic_all": "10000000",
}
ACL_LABELS = REPAIRS | {"partial.before.root", "partial.before.file", "broad.fixture", "broad.allowed.parent", "broad.allowed.file", "broad.outside.parent", "broad.outside.file", "broad.protected.directory"}
TOKEN_LABELS = {"partial.production", "broad.base", "broad.production"}
TOKEN_KINDS = {"user", "normal", "restricting"}


def exact_rows(rows, kind, fields, expected):
    selected = [row for row in rows if row["kind"] == kind]
    keys = [tuple(row[field] for field in fields) for row in selected]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError(f"missing, duplicate, or unexpected {kind} observations")
    return selected


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args, input=None):
    return subprocess.check_output(["git", "-C", str(root), *args], input=input)


def source_controls():
    paths = (*PRODUCTION, *CONFIG, *((RELATIVE / p).as_posix() for p in HARNESS))
    return (*paths, (RELATIVE / "ops_windows_acl_probe.py").as_posix())


def source_paths(root):
    return tuple(packaging.source_entries(root, git, source_controls()))


def bind_sources(root, expected_head):
    head = git(root, "rev-parse", "HEAD").decode().strip()
    if head != expected_head or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("checkout is not the exact requested commit")
    entries = packaging.source_entries(root, git, source_controls())
    request = b"".join(blob.encode("ascii") + b"\n" for _, blob in entries.values())
    payload = git(root, "cat-file", "--batch", input=request)
    records, blobs, position = {}, {}, 0
    for path, (mode, blob) in entries.items():
        boundary = payload.index(b"\n", position)
        observed_blob, kind, size = payload[position:boundary].decode("ascii").split()
        size = int(size)
        begin, end = boundary + 1, boundary + 1 + size
        content = payload[begin:end]
        if (observed_blob != blob or kind != "blob" or size < 0
                or len(content) != size or payload[end:end + 1] != b"\n"
                or hashlib.sha1(f"blob {size}\0".encode() + content).hexdigest() != blob):
            raise ValueError(f"invalid committed source payload: {path}")
        position = end + 1
        source = root / path
        if (any(parent.is_symlink() for parent in (source, *source.parents)
                if parent != root and parent.is_relative_to(root))
                or not source.resolve().is_relative_to(root.resolve())
                or source.read_bytes() != content):
            raise ValueError(f"working-tree bytes differ from commit: {path}")
        records[path] = {"git_blob": blob, "mode": mode, "sha256": sha(content)}
        blobs[path] = content
    if position != len(payload):
        raise ValueError("unexpected trailing committed source payload")
    if git(root, "diff", "--cached", "HEAD", "--", *packaging.PACKAGE_ROOTS, *source_controls()):
        raise ValueError("index differs from commit for bound production or probe sources")
    return records, blobs


def dependency_closure(lock_bytes):
    return packaging.dependency_closure(lock_bytes)


def prepare(crate, blobs):
    return packaging.prepare(crate, blobs, RELATIVE)



def observations(stdout):
    schemas = {
        "CHECK": ("name", "passed"),
        "OP": ("name", "succeeded", "os_error", "error_kind"),
        "OPEN": ("name", "access", "mask_hex", "succeeded", "os_error"),
        "ACL": ("name", "ace_count"),
        "ACE": ("name", "index", "type", "flags_hex", "mask_hex", "mapped_mask_hex", "sid"),
        "TOKEN": ("name", "group_kind", "index", "attributes_hex", "sid"),
        "GROUPS": ("name", "group_kind", "count"),
        "FLAG": ("name", "flag", "value"),
        "REPAIR": ("name", "rewritten"),
        "DONE": ("completed_cases",),
    }
    rows = []
    for line in stdout.splitlines():
        kind, *fields = line.split("\t")
        if kind not in schemas or len(fields) != len(schemas[kind]):
            raise ValueError(f"invalid observation row: {line!r}")
        row = {"kind": kind, **dict(zip(schemas[kind], fields))}
        for field in ("passed", "succeeded", "rewritten"):
            if field in row:
                if row[field] not in ("true", "false"):
                    raise ValueError("invalid observation boolean")
                row[field] = row[field] == "true"
        rows.append(row)
    if sum(r["kind"] == "DONE" for r in rows) != 1 or rows[-1] != {
        "kind": "DONE", "completed_cases": "2"
    }:
        raise ValueError("incomplete native observation")
    exact_rows(rows, "CHECK", ("name",), {(name,) for name in CHECKS})
    exact_rows(rows, "OP", ("name",), {(name,) for name in OPS})
    exact_rows(rows, "REPAIR", ("name",), {(name,) for name in REPAIRS})
    exact_rows(rows, "OPEN", ("name", "access", "mask_hex"), {
        (name, access, mask) for name in OPEN_LABELS for access, mask in OPEN_MASKS.items()
    })
    acls = exact_rows(rows, "ACL", ("name",), {(name,) for name in ACL_LABELS})
    if any(int(row["ace_count"]) <= 0 for row in acls):
        raise ValueError("empty ACL observation")
    exact_rows(rows, "ACE", ("name", "index"), {
        (row["name"], str(index)) for row in acls for index in range(int(row["ace_count"]))
    })
    groups = exact_rows(rows, "GROUPS", ("name", "group_kind"), {
        (name, kind) for name in TOKEN_LABELS for kind in TOKEN_KINDS
    })
    if any(int(row["count"]) < 0 or (row["group_kind"] == "user" and row["count"] != "1") for row in groups):
        raise ValueError("invalid token group count")
    exact_rows(rows, "TOKEN", ("name", "group_kind", "index"), {
        (row["name"], row["group_kind"], str(index)) for row in groups for index in range(int(row["count"]))
    })
    exact_rows(rows, "FLAG", ("name", "flag"), {(name, "restricted") for name in TOKEN_LABELS})
    return rows


def refusal_observations(stdout):
    """Validate a completed admission refusal, not the historical permission cases."""
    rows = []
    for line in stdout.splitlines():
        fields = line.split("\t")
        if len(fields) == 3 and fields[0] == "ADMISSION":
            if fields[2] != "LegacyWindowsSandboxIsolationUnavailable":
                raise ValueError("unexpected native admission error type")
            rows.append({"kind": fields[0], "name": fields[1], "error_type": fields[2]})
        elif fields == ["FIXTURE", "unchanged", "true"]:
            rows.append({"kind": "FIXTURE", "unchanged": True})
        elif fields == ["DONE", "0"]:
            rows.append({"kind": "DONE", "completed_permission_cases": 0})
        else:
            raise ValueError(f"invalid refusal observation row: {line!r}")
    if len(rows) != 4 or rows[-2:] != [
        {"kind": "FIXTURE", "unchanged": True},
        {"kind": "DONE", "completed_permission_cases": 0},
    ]:
        raise ValueError("incomplete native refusal observation")
    exact_rows(rows, "ADMISSION", ("name",), {("partial",), ("broad",)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "hepta.windows-acl-native-observation.v2",
        "observation_mode": "production_legacy_admission",
        "expected_head": args.expected_head,
        "qualification": False,
        "scope": "Only newly created temporary fixture trees; unchanged production token flags and ACL APIs.",
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    code = 1
    try:
        if sys.platform != "win32":
            raise RuntimeError("This diagnostic requires native Windows; no substitute execution.")
        root = Path(__file__).resolve().parents[3]
        records, blobs = bind_sources(root, args.expected_head)
        report["sources"] = records
        toolchain = tomllib.loads(blobs[CONFIG[2]].decode())["toolchain"]["channel"]
        if not re.fullmatch(r"\d+\.\d+\.\d+", toolchain):
            raise ValueError("production toolchain is not an exact release")
        report["toolchain"] = toolchain
        with tempfile.TemporaryDirectory(prefix="hepta-acl-native-") as temporary:
            temporary = Path(temporary).resolve()
            crate, fixture = temporary / "crate", temporary / "fixture"
            fixture.mkdir()
            manifest, locked, copies = prepare(crate, blobs)
            (output / "isolated-Cargo.toml").write_bytes(manifest)
            (output / "isolated-Cargo.lock").write_bytes(locked)
            command = ["cargo", f"+{toolchain}", "run", "--locked", "--manifest-path", str(crate / "Cargo.toml"),
                       "--package", "codex-windows-sandbox", "--bin", packaging.BINARY_NAME,
                       "--target-dir", str(crate / "target"), "--", str(fixture)]
            report["command"] = command
            with (output / "native-stdout.tsv").open("wb") as stdout, (output / "native-stderr.log").open("wb") as stderr:
                completed = subprocess.run(command, cwd=crate, stdout=stdout, stderr=stderr, timeout=480)
            report["native_exit_code"] = completed.returncode
            if (crate / "Cargo.lock").read_bytes() != locked:
                raise ValueError("isolated lock changed during --locked execution")
            final_records, _ = bind_sources(root, args.expected_head)
            if final_records != records:
                raise ValueError("production or probe source binding changed during observation")
            if completed.returncode:
                raise RuntimeError("native build or probe failed; inspect native-stderr.log")
            for source, expected in copies.items():
                if (crate / source).read_bytes() != expected:
                    raise ValueError(f"copied production or generated package source changed during observation: {source}")
            rows = refusal_observations((output / "native-stdout.tsv").read_text(encoding="utf-8"))
            report["observations"] = rows
            report["completed_permission_cases"] = 0
            report["original_permission_invariants_observed"] = False
            report["all_observed_invariants_held"] = None
            report["status"] = "legacy_backend_refused"
            code = 0
    except Exception as error:
        report["status"] = "observation_failed"
        report["error"] = f"{type(error).__name__}: {error}"
    (output / "OBSERVATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
