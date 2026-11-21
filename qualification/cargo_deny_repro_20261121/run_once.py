#!/usr/bin/env python3
"""Draft worker: acquire declared inputs, freeze them, run one offline check."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.parse
import urllib.request

INPUT_FILE_CAP = 4 * 1024 ** 3
OUTPUT_CAP = 128 * 1024 ** 2
METADATA_CAP = 64 * 1024 ** 2
RECEIPT_CAP = 1024 ** 2
INPUT_COUNT_CAP = 100000
INPUT_TOTAL_CAP = 10 * 1024 ** 3
PATH_BYTES_CAP = 1024
RECORD_BYTES_CAP = 4096

def digest(path, deadline=None):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError("ABSOLUTE_DEADLINE_DURING_HASH")
            h.update(block)
    return h.hexdigest()

def emit(path, value, cap=RECEIPT_CAP):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > cap:
        raise RuntimeError("RECEIPT_SIZE_LIMIT")
    with Path(path).open("xb") as f:
        f.write(raw)

def main():
    ap = argparse.ArgumentParser()
    for name in ("repo", "contract", "root", "head", "unit"):
        ap.add_argument("--" + name, required=True)
    a = ap.parse_args()
    repo, root = Path(a.repo).resolve(), Path(a.root).resolve()
    out, work = root / "out", root / "work"
    contract_path = Path(a.contract).resolve()
    c = json.loads(contract_path.read_text())
    result = {"schema": "hepta.cargo_deny.new_measurement.v2", "status": "STARTING",
              "subject_head": c["subject_head"], "ci_head": a.head, "unit": a.unit,
              "contract_sha256": digest(contract_path), "phases": [],
              "old_ci_equivalence_claimed": False, "restricted_old_logs_accessed": 0,
              "model_evaluations": 0, "policy_edits": 0, "compile_commands": 0,
              "metadata_invocations": 0, "policy_check_invocations": 0,
              "metadata_attempts": 0, "policy_check_attempts": 0,
              "network_bytes_total": None, "whole_job_cpu_seconds": None,
              "wall_admissions": [], "checkout_identity": None,
              "log_capture": "bounded pipes; independent 4GiB regular-file kernel limit"}
    cg = None
    env = {}
    inputs_before = None
    check_code = None
    used_commands = 0
    deadline = None
    runner_owner = None
    checkout_verified = False
    def require_wall(label, minimum=0, record=False):
        if deadline is None:
            raise RuntimeError("ABSOLUTE_DEADLINE_NOT_INSTALLED")
        now = time.monotonic()
        remaining = deadline - now
        if record:
            result["wall_admissions"].append({"label": label,
                "monotonic_seconds": now, "absolute_deadline": deadline,
                "remaining_seconds": remaining, "required_seconds": minimum})
        if remaining < minimum or remaining <= 0:
            raise RuntimeError("INSUFFICIENT_WALL_" + label)
        return remaining
    def cpu():
        if cg is None:
            return None
        rows = dict(line.split() for line in (cg / "cpu.stat").read_text().splitlines())
        return int(rows["usage_usec"]) / 1000000
    def run(name, argv, cwd=None, stdout_cap=524288, stderr_cap=524288,
            allowed=(0,), as_owner=None):
        nonlocal used_commands
        if used_commands >= 30:
            raise RuntimeError("COMMAND_COUNT_LIMIT")
        used_commands += 1
        fo, fe = out / (name + ".stdout"), out / (name + ".stderr")
        begin, before = time.monotonic(), cpu()
        phase = {"name": name, "argv": [str(x) for x in argv], "started": False,
                 "returncode": None, "wall_seconds": None,
                 "cgroup_cpu_delta_seconds": None,
                 "stdout_cap": stdout_cap, "stderr_cap": stderr_cap,
                 "run_as_uid": 0 if as_owner is None else as_owner[0],
                 "input_single_file_kernel_cap": INPUT_FILE_CAP,
                 "output_truncated": False, "stop_reason": None}
        result["phases"].append(phase)
        def limits():
            resource.setrlimit(resource.RLIMIT_FSIZE, (INPUT_FILE_CAP, INPUT_FILE_CAP))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            if as_owner is not None:
                os.setgroups([])
                os.setgid(as_owner[1])
                os.setuid(as_owner[0])
        p = None
        killed = False
        code = None
        try:
            with fo.open("xb") as so, fe.open("xb") as se, selectors.DefaultSelector() as sel:
                require_wall("policy-launch" if name == "policy-check" else "launch-" + name,
                             minimum=120 if name == "policy-check" else 0,
                             record=name == "policy-check")
                p = subprocess.Popen(argv, cwd=cwd or work, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     stdin=subprocess.DEVNULL, start_new_session=True,
                                     preexec_fn=limits)
                phase.update({"started": True, "pid": p.pid})
                for pipe, target, cap in ((p.stdout, so, stdout_cap), (p.stderr, se, stderr_cap)):
                    os.set_blocking(pipe.fileno(), False)
                    sel.register(pipe, selectors.EVENT_READ, [target, cap, 0])
                while sel.get_map() or p.poll() is None:
                    require_wall("capture-" + name)
                    for key, _ in sel.select(timeout=0.1):
                        block = os.read(key.fileobj.fileno(), 65536)
                        if not block:
                            sel.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        target, cap, written = key.data
                        left = cap - written
                        target.write(block[:left])
                        key.data[2] += min(left, len(block))
                        if len(block) > left:
                            phase["output_truncated"] = True
                            phase["stop_reason"] = "STREAM_OUTPUT_LIMIT"
                            raise RuntimeError("STREAM_OUTPUT_LIMIT_" + name)
                code = p.wait(timeout=min(5, require_wall("reap-" + name)))
            phase.update({"returncode": code,
                          "stdout": fo.name, "stdout_sha256": digest(fo),
                          "stderr": fe.name, "stderr_sha256": digest(fe)})
        except BaseException as e:
            phase["error"] = type(e).__name__ + ": " + str(e)
            if p is not None:
                killed = True
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    code = p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    phase["reaped"] = False
                for pipe in (p.stdout, p.stderr):
                    if pipe is not None:
                        pipe.close()
            raise
        finally:
            phase["returncode"] = code
            phase["killed"] = killed
            phase.setdefault("reaped", code is not None)
            for path, label in ((fo, "stdout"), (fe, "stderr")):
                if path.exists():
                    phase[label + "_bytes"] = path.stat().st_size
                    phase[label + "_sha256"] = digest(path)
            phase["wall_seconds"] = time.monotonic()-begin
            phase["cgroup_cpu_delta_seconds"] = None if before is None else cpu()-before
        if killed or code not in allowed:
            raise RuntimeError("PHASE_FAILED_" + name)
        return code, fo, fe
    def git(name, args, cwd=repo):
        argv = ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper="]
        as_owner = None
        if cwd == repo:
            if checkout_verified:
                argv += ["-c", "safe.directory=" + str(repo)]
            else:
                as_owner = runner_owner
                if as_owner is None:
                    raise RuntimeError("CHECKOUT_OWNER_NOT_VERIFIED")
        elif not Path(cwd).resolve(strict=True).is_relative_to(work):
            raise RuntimeError("GIT_CWD_OUTSIDE_DECLARED_SCOPES")
        return run(name, argv + args, cwd=cwd, as_owner=as_owner)
    def snapshot():
        scopes = {"registry": work/"cargo/registry", "git": work/"cargo/git",
                  "advisory-dbs": work/"cargo/advisory-dbs",
                  "toolchain": work/"rustup/toolchains"}
        whole = hashlib.sha256()
        totals = {"records": 0, "file_bytes": 0, "canonical_bytes": 0, "discovered": 0}
        summary = {"schema": "hepta.cargo_deny.input_closure.v2",
                   "canonicalization": "UTF-8 JSON, ensure_ascii=false, sort_keys=true, separators=(',',':'), newline; scopes and sibling names sorted by UTF-8 bytes; depth-first preorder traversal",
                   "full_record_listing_saved": False, "excluded_paths": [], "scopes": {}}
        for label, base in sorted(scopes.items()):
            if not base.is_dir() or base.is_symlink():
                raise RuntimeError("INPUT_SCOPE_MISSING_" + label)
            sh = hashlib.sha256()
            counts = {"records": 0, "file_bytes": 0, "canonical_bytes": 0}
            def walk(directory):
                require_wall("input-scan")
                entries = []
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        totals["discovered"] += 1
                        if totals["discovered"] > INPUT_COUNT_CAP:
                            raise RuntimeError("INPUT_RECORD_COUNT_LIMIT")
                        name_bytes = entry.name.encode("utf-8", errors="strict")
                        entries.append((name_bytes, Path(entry.path)))
                for _, path in sorted(entries):
                    require_wall("input-record")
                    rel = label + "/" + str(path.relative_to(base))
                    if len(rel.encode("utf-8", errors="strict")) > PATH_BYTES_CAP:
                        raise RuntimeError("INPUT_PATH_LENGTH_LIMIT")
                    before = path.lstat()
                    record = {"path": rel, "mode": stat.S_IMODE(before.st_mode)}
                    n = 0
                    if stat.S_ISLNK(before.st_mode):
                        target = path.resolve(strict=True)
                        if not any(target.is_relative_to(scope) for scope in scopes.values()):
                            raise RuntimeError("INPUT_SYMLINK_OUTSIDE_HASHED_SCOPES")
                        link = os.readlink(path)
                        if len(link.encode("utf-8", errors="strict")) > PATH_BYTES_CAP:
                            raise RuntimeError("INPUT_SYMLINK_LENGTH_LIMIT")
                        record.update({"kind": "symlink", "target": link})
                    elif stat.S_ISREG(before.st_mode):
                        n = before.st_size
                        if n > INPUT_FILE_CAP or totals["file_bytes"] + n > INPUT_TOTAL_CAP:
                            raise RuntimeError("INPUT_FILE_OR_TOTAL_BYTES_LIMIT")
                        record.update({"kind": "file", "bytes": n,
                                       "sha256": digest(path, deadline)})
                        after = path.lstat()
                        if (before.st_ino, before.st_size, before.st_mode, before.st_mtime_ns,
                            before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mode,
                                                   after.st_mtime_ns, after.st_ctime_ns):
                            raise RuntimeError("INPUT_CHANGED_DURING_HASH")
                    elif stat.S_ISDIR(before.st_mode):
                        record["kind"] = "directory"
                    else:
                        raise RuntimeError("INPUT_SPECIAL_FILE")
                    raw = (json.dumps(record, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")) + "\n").encode("utf-8")
                    if len(raw) > RECORD_BYTES_CAP:
                        raise RuntimeError("INPUT_RECORD_SIZE_LIMIT")
                    whole.update(raw)
                    sh.update(raw)
                    for counter in (totals, counts):
                        counter["records"] += 1
                        counter["file_bytes"] += n
                        counter["canonical_bytes"] += len(raw)
                    if record["kind"] == "directory":
                        walk(path)
            walk(base)
            summary["scopes"][label] = {**counts, "sha256": sh.hexdigest()}
        summary.update({key: totals[key] for key in ("records", "file_bytes", "canonical_bytes")})
        summary["sha256"] = whole.hexdigest()
        result["input_closure_bytes"] = totals["file_bytes"]
        return summary
    try:
        if c.get("status") != "ROOT_FROZEN_ADMITTED_ONCE":
            raise RuntimeError("CONTRACT_NOT_FROZEN")
        if sys.version_info[:2] != (3, 12):
            raise RuntimeError("PYTHON312_REQUIRED")
        for _ in range(200):
            if (root/"RESOURCE_ADMITTED.json").exists():
                break
            time.sleep(0.05)
        gate = json.loads((root/"RESOURCE_ADMITTED.json").read_text())
        result["resource_admission_sha256"] = digest(root/"RESOURCE_ADMITTED.json")
        if gate["unit"] != a.unit:
            raise RuntimeError("RESOURCE_GATE_IDENTITY")
        deadline = float(gate["worker_absolute_deadline_monotonic"])
        result["absolute_deadlines"] = gate["absolute_deadlines"]
        result["worker_absolute_deadline_monotonic"] = deadline
        require_wall("resource-gate", record=True)
        identity = gate["checkout_owner_precondition"]
        if (str(repo) != identity["workspace"]
            or repo != Path("/home/runner/work/hepta-private-ci/hepta-private-ci")
            or repo.is_symlink() or (repo/".git").is_symlink()
            or not (repo/".git").is_dir()
            or repo.stat().st_uid != identity["uid"]
            or (repo/".git").stat().st_uid != identity["uid"]
            or identity["uid"] <= 0):
            raise RuntimeError("CHECKOUT_OWNER_OR_LOCATION_CHANGED")
        runner_owner = (identity["uid"], identity["gid"])
        resource.setrlimit(resource.RLIMIT_FSIZE, (INPUT_FILE_CAP, INPUT_FILE_CAP))
        cg = Path(gate["cgroup"])
        if (cg/"cpu.max").read_text().split() != ["25000", "100000"]:
            raise RuntimeError("RESOURCE_GATE_CPU_QUOTA")
        cargo_home, rustup_home = work/"cargo", work/"rustup"
        cargo_home.mkdir()
        rustup_home.mkdir()
        env = {"PATH": "/usr/bin:/bin:/home/runner/.cargo/bin",
               "CARGO_HOME": str(cargo_home), "RUSTUP_HOME": str(rustup_home),
               "RUSTUP_TOOLCHAIN": c["rust_toolchain"],
               "RUSTUP_DIST_SERVER": "https://static.rust-lang.org",
               "RUSTUP_NO_UPDATE_CHECK": "1", "CARGO_NET_GIT_FETCH_WITH_CLI": "false",
               "CARGO_REGISTRIES_CRATES_IO_PROTOCOL": "sparse",
               "CARGO_HTTP_TIMEOUT": "60", "CARGO_NET_RETRY": "0",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never",
               "GIT_SSH_COMMAND": "/bin/false", "SSH_ASKPASS": "/bin/false",
               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "RAYON_NUM_THREADS": "1",
               "CARGO_BUILD_JOBS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        for rel, expected in c["publication_file_pins"].items():
            if (repo/rel).resolve(strict=True) != repo/rel:
                raise RuntimeError("PUBLICATION_PATH_SYMLINK")
            if digest(repo/rel) != expected:
                raise RuntimeError("PUBLICATION_INPUT_CHANGED")
        for rel, expected in c["policy_file_pins"].items():
            if digest(repo/rel) != expected:
                raise RuntimeError("POLICY_INPUT_CHANGED")
        _, head, _ = git("head", ["rev-parse", "HEAD"])
        _, parent, _ = git("parent", ["rev-parse", "HEAD^"])
        _, parent_tree, _ = git("parent-tree", ["rev-parse", "HEAD^1^{tree}"])
        if head.read_text().strip() != a.head or parent.read_text().strip() != c["subject_head"]:
            raise RuntimeError("SOURCE_ANCESTRY_MISMATCH")
        if parent_tree.read_text().strip() != c["subject_tree"]:
            raise RuntimeError("SUBJECT_TREE_MISMATCH")
        _, dirty, _ = git("initial-status", ["status", "--porcelain", "--untracked-files=all"])
        if dirty.read_bytes():
            raise RuntimeError("INITIAL_WORKTREE_DIRTY")
        _, changed, _ = git("instrumentation-diff", ["diff", "--name-status", "--no-renames", "HEAD^", "HEAD"])
        if set(changed.read_text().splitlines()) != {"A\t" + p for p in c["allowed_added_paths"]}:
            raise RuntimeError("INSTRUMENTATION_SCOPE_MISMATCH")
        checkout_verified = True
        result["checkout_identity"] = {"workspace": str(repo), "runner_owner": identity,
            "head": a.head, "parent": c["subject_head"], "parent_tree": c["subject_tree"],
            "initial_checks_as_owner_uid": runner_owner[0], "clean": True,
            "diagnostic_only_additions": True,
            "subsequent_root_git_safe_directory": str(repo),
            "global_git_config_changed": False}
        for ancestor in repo.parents:
            if any((ancestor/".cargo"/x).exists() for x in ("config", "config.toml")):
                raise RuntimeError("EXTERNAL_ANCESTOR_CARGO_CONFIG")
        rustup = Path("/home/runner/.cargo/bin/rustup").resolve(strict=True)
        result["runner_tool_fingerprints_before"] = {
            "python": digest("/usr/bin/python3"), "git": digest("/usr/bin/git"),
            "unshare": digest("/usr/bin/unshare"),
            "rustup": digest(rustup)}
        run("rust-toolchain", [str(rustup), "toolchain", "install", c["rust_toolchain"],
                               "--profile", "minimal", "--no-self-update"])
        tc = work/"rustup/toolchains"/c["rust_toolchain"]
        cargo, rustc = tc/"bin/cargo", tc/"bin/rustc"
        env["PATH"] = str(tc/"bin") + ":/usr/bin:/bin"
        env["RUSTC"] = str(rustc)
        _, cargo_version, _ = run("cargo-version", [str(cargo), "--version", "--verbose"])
        _, rustc_version, _ = run("rustc-version", [str(rustc), "--version", "--verbose"])
        for key, path in (("cargo", cargo_version), ("rustc", rustc_version)):
            v = path.read_text()
            if c[key+"_commit"] not in v or ("release: 1.95.0" not in v):
                raise RuntimeError("TOOLCHAIN_VERSION_IDENTITY_" + key)
        archive = work/"cargo-deny.tar.gz"
        begin, before = time.monotonic(), cpu()
        with urllib.request.urlopen(c["cargo_deny_asset"]["url"], timeout=30) as r:
            host = urllib.parse.urlsplit(r.url).hostname
            if host not in ("github.com", "release-assets.githubusercontent.com",
                            "objects.githubusercontent.com"):
                raise RuntimeError("TOOL_DOWNLOAD_REDIRECT_HOST")
            with archive.open("xb") as f:
                total = 0
                while block := r.read(1048576):
                    require_wall("tool-archive-read")
                    total += len(block)
                    if total > c["cargo_deny_asset"]["bytes"]:
                        raise RuntimeError("TOOL_ARCHIVE_SIZE")
                    f.write(block)
        if archive.stat().st_size != c["cargo_deny_asset"]["bytes"]:
            raise RuntimeError("TOOL_ARCHIVE_LENGTH")
        if digest(archive) != c["cargo_deny_asset"]["sha256"]:
            raise RuntimeError("TOOL_ARCHIVE_CHECKSUM")
        tools = work/"tools"
        tools.mkdir()
        with tarfile.open(archive) as tf:
            tf.extractall(tools, filter="data")
        bins = [p for p in tools.rglob("cargo-deny") if p.is_file()]
        if len(bins) != 1:
            raise RuntimeError("TOOL_BINARY_CARDINALITY")
        deny = bins[0]
        result["phases"].append({"name": "cargo-deny-download-extract",
                                  "wall_seconds": time.monotonic()-begin,
                                  "cgroup_cpu_delta_seconds": cpu()-before,
                                  "downloaded_bytes": total, "binary_sha256": digest(deny)})
        _, ver, _ = run("deny-version", [str(deny), "--version"])
        if ver.read_text().strip() != "cargo-deny 0.19.0":
            raise RuntimeError("CARGO_DENY_VERSION")
        manifest = repo/"codex-rs/Cargo.toml"
        run("advisory-acquire", [str(deny), "--manifest-path", str(manifest),
                                 "--locked", "fetch", "db"], cwd=repo/"codex-rs")
        dbs = [p for p in (cargo_home/"advisory-dbs").iterdir()
               if p.is_dir() and (p/".git").exists()]
        if len(dbs) != 1:
            raise RuntimeError("ADVISORY_DB_CARDINALITY")
        db = dbs[0]
        git("advisory-detach", ["checkout", "--detach", c["advisory_commit"]], cwd=db)
        _, db_head, _ = git("advisory-head", ["rev-parse", "HEAD"], cwd=db)
        _, db_tree, _ = git("advisory-tree", ["rev-parse", "HEAD^{tree}"], cwd=db)
        if db_head.read_text().strip() != c["advisory_commit"]:
            raise RuntimeError("ADVISORY_COMMIT_MISMATCH")
        if db_tree.read_text().strip() != c["advisory_tree"]:
            raise RuntimeError("ADVISORY_TREE_MISMATCH")
        run("dependency-acquire", [str(cargo), "fetch", "--locked",
                                   "--manifest-path", str(manifest)], cwd=repo/"codex-rs")
        result["metadata_attempts"] += 1
        result["metadata_invocations"] = None
        _, metadata, _ = run("metadata", ["/usr/bin/unshare", "--net", "--", str(cargo),
                                         "metadata", "--locked", "--offline", "--all-features",
                                         "--format-version", "1", "--manifest-path", str(manifest)],
                              cwd=repo/"codex-rs", stdout_cap=METADATA_CAP)
        md = json.loads(metadata.read_text())
        if not isinstance(md.get("resolve"), dict):
            raise RuntimeError("METADATA_RESOLVE_MISSING")
        if not isinstance(md.get("packages"), list) or not 1 <= len(md["packages"]) <= 1517:
            raise RuntimeError("METADATA_PACKAGE_COUNT_LIMIT")
        result["metadata_invocations"] = 1
        lock = tomllib.loads((repo/"codex-rs/Cargo.lock").read_text())
        if len(lock["package"]) != 1517:
            raise RuntimeError("LOCK_PACKAGE_COUNT_CHANGED")
        expected = {(p["name"], p["version"], p.get("source")): p for p in lock["package"]}
        allowed_git = set(c["locked_git_sources"])
        for p in md["packages"]:
            require_wall("package-verification")
            source = p.get("source")
            if source and source.startswith("registry+"):
                item = expected.get((p["name"], p["version"], source))
                if not item or "checksum" not in item:
                    raise RuntimeError("REGISTRY_IDENTITY_NOT_LOCKED")
                matches = list((cargo_home/"registry/cache").glob(
                    "*/" + p["name"] + "-" + p["version"] + ".crate"))
                if len(matches) != 1 or digest(matches[0], deadline) != item["checksum"]:
                    raise RuntimeError("REGISTRY_ARCHIVE_CHECKSUM")
            elif source and source.startswith("git+"):
                if source not in allowed_git:
                    raise RuntimeError("GIT_SOURCE_NOT_LOCKED")
            elif source:
                raise RuntimeError("UNEXPECTED_PACKAGE_SOURCE")
            elif not Path(p["manifest_path"]).resolve(strict=True).is_relative_to(repo):
                raise RuntimeError("UNPINNED_PATH_PACKAGE")
        result["resolved_package_count"] = len(md["packages"])
        require_wall("before-input-snapshot", minimum=120, record=True)
        begin, before = time.monotonic(), cpu()
        inputs_before = snapshot()
        result["phases"].append({"name": "input-snapshot-before",
            "wall_seconds": time.monotonic()-begin, "cgroup_cpu_delta_seconds": cpu()-before})
        emit(out/"INPUT_CLOSURE_BEFORE.json", inputs_before)
        require_wall("after-input-snapshot", minimum=120, record=True)
        freeze = {"schema": "hepta.cargo_deny.new_measurement.inputs.v1",
                  "subject_head": c["subject_head"], "ci_head": a.head,
                  "contract_sha256": result["contract_sha256"],
                  "metadata_sha256": digest(metadata),
                  "input_closure_sha256": digest(out/"INPUT_CLOSURE_BEFORE.json"),
                  "canonical_input_records_sha256": inputs_before["sha256"],
                  "advisory_commit": c["advisory_commit"], "advisory_tree": c["advisory_tree"],
                  "cargo_sha256": digest(cargo), "rustc_sha256": digest(rustc),
                  "cargo_deny_sha256": digest(deny), "new_snapshot": True,
                  "old_ci_equivalence_claimed": False}
        emit(out/"INPUTS_FROZEN.json", freeze)
        result["policy_check_attempts"] += 1
        result["policy_check_invocations"] = None
        check_code, check_stdout, check_stderr = run("policy-check",
            ["/usr/bin/unshare", "--net", "--", str(deny), "--format", "json",
             "--color", "never", "--manifest-path", str(manifest), "--all-features",
             "--locked", "--offline", "check", "--disable-fetch",
             "--metadata-path", str(metadata)], cwd=repo/"codex-rs",
            stdout_cap=2097152, stderr_cap=2097152, allowed=(0, 1))
        diagnostics = []
        for line in check_stderr.read_text().splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                diagnostics.append(value)
        if check_code == 1 and not diagnostics:
            raise RuntimeError("CHECK_FAILURE_WITHOUT_STRUCTURED_DIAGNOSTIC")
        result["policy_check_invocations"] = 1
        result["diagnostic_json_records"] = len(diagnostics)
        begin, before = time.monotonic(), cpu()
        after = snapshot()
        result["phases"].append({"name": "input-snapshot-after",
            "wall_seconds": time.monotonic()-begin, "cgroup_cpu_delta_seconds": cpu()-before})
        emit(out/"INPUT_CLOSURE_AFTER.json", after)
        if after != inputs_before:
            raise RuntimeError("FROZEN_INPUTS_CHANGED")
        if any(digest(path) != freeze[key] for path, key in (
                (metadata, "metadata_sha256"), (cargo, "cargo_sha256"),
                (rustc, "rustc_sha256"), (deny, "cargo_deny_sha256"))):
            raise RuntimeError("FROZEN_EXECUTABLE_OR_METADATA_CHANGED")
        current_tools = {"python": digest("/usr/bin/python3"),
                         "git": digest("/usr/bin/git"), "unshare": digest("/usr/bin/unshare"),
                         "rustup": digest(rustup)}
        if current_tools != result["runner_tool_fingerprints_before"]:
            raise RuntimeError("RUNNER_TOOL_CHANGED")
        for rel, expected_hash in c["policy_file_pins"].items():
            if digest(repo/rel) != expected_hash:
                raise RuntimeError("POLICY_CHANGED")
        _, dirty, _ = git("final-status", ["status", "--porcelain", "--untracked-files=all"])
        if dirty.read_bytes():
            raise RuntimeError("FINAL_WORKTREE_DIRTY")
        result["frozen_inputs_unchanged"] = True
        result["policy_check_returncode"] = check_code
        result["status"] = ("CHECK_PASSED_NEW_MEASUREMENT_ONLY" if check_code == 0
                            else "CHECK_FAILED_NEW_DIAGNOSTIC")
    except BaseException as e:
        result["status"] = "STOP"
        result["error"] = type(e).__name__ + ": " + str(e)
        result["frozen_inputs_unchanged"] = None
    finally:
        begin, before = time.monotonic(), cpu()
        try:
            require_wall("cleanup-start", record=True)
            shutil.rmtree(work)
            result["cleanup"] = "RESEARCH_WORK_REMOVED"
        except BaseException as e:
            result["cleanup"] = "INCOMPLETE"
            result["cleanup_error"] = type(e).__name__ + ": " + str(e)
            result["status"] = "STOP"
        result["phases"].append({"name": "cleanup",
                                  "wall_seconds": time.monotonic()-begin,
                                  "cgroup_cpu_delta_seconds": None if before is None else cpu()-before})
        result["command_count"] = used_commands
        result["output_bytes_before_worker_receipt"] = sum(
            x.stat().st_size for x in out.iterdir() if x.is_file())
        if result["output_bytes_before_worker_receipt"] > OUTPUT_CAP-RECEIPT_CAP:
            result["status"] = "STOP"
            result["output_acceptance_error"] = "OUTPUT_TOTAL_LIMIT"
        if deadline is None or time.monotonic() >= deadline:
            result["status"] = "STOP"
            result["deadline_error"] = "ABSOLUTE_DEADLINE_NOT_MET"
        result["cgroup_cpu_seconds_through_worker_receipt"] = cpu()
        result["whole_job_cost_complete"] = False
        emit(out/"RESULT.json", result)
    return 0 if result["status"] == "CHECK_PASSED_NEW_MEASUREMENT_ONLY" else 1

if __name__ == "__main__":
    sys.exit(main())

