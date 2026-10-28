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


RELATIVE = Path("experiments/multimodal_output_portfolio/closure_20261028")
PRODUCTION = tuple(
    f"codex-rs/windows-sandbox-rs/src/{name}.rs"
    for name in ("token", "acl", "winutil")
)
CONFIG = (
    "codex-rs/Cargo.lock",
    "codex-rs/Cargo.toml",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/windows-sandbox-rs/Cargo.toml",
    ".github/workflows/ndu-windows-storage-probe.yml",
)
HARNESS = ("ops_windows_acl_probe.rs", "ops_windows_acl_probe_support.rs")
FEATURES = (
    "Win32_Foundation",
    "Win32_Security",
    "Win32_Security_Authorization",
    "Win32_System_Threading",
    "Win32_System_Diagnostics_Debug",
    "Win32_Storage_FileSystem",
)


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


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def bind_sources(root, expected_head):
    head = git(root, "rev-parse", "HEAD").decode().strip()
    if head != expected_head or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("checkout is not the exact requested commit")
    paths = (*PRODUCTION, *CONFIG, *((RELATIVE / p).as_posix() for p in HARNESS))
    paths += ((RELATIVE / "ops_windows_acl_probe.py").as_posix(),)
    records, blobs = {}, {}
    for path in paths:
        entry = git(root, "ls-tree", "HEAD", "--", path).decode().strip()
        metadata, listed = entry.split("\t")
        mode, kind, blob = metadata.split()
        content = git(root, "cat-file", "blob", blob)
        if listed != path or kind != "blob" or mode != "100644":
            raise ValueError(f"unexpected committed source kind/mode: {path}")
        if (root / path).is_symlink() or (root / path).read_bytes() != content:
            raise ValueError(f"working-tree bytes differ from commit: {path}")
        if git(root, "diff", "--cached", "HEAD", "--", path):
            raise ValueError(f"index differs from commit: {path}")
        records[path] = {"git_blob": blob, "mode": mode, "sha256": sha(content)}
        blobs[path] = content
    return records, blobs


def dependency_closure(lock_bytes):
    packages = tomllib.loads(lock_bytes.decode())["package"]
    by_key = {(p["name"], p["version"]): p for p in packages}
    pending = [("anyhow", "1.0.103"), ("windows-sys", "0.52.0")]
    selected = {}
    while pending:
        key = pending.pop()
        if key in selected:
            continue
        package = by_key[key]
        if package.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
            raise ValueError(f"non-registry dependency: {key}")
        if not re.fullmatch(r"[0-9a-f]{64}", package.get("checksum", "")):
            raise ValueError(f"missing registry checksum: {key}")
        selected[key] = package
        for dependency in package.get("dependencies", []):
            fields = dependency.split()
            candidates = [k for k in by_key if k[0] == fields[0]]
            if len(fields) > 1:
                candidates = [k for k in candidates if k[1] == fields[1]]
            if len(candidates) != 1:
                raise ValueError(f"ambiguous dependency: {dependency}")
            pending.append(candidates[0])
    if len({key[0] for key in selected}) != len(selected):
        raise ValueError("unexpected duplicate-version dependency closure")
    return [selected[key] for key in sorted(selected)]


def isolated_lock(packages):
    root = {
        "name": "hepta-windows-acl-native-probe",
        "version": "0.0.0",
        "dependencies": ["anyhow", "windows-sys"],
    }
    lines = ["# This file is automatically @generated by Cargo.", "# It is not intended for manual editing.", "version = 4", ""]
    for package in sorted([root, *packages], key=lambda p: (p["name"], p["version"])):
        lines.append("[[package]]")
        for key in ("name", "version", "source", "checksum"):
            if key in package:
                lines.append(f"{key} = {json.dumps(package[key])}")
        if package.get("dependencies"):
            dependencies = [p.split()[0] for p in package["dependencies"]]
            lines.append("dependencies = [")
            lines.extend(f" {json.dumps(dependency)}," for dependency in dependencies)
            lines.append("]")
        lines.append("")
    return "\n".join(lines).encode()


def prepare(crate, blobs):
    (crate / "src").mkdir(parents=True)
    for source in PRODUCTION:
        (crate / "src" / Path(source).name).write_bytes(blobs[source])
    for source, target in zip(HARNESS, ("main.rs", "support.rs")):
        (crate / "src" / target).write_bytes(blobs[(RELATIVE / source).as_posix()])
    edition = tomllib.loads(blobs[CONFIG[1]].decode())["workspace"]["package"]["edition"]
    if edition not in ("2021", "2024"):
        raise ValueError("unexpected production Rust edition")
    manifest = (
        '[package]\nname = "hepta-windows-acl-native-probe"\nversion = "0.0.0"\n'
        f'edition = "{edition}"\n\n[workspace]\n\n[dependencies]\n'
        'anyhow = "=1.0.103"\n[dependencies.windows-sys]\nversion = "=0.52.0"\n'
        f"features = {json.dumps(FEATURES)}\n"
    ).encode()
    locked = isolated_lock(dependency_closure(blobs[CONFIG[0]]))
    (crate / "Cargo.toml").write_bytes(manifest)
    (crate / "Cargo.lock").write_bytes(locked)
    return manifest, locked


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "hepta.windows-acl-native-observation.v1",
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
            manifest, locked = prepare(crate, blobs)
            (output / "isolated-Cargo.toml").write_bytes(manifest)
            (output / "isolated-Cargo.lock").write_bytes(locked)
            command = ["cargo", f"+{toolchain}", "run", "--locked", "--manifest-path", str(crate / "Cargo.toml"), "--target-dir", str(crate / "target"), "--", str(fixture)]
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
            for source in PRODUCTION:
                if (crate / "src" / Path(source).name).read_bytes() != blobs[source]:
                    raise ValueError("copied production source changed during observation")
            rows = observations((output / "native-stdout.tsv").read_text(encoding="utf-8"))
            report["observations"] = rows
            report["invariant_failures"] = [r["name"] for r in rows if r["kind"] == "CHECK" and not r["passed"]]
            report["all_observed_invariants_held"] = not report["invariant_failures"]
            report["status"] = "observations_completed"
            code = 0
    except Exception as error:
        report["status"] = "observation_failed"
        report["error"] = f"{type(error).__name__}: {error}"
    (output / "OBSERVATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
