"""Read-only identity inventory. Does not sync, install, compile, fix or format."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time

T = Path("/home/alex/work/hepta-cell-unified-20261106-a")
S = T / "source"
E = T / "evidence"
O = E / "source53-formatter-tool-inventory"
FROZEN = True
EXPECTED_SOURCE_COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
EXPECTED_SOURCE_TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
SOURCE_MANIFEST_BYTES = 56747
R31_JOB_ID = "1a1b275ba33-fc05-7e17"
R31_TERMINAL_NAME = "native-workspace-r31-terminal-process-status.json"
R31_TERMINAL_BYTES = 731
R31_TERMINAL_SHA256 = '56e8d10b8a04bb14fd5ec432610878f9d648ca724d4fe860f644d7831f93047e'
SOURCE_SHA = "9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda"
ENV_SHA = "8881726a60b0881a3ebaff02997a6fb0abae955b585821c70a0ed8789f243b28"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
LOCKS = {
    "codex-rs/Cargo.lock": "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c",
    "MODULE.bazel.lock": "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb",
}
SUPPORT = {
    "justfile": "74f869224eba12fc4212b043428e7f5b35b551d26f5b06161c25d8aca525f124",
    "scripts/format.py": "8d93d7a6261bbe5f2b9fceea228154f0be29f721015d05b4f538c30076dd80b3",
    "scripts/pyproject.toml": "0b6799e50e7d0e58834615ccd885e23a78acd7b89f43f37b315cdb355cd05fc0",
    "scripts/uv.lock": "6b8e7a82d1a4f4c5d59ce57cf8be472ea031c6fb0a905506258d434132b3c99c",
}
env = os.environ.copy()
env["PATH"] = str(T / "bin") + ":/home/alex/.cargo/bin:" + env.get("PATH", "")
env["RUSTUP_TOOLCHAIN"] = "1.96.0"
env["PYTHONDONTWRITEBYTECODE"] = "1"
env["GIT_OPTIONAL_LOCKS"] = "0"

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

def write_bytes(name, data):
    with (O / name).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())

def write_json(name, value):
    write_bytes(name, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())

def git(*args):
    proc = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.quotePath=false",
         "-c", "diff.external=", *args], cwd=S, env=env, capture_output=True,
    )
    require(proc.returncode == 0, "read-only git failed: " + repr(args))
    return proc.stdout

def source_guard(manifest):
    require(git("rev-parse", "HEAD").decode().strip() == HEAD, "HEAD changed")
    expected = {row["path"]: row for row in manifest["changed_files"]}
    require(len(expected) == 197, "source count")
    require(manifest["source_commit"] == EXPECTED_SOURCE_COMMIT
            and manifest["source_tree"] == EXPECTED_SOURCE_TREE, "actual source53 identity")
    require(not git("diff", "--cached", "--no-ext-diff", "--no-textconv",
                    "--name-only", "-z", EXPECTED_SOURCE_TREE, "--"),
            "index differs from actual source53 tree")
    cached = set(git("diff", "--cached", "--no-ext-diff", "--no-textconv",
                     "--name-only", "-z", HEAD, "--").decode().split("\0")) - {""}
    require(cached == set(expected), "cached path set changed")
    require(not git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "--"),
            "unstaged paths")
    require(not git("ls-files", "--others", "--exclude-standard", "-z"), "untracked paths")
    index = {}
    for record in git("ls-files", "--stage", "-z").decode().split("\0"):
        if record:
            header, path = record.split("\t", 1)
            mode, blob, stage = header.split()
            require(stage == "0", "unmerged index")
            index[path] = (mode, blob)
    for path, row in expected.items():
        file = S / path
        st = file.lstat()
        require(stat.S_ISREG(st.st_mode), "source is not regular: " + path)
        data = file.read_bytes()
        mode = "100755" if st.st_mode & 0o111 else "100644"
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(pin(data) == {"bytes": row["bytes"], "sha256": row["sha256"]},
                "source bytes changed: " + path)
        require(mode == row["mode"] and blob == row["git_blob"]
                and index.get(path) == (mode, blob), "source index identity: " + path)
    lock_pins = {}
    for path, sha in LOCKS.items():
        p = pin((S / path).read_bytes())
        require(p["sha256"] == sha, "lock changed: " + path)
        lock_pins[path] = p
    support_pins = {}
    for path, sha in SUPPORT.items():
        p = pin((S / path).read_bytes())
        require(p["sha256"] == sha, "support changed: " + path)
        support_pins[path] = p
    return {"pass": True, "source_commit": manifest["source_commit"],
            "expected_source_tree": manifest["source_tree"], "native_head": HEAD,
            "changed_file_count": 197, "index_and_source_rows_equal": True,
            "locks": lock_pins, "support": support_pins,
            "git_write_tree_not_invoked": True}

def executable_identity(path):
    if path is None:
        return {"found": False}
    p = Path(path)
    if not p.exists():
        return {"found": False, "requested": str(p)}
    st = p.lstat()
    real = p.resolve(strict=True)
    rst = real.stat()
    require(stat.S_ISREG(rst.st_mode), "resolved executable not regular")
    data = real.read_bytes()
    return {"found": True, "requested": str(p), "resolved": str(real),
            "requested_is_symlink": stat.S_ISLNK(st.st_mode),
            "mode": oct(stat.S_IMODE(rst.st_mode)), "uid": rst.st_uid,
            "gid": rst.st_gid, **pin(data)}

def version_probe(name, argv, cwd):
    started = time.time()
    proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True)
    ended = time.time()
    raw = {"name": name, "command": argv, "cwd": str(cwd),
           "start_unix": started, "end_unix": ended,
           "exit_code": proc.returncode}
    write_json(name + "-raw-process-result.json", raw)
    write_bytes(name + ".stdout", proc.stdout)
    write_bytes(name + ".stderr", proc.stderr)
    raw.update({"stdout": pin(proc.stdout), "stderr": pin(proc.stderr)})
    write_json(name + "-receipt.json", raw)
    return raw, proc.stdout, proc.stderr

def r31_closed_prerequisite():
    require(type(R31_TERMINAL_BYTES) is int and R31_TERMINAL_BYTES > 0,
            "actual R31 terminal byte count is unbound")
    require(isinstance(R31_TERMINAL_SHA256, str) and len(R31_TERMINAL_SHA256) == 64
            and all(c in "0123456789abcdef" for c in R31_TERMINAL_SHA256),
            "actual R31 terminal SHA256 is unbound")
    raw = (E / R31_TERMINAL_NAME).read_bytes()
    require(pin(raw) == {"bytes": R31_TERMINAL_BYTES, "sha256": R31_TERMINAL_SHA256},
            "actual R31 terminal bytes differ")
    terminal = json.loads(raw)
    require(terminal["job_id"] == R31_JOB_ID
            and terminal["state"] in ("succeeded", "failed")
            and type(terminal["exit_code"]) is int, "R31 is not naturally terminal")
    require(terminal["output_complete"] is True and terminal["output_durable"] is True
            and terminal["terminal_publication_confirmed"] is True,
            "R31 controller output has not durably closed")
    require(terminal["automatic_retry"] is False and terminal["cancelled"] is False
            and terminal["timed_out"] is False, "R31 did not close naturally")
    for stream in ("stdout", "stderr"):
        require(terminal["log_bytes"][stream]["seen"] == terminal["log_bytes"][stream]["stored"]
                and terminal["log_truncated"][stream] is False
                and terminal["log_synced"][stream] is True
                and terminal["log_errors"][stream] is None,
                "R31 original controller stream is not complete")
    return terminal, {"path": R31_TERMINAL_NAME, **pin(raw)}

def main():
    require(FROZEN, "preparation only: inventory is not authorized or bound")
    terminal, terminal_pin = r31_closed_prerequisite()
    manifest_data = (E / "native-candidate-r30-source.json").read_bytes()
    require(len(manifest_data) == SOURCE_MANIFEST_BYTES, "source manifest byte count")
    require(pin(manifest_data)["sha256"] == SOURCE_SHA, "source manifest identity")
    manifest = json.loads(manifest_data)
    formatter_data = (E / "native-final-formatter-env.json").read_bytes()
    require(pin(formatter_data)["sha256"] == ENV_SHA, "formatter env identity")
    formatter = json.loads(formatter_data)
    require(formatter == {
        "UV_PROJECT_ENVIRONMENT": str(T / "tools/python-scripts-env"),
        "UV_CACHE_DIR": str(T / "tools/uv-cache"),
        "UV_PYTHON_DOWNLOADS": "never",
    }, "formatter env values")
    pre = source_guard(manifest)
    O.mkdir(exist_ok=False)
    write_json("source-before.json", pre)
    write_bytes("formatter-env-original.json", formatter_data)
    result = {"schema": "hepta.source53-formatter-readonly-inventory.v1",
              "source_commit": manifest["source_commit"], "source_tree": manifest["source_tree"],
              "source_manifest": pin(manifest_data), "formatter_env": pin(formatter_data),
              "effective_path": env["PATH"], "toolchain": env["RUSTUP_TOOLCHAIN"],
              "tools": {}, "formatter_commands_executed": False,
              "sync_install_compile_fix_executed": False,
              "active_rust_environment_modified": False,
              "workspace_terminal_observed": terminal_pin,
              "workspace_terminal_state": terminal["state"],
              "workspace_original_exit_code": terminal["exit_code"],
              "workspace_pass_not_implied_by_inventory": True,
              "diagnostic_only": True, "behavior_repair_claimed": False}
    issues = []
    try:
        for name in ("just", "python3", "uv"):
            path = shutil.which(name, path=env["PATH"])
            identity = executable_identity(path)
            result["tools"][name] = {"identity": identity}
            if path:
                r, out, err = version_probe(name, [path, "--version"], S / "codex-rs")
                result["tools"][name]["version"] = r
                result["tools"][name]["version_stdout"] = out.decode("utf-8", errors="replace")
                result["tools"][name]["version_stderr"] = err.decode("utf-8", errors="replace")
        rustup = shutil.which("rustup", path=env["PATH"])
        result["rustup_resolver_identity"] = executable_identity(rustup)
        if rustup:
            r, out, err = version_probe("rustfmt-path",
                                       [rustup, "which", "--toolchain", "1.96.0", "rustfmt"], S)
            result["rustfmt_path_query"] = r
            if r["exit_code"] == 0:
                path = out.decode().strip()
                require(Path(path).is_absolute(), "rustfmt path is not absolute")
                identity = executable_identity(path)
                vr, vout, verr = version_probe("rustfmt", [path, "--version"], S / "codex-rs")
                result["tools"]["rustfmt-1.96.0"] = {
                    "identity": identity, "version": vr,
                    "version_stdout": vout.decode("utf-8", errors="replace"),
                    "version_stderr": verr.decode("utf-8", errors="replace"),
                }
        ruff = Path(formatter["UV_PROJECT_ENVIRONMENT"]) / "bin" / "ruff"
        result["tools"]["ruff"] = {"identity": executable_identity(ruff),
                                    "locked_version": "0.15.13"}
        if ruff.exists():
            vr, vout, verr = version_probe("ruff", [str(ruff), "--version"], S)
            result["tools"]["ruff"].update({
                "version": vr, "version_stdout": vout.decode("utf-8", errors="replace"),
                "version_stderr": verr.decode("utf-8", errors="replace"),
                "matches_locked_version": vr["exit_code"] == 0 and vout.strip() == b"ruff 0.15.13",
            })
        venv = Path(formatter["UV_PROJECT_ENVIRONMENT"])
        result["project_environment_exists"] = venv.is_dir()
        result["uv_cache_exists"] = Path(formatter["UV_CACHE_DIR"]).is_dir()
        pyvenv = venv / "pyvenv.cfg"
        if pyvenv.is_file():
            data = pyvenv.read_bytes()
            write_bytes("pyvenv.cfg", data)
            result["pyvenv_cfg"] = pin(data)
    except Exception as exc:
        issues.append({"stage": "inventory", "error": repr(exc)})
    finally:
        try:
            post = source_guard(manifest)
            write_json("source-after.json", post)
            result["source_guard_pass"] = True
        except Exception as exc:
            issues.append({"stage": "source-postguard", "error": repr(exc)})
            result["source_guard_pass"] = False
        result["issues"] = issues
        result["inventory_complete"] = not issues
        write_json("inventory.json", result)
    print(json.dumps({"directory": str(O), "inventory_complete": result["inventory_complete"],
                      "source_guard_pass": result["source_guard_pass"]}))
    return 0 if result["inventory_complete"] else 1

if __name__ == "__main__":
    sys.exit(main())
