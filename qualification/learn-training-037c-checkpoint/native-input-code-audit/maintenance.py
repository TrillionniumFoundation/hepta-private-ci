#!/usr/bin/env python3
"""Retain one exact-source dependency or maintenance attempt; no qualification."""
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

parser = argparse.ArgumentParser()
parser.add_argument("--mode", required=True, choices=("fetch", "fix"))
parser.add_argument("--source", required=True)
parser.add_argument("--tree", required=True)
parser.add_argument("--records", required=True)
parser.add_argument("--request-key", required=True)
args = parser.parse_args()
REPO = Path("/home/qian-qi/hepta-learn-common-20261112-037c")
RECORDS = Path(args.records)
TARGET = Path("/data/hepta-learn-037c-20261112/target-cold-4ab-v1")
EVIDENCE = Path("/home/qian-qi/hepta-learn-037c-evidence")
NEXTEST = Path("/home/qian-qi/hepta-learn-037c-tools/nextest-0.9.103-e999c122/cargo-nextest")
V8 = Path("/home/qian-qi/hepta-learn-037c-evidence/v8-input-recovery-4ab-v2/verified-inputs")
if RECORDS.parent != EVIDENCE or not RECORDS.name:
    raise SystemExit("records must be a new immediate child of own evidence root")
if os.getuid() == 0:
    raise SystemExit("ordinary maintenance must run as desktop operator")
if len(args.source) != 40 or len(args.tree) != 40 or any(c not in "0123456789abcdef" for c in args.source + args.tree):
    raise SystemExit("exact source and tree required")
RECORDS.mkdir(mode=0o700, exist_ok=False)
os.chdir(REPO)

def now():
    return datetime.now(timezone.utc).isoformat()

def git(*words):
    return subprocess.check_output(["git", "--no-optional-locks", *words], cwd=REPO)

def identity():
    return {"commit": git("rev-parse", "HEAD").decode().strip(),
            "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
            "dirty": git("status", "--porcelain=v1", "--untracked-files=all").decode()}

def save(name, value):
    with (RECORDS / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def snapshot(label):
    names = git("ls-files", "-z") + git("ls-files", "--others", "--exclude-standard", "-z")
    rows = []
    for raw in sorted(set(names.split(b"\0")) - {b""}):
        rel = os.fsdecode(raw)
        p = REPO / rel
        if not p.exists() and not p.is_symlink():
            rows.append({"path": rel, "missing": True})
            continue
        data = os.fsencode(os.readlink(p)) if p.is_symlink() else p.read_bytes()
        mode = "120000" if p.is_symlink() else ("100755" if p.stat().st_mode & 0o111 else "100644")
        rows.append({"path": rel, "mode": mode, "bytes": len(data),
                     "sha256": hashlib.sha256(data).hexdigest(),
                     "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    with gzip.open(RECORDS / (label + ".files.json.gz"), "xb") as stream:
        stream.write(encoded)
    observed = {**identity(), "file_count": len(rows),
                "inventory_sha256": hashlib.sha256(encoded).hexdigest(),
                "cargo_lock_sha256": sha(REPO / "codex-rs/Cargo.lock")}
    save(label + ".json", observed)
    print(json.dumps({"snapshot": label, **observed}), flush=True)
    return observed

def execute(name, command, env):
    started = now()
    path = RECORDS / (name + ".raw.log")
    digest, size = hashlib.sha256(), 0
    cwd = REPO / "codex-rs"
    with path.open("xb", buffering=0) as output:
        process = subprocess.Popen(command, cwd=cwd, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(json.dumps({"phase": name, "pid": process.pid, "command": command,
                          "cwd": str(cwd), "started_at": started,
                          "timeout_or_kill_policy": "none; await actual process exit"}), flush=True)
        while True:
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        status = process.wait()
        process.stdout.close()
        os.fsync(output.fileno())
    observed = {"command": command, "cwd": str(cwd), "started_at": started,
                "finished_at": now(), "returncode": status, "log_file": path.name,
                "log_bytes": size, "log_sha256": digest.hexdigest(),
                "actual_process_exit_observed": True, "controller_kill": False}
    save(name + ".json", observed)
    return observed

result = {"kind": "exact-source-" + args.mode + "-only", "qualification": False,
          "source_sha": args.source, "source_tree": args.tree,
          "request_key": args.request_key, "started_at": now(), "status": "running"}
save("started.json", result)
save("invocation.json", {"request_key": args.request_key, "host": "desktop",
     "executable": sys.executable, "argv": sys.argv,
     "script_sha256": sha(Path(__file__)), "launch_cwd": str(REPO),
     "uid": os.getuid(), "gid": os.getgid()})
before = None
exit_code = 1
try:
    exact = identity()
    if exact != {"commit": args.source, "tree": args.tree, "dirty": ""}:
        raise RuntimeError("own checkout is not the exact clean source: " + repr(exact))
    if sha(REPO / "AGENTS.md") != "c3f80e8386eb170b00af1e21de40d770c4941e464915687e728e2d14a7e79480":
        raise RuntimeError("AGENTS changed; read instructions before dispatch")
    instructions = [REPO / "codex-rs/AGENTS.md", *list((REPO / "codex-rs/hepta-agentd").rglob("AGENTS.md"))]
    if any(p.exists() for p in instructions):
        raise RuntimeError("additional scoped AGENTS require inspection")
    lock = REPO / "codex-rs/Cargo.lock"
    versions = {p["version"] for p in tomllib.loads(lock.read_text())["package"] if p["name"] == "v8"}
    if versions != {"150.4.0"}:
        raise RuntimeError("V8 version differs from verified native pair")
    archive = V8 / "librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz"
    binding = V8 / "src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs"
    inputs = [(archive, "a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583"),
              (binding, "7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506"),
              (NEXTEST, "e999c122a02c3fe74a1b66d254b6419a8a665e8bf540b1d31de7933a6d3753f1")]
    for p, expected in inputs:
        if sha(p) != expected:
            raise RuntimeError("verified native input changed: " + str(p))
    if not TARGET.is_dir() or TARGET.is_symlink() or TARGET.stat().st_uid != os.getuid():
        raise RuntimeError("own existing target is absent or has unexpected identity")
    env = dict(os.environ)
    env.update(PATH=str(NEXTEST.parent) + ":/home/qian-qi/.cargo/bin:/home/qian-qi/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
               RUSTUP_HOME="/home/qian-qi/.rustup", RUSTUP_TOOLCHAIN="1.96.0",
               CARGO_HOME="/home/qian-qi/.cargo", CARGO_TARGET_DIR=str(TARGET),
               CARGO_BUILD_JOBS="2", CARGO_INCREMENTAL="0",
               CARGO_PROFILE_TEST_DEBUG="0", CARGO_PROFILE_DEV_DEBUG="0",
               CARGO_NET_OFFLINE="false" if args.mode == "fetch" else "true",
               CARGO_NET_GIT_FETCH_WITH_CLI="true", CARGO_TERM_COLOR="never",
               PYTHONDONTWRITEBYTECODE="1", CODEX_REPO_ROOT=str(REPO),
               PYTHONPATH=str(REPO / "scripts"),
               RUSTY_V8_ARCHIVE=str(archive), RUSTY_V8_SRC_BINDING_PATH=str(binding),
               SOURCE_SHA=args.source, TESTED_SHA=args.source, HEPTA_CI_LANE="source-head")
    keys = ("PATH", "RUSTUP_HOME", "RUSTUP_TOOLCHAIN", "CARGO_HOME", "CARGO_TARGET_DIR",
            "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL", "CARGO_PROFILE_TEST_DEBUG",
            "CARGO_PROFILE_DEV_DEBUG", "CARGO_NET_OFFLINE", "CARGO_NET_GIT_FETCH_WITH_CLI",
            "CARGO_TERM_COLOR", "PYTHONDONTWRITEBYTECODE", "CODEX_REPO_ROOT", "PYTHONPATH",
            "RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH", "RUSTFLAGS", "RUSTDOCFLAGS",
            "CARGO_ENCODED_RUSTFLAGS", "RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
            "LIBCLANG_PATH", "BINDGEN_EXTRA_CLANG_ARGS", "PROTOC", "CMAKE", "CC", "CXX",
            "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "SOURCE_SHA", "TESTED_SHA", "HEPTA_CI_LANE")
    disk = os.statvfs(str(TARGET))
    save("native-environment.json", {"environment": {k: env.get(k) for k in keys},
         "network_variables_present": {k: k in env for k in
          ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
           "SSL_CERT_FILE", "SSL_CERT_DIR", "CARGO_HTTP_CAINFO", "GIT_SSL_CAINFO")},
         "cargo_lock_sha256": sha(lock), "v8_versions": sorted(versions),
         "native_inputs": [{"path": str(p), "sha256": expected, "bytes": p.stat().st_size} for p, expected in inputs],
         "available_disk_bytes": disk.f_bavail * disk.f_frsize,
         "mem_available": next(line for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))})
    for name, command in [("rustc-version", ["rustc", "--version", "--verbose"]),
                          ("cargo-version", ["cargo", "--version"]),
                          ("just-version", ["just", "--version"]),
                          ("nextest-version", ["cargo", "nextest", "--version"])]:
        if execute(name, command, env)["returncode"]:
            raise RuntimeError(name + " failed")
    if not (RECORDS / "nextest-version.raw.log").read_text().startswith("cargo-nextest 0.9.103 "):
        raise RuntimeError("cargo dispatcher did not use pinned nextest")
    before = snapshot("source-before")
    command = (["cargo", "fetch", "--locked", "--target", "x86_64-unknown-linux-gnu"] if args.mode == "fetch"
               else ["just", "fix", "-p", "codex-hepta-agentd", "--locked", "--offline"])
    executed = execute("cargo-fetch" if args.mode == "fetch" else "just-fix", command, env)
    result["execution"] = executed
    exit_code = executed["returncode"] if executed["returncode"] >= 0 else 128 - executed["returncode"]
    result["status"] = "passed" if exit_code == 0 else "failed"
except Exception as error:
    result.update(status="failed", error=type(error).__name__ + ": " + str(error))
finally:
    try:
        after = snapshot("source-after")
        result.update(before=before, after=after)
        patch = git("diff", "--binary", "HEAD", "--")
        (RECORDS / "maintenance.patch").write_bytes(patch)
        changed = git("diff", "--name-only", "--no-renames", "-z", "HEAD", "--")
        images = []
        for raw in changed.split(b"\0"):
            if not raw:
                continue
            rel = os.fsdecode(raw)
            p = REPO / rel
            if not p.is_file():
                images.append({"path": rel, "missing": True})
                continue
            data = p.read_bytes()
            destination = RECORDS / "postimages" / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as out:
                out.write(data)
            images.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                           "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})
        save("postimages.json", {"files": images, "patch_bytes": len(patch), "patch_sha256": hashlib.sha256(patch).hexdigest()})
        result["postimages"] = {"file_count": len(images), "patch_bytes": len(patch), "patch_sha256": hashlib.sha256(patch).hexdigest()}
        if before is not None and (after["commit"] != before["commit"] or
                                  after["cargo_lock_sha256"] != before["cargo_lock_sha256"] or
                                  (args.mode == "fetch" and after != before)):
            result.update(status="failed", source_identity_changed=True)
            exit_code = exit_code or 1
    except Exception as error:
        result["retention_error"] = type(error).__name__ + ": " + str(error)
        result["status"] = "failed"
        exit_code = exit_code or 1
    result.update(finished_at=now(), exit_code=exit_code)
    save("result.json", result)
    print(json.dumps({"attempt_result": result}, sort_keys=True), flush=True)
raise SystemExit(exit_code)
