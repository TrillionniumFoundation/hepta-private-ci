#!/usr/bin/env python3
"""Reviewable, source-bound three-package native and exact Root7 driver.

Preparation of this file does not execute qualification. Running it requires a
new output directory, a new Cargo target directory, and a clean exclusive checkout.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET


PACKAGES = (
    "codex-hepta-agentd",
    "codex-hepta-learning-artifacts",
    "codex-hepta-intelligence-eval",
)
ROOT_PARENTS = (
    "authority_host_service::writer::learning_registration::tests::root_learning_registration_reopens_without_replacing_original_history",
    "authority_host_service::writer::learning_registration::tests::root_learning_sealed_pin_and_dedicated_uds_recover_original_checkpoint",
    "authority_host_service::writer::learning_registration::tests::root_scoped_learning_reopens_exact_scope_and_refuses_legacy_client",
    "authority_host_service::writer::learning_registration::tests::root_learning_scoped_sealed_pin_preserves_scope_on_cold_reopen",
    "root_production_handoff::learning::tests::root_learning_handoff_reaches_dedicated_uid_with_original_root_pin",
    "authority_host_learning_service_root_tests::root_learning_public_registration_serves_retained_writer_and_recovers_history",
    "learning_iteration_evidence_client::tests::root::original_external_uid_returns_a_verified_receipt_through_held_pidfd",
)
REFERENCE_SOURCE = "c7633658aef42077f51fa71a1b727b4653ddb76b"
REVIEWED_TOOLS = {
    "scripts/hepta_ci_exec.py": "c9434b3a4afb31f80e323d543936386a2fa738de",
    "scripts/hepta_ci_junit.py": "683626df091bdfe160a8965fdc92bf40f5783cf8",
    "scripts/hepta_cell_test_helpers.py": "f5b702a55b44c081c6d8f5556da3a2152a33eec3",
    "scripts/hepta_ci_v8.py": "088b737c0cca7386161e06b254c794bf972380ad",
    "scripts/run-nextest.py": "1ed63abe84267b320cbfb0123a70aac5507f4595",
    "codex-rs/.config/nextest.toml": "0904c42a41594d3ae4dc6f196e64f35f0b85bd2c",
}
ENV_KEYS = (
    "PATH", "CARGO_HOME", "RUSTUP_HOME", "RUSTUP_TOOLCHAIN", "LIBCLANG_PATH",
    "BINDGEN_EXTRA_CLANG_ARGS", "CARGO_TARGET_DIR", "CARGO_INCREMENTAL",
    "CARGO_BUILD_JOBS", "CARGO_PROFILE_TEST_DEBUG", "CARGO_PROFILE_DEV_DEBUG",
    "CARGO_NET_OFFLINE", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTDOCFLAGS",
    "CC", "CXX", "AR", "CMAKE", "CMAKE_PREFIX_PATH", "PKG_CONFIG_PATH",
    "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "TMPDIR",
    "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "RUST_MIN_STACK",
    "SOURCE_SHA", "TESTED_SHA", "HEPTA_CI_LANE", "CODEX_REPO_ROOT",
    "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB",
    "RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH",
)
ROOT_SETUP = """
import json, os, stat, subprocess, sys
from pathlib import Path
assert os.geteuid() == 0
p = Path(sys.argv[1])
assert p.parent == Path('/run') and p.name.startswith('hepta-daemon-learning-')
p.mkdir(mode=0o700)
for name in ('source', 'bind', 'checkpoints'):
    (p / name).mkdir(mode=0o700)
assert p.stat().st_uid == 0 and stat.S_IMODE(p.stat().st_mode) == 0o700
subprocess.run(['mount', '--bind', str(p / 'source'), str(p / 'bind')], check=True)
print(json.dumps({'uid': os.geteuid(), 'fixture': str(p), 'bound': True}), flush=True)
"""
ROOT_UNMOUNT = """
import json, os, subprocess, sys
from pathlib import Path
assert os.geteuid() == 0
p = Path(sys.argv[1])
assert p.parent == Path('/run') and p.name.startswith('hepta-daemon-learning-')
assert not p.is_symlink()
mounted = False
if p.exists():
    assert p.stat().st_uid == 0 and not (p / 'bind').is_symlink()
    code = subprocess.run(['mountpoint', '-q', str(p / 'bind')]).returncode
    assert code in (0, 1)
    mounted = code == 0
    if mounted:
        subprocess.run(['umount', str(p / 'bind')], check=True)
print(json.dumps({'fixture': str(p), 'unmounted': mounted, 'files_retained': True}), flush=True)
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class NativeDriver:
    def __init__(self, args):
        self.args = args
        self.repo = args.repo.resolve(strict=True)
        self.output = args.output.resolve()
        self.target = args.target.resolve()
        paths = (self.repo, self.output, self.target)
        if any(a == b or a.is_relative_to(b) for a in paths for b in paths if a is not b):
            raise ValueError("repo, output and target must be disjoint directories")
        if self.output.exists() or self.target.exists():
            raise ValueError("output and target must both be new; never resume or reuse binaries")
        if re.fullmatch(r"[0-9a-f]{40}", args.source_sha) is None:
            raise ValueError("source_sha must be an exact lowercase 40-character Git SHA")
        self.output.mkdir(parents=True)
        self.target.mkdir(parents=True)
        (self.output / "tmp").mkdir()
        self.started = time.monotonic()
        self.steps = []
        self.errors = []
        self.initial = None
        self.native_passed = False
        self.ordinary_passed = False
        self.root_passed = False
        self.root_available = False
        self.root_unavailable_reason = None
        self.root_attempted = False
        self.maintenance_started = False
        self.maintenance_complete = False
        self.root_dir = Path("/run") / ("hepta-daemon-learning-" + uuid.uuid4().hex)
        self.junit = self.repo / "codex-rs/target/nextest/local/junit.xml"
        self.package_args = [value for package in PACKAGES for value in ("-p", package)]
        self.helper = ["python3", "scripts/hepta_cell_test_helpers.py", "--package",
                       "codex-hepta-infer-worker-host", "--output-dir", str(self.output / "helpers")]
        self.save("invocation.json", {
            "argv": sys.argv, "started_at": utc_now(), "status": "prepared-not-complete",
            "repo": str(self.repo), "output": str(self.output), "target": str(self.target),
            "source_sha": args.source_sha, "reference_source": REFERENCE_SOURCE,
            "driver_sha256": file_digest(Path(__file__).resolve()),
            "uid": os.getuid(), "euid": os.geteuid(), "host": os.uname().nodename,
            "root_fixture": str(self.root_dir), "maintenance_requested": args.maintenance,
        })

    def save(self, name, value):
        with (self.output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

    def git(self, *args, raw=False):
        result = subprocess.check_output(["git", "--no-optional-locks", *args], cwd=self.repo)
        return result if raw else result.decode().strip()

    def identity(self):
        return {"commit": self.git("rev-parse", "HEAD"),
                "tree": self.git("rev-parse", "HEAD^{tree}"),
                "status": self.git("status", "--porcelain=v1", "--untracked-files=all")}

    def snapshot(self, label):
        started = time.monotonic()
        before = self.identity()
        names = self.git("ls-files", "-z", raw=True)
        names += self.git("ls-files", "--others", "--exclude-standard", "-z", raw=True)
        rows = []
        for raw in sorted(set(names.split(b"\0")) - {b""}):
            name = os.fsdecode(raw)
            path = self.repo / name
            if not path.exists() and not path.is_symlink():
                rows.append({"path": name, "missing": True})
                continue
            initial = path.lstat()
            if stat.S_ISLNK(initial.st_mode):
                data = os.fsencode(os.readlink(path))
                size, mode = len(data), "120000"
                sha256 = hashlib.sha256(data)
                blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0" + data)
            elif stat.S_ISREG(initial.st_mode):
                size = initial.st_size
                mode = "100755" if initial.st_mode & 0o111 else "100644"
                sha256 = hashlib.sha256()
                blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        sha256.update(block)
                        blob.update(block)
            else:
                raise RuntimeError("unsupported source file kind: " + name)
            after = path.lstat()
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
            if any(getattr(initial, field) != getattr(after, field) for field in fields):
                raise RuntimeError("source changed while hashing: " + name)
            rows.append({"path": name, "mode": mode, "bytes": size,
                         "sha256": sha256.hexdigest(), "blob": blob.hexdigest()})
        if before != self.identity():
            raise RuntimeError("Git identity changed while taking source inventory")
        encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        with (self.output / (label + ".files.json.gz")).open("xb") as stream:
            stream.write(gzip.compress(encoded, mtime=0))
        result = {**before, "files": len(rows), "inventory_sha256": hashlib.sha256(encoded).hexdigest()}
        self.save(label + ".json", {**result, "elapsed_seconds": time.monotonic() - started})
        print(json.dumps({"source_snapshot": label, **result}), flush=True)
        return result

    def prepare(self):
        if sys.platform != "linux" or os.getuid() != os.geteuid() or os.geteuid() == 0:
            raise RuntimeError("ordinary native suite requires a normal Linux user")
        if self.git("rev-parse", "--show-toplevel") != str(self.repo):
            raise RuntimeError("repo must identify the checkout root")
        lock_path = Path(self.git("rev-parse", "--git-path", "hepta-native-driver.lock"))
        if not lock_path.is_absolute():
            lock_path = self.repo / lock_path
        self.lock = lock_path.open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.initial = self.snapshot("checkout")
        if self.initial["commit"] != self.args.source_sha or self.initial["status"]:
            raise RuntimeError("checkout must be clean and HEAD must equal source_sha")
        observed = {path: self.git("rev-parse", "HEAD:" + path) for path in REVIEWED_TOOLS}
        self.save("reviewed-tools.json", {"expected": REVIEWED_TOOLS, "observed": observed})
        if observed != REVIEWED_TOOLS:
            raise RuntimeError("recorder/helper/nextest contracts changed; review driver before executing")
        if self.args.maintenance:
            if not self.args.format_base_sha:
                raise RuntimeError("maintenance requires an explicit format-base-sha")
            if re.fullmatch(r"[0-9a-f]{40}", self.args.format_base_sha) is None:
                raise RuntimeError("format-base-sha must be a fixed complete commit SHA")
            subprocess.run(["git", "merge-base", "--is-ancestor", self.args.format_base_sha, "HEAD"],
                           cwd=self.repo, check=True)
        removed = [key for key in os.environ if key.startswith(("CARGO_BIN_EXE_", "NEXTEST_"))]
        removed += [key for key in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER") if key in os.environ]
        for key in removed:
            os.environ.pop(key)
        settings = {
            "SOURCE_SHA": self.args.source_sha, "TESTED_SHA": self.args.source_sha,
            "HEPTA_CI_LANE": "source-head", "CODEX_REPO_ROOT": str(self.repo),
            "CARGO_TARGET_DIR": str(self.target), "CARGO_INCREMENTAL": "0",
            "CARGO_BUILD_JOBS": str(self.args.cargo_build_jobs), "CARGO_NET_OFFLINE": "true",
            "CARGO_HOME": os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")),
            "CARGO_PROFILE_TEST_DEBUG": "0", "CARGO_PROFILE_DEV_DEBUG": "0",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(self.repo / "scripts") + ":" + str(self.repo),
            "TMPDIR": str(self.output / "tmp"), "RUST_MIN_STACK": "8388608",
            "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
            "GITHUB_RUN_ID": "local-" + self.root_dir.name.removeprefix("hepta-daemon-learning-"),
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "local-native-driver",
            "GITHUB_ENV": str(self.output / "v8.env"),
        }
        os.environ.update(settings)
        os.chdir(self.repo)
        sys.path.insert(0, str(self.repo / "scripts"))
        from hepta_ci_exec import execute_logged
        from hepta_ci_junit import collect
        self.execute_logged, self.collect = execute_logged, collect
        self.save("environment.json", {"selected": {key: os.environ[key] for key in ENV_KEYS if key in os.environ},
                                       "removed_inherited_variable_names": removed,
                                       "origin": "local-driver-not-GitHub-Actions"})
        required = ("python3", "git", "cargo", "rustc", "just")
        root_required = ("sudo", "mount", "mountpoint", "umount")
        tools = {name: shutil.which(name) for name in (*required, *root_required)}
        self.save("tool-paths.json", tools)
        if any(not tools[name] for name in required):
            raise RuntimeError("missing ordinary executables: " + ", ".join(name for name in required if not tools[name]))
        missing_root = [name for name in root_required if not tools[name]]
        self.root_available = not missing_root
        if missing_root:
            self.root_unavailable_reason = "missing Root executables: " + ", ".join(missing_root)

    def command(self, name, command, *, minimum=0, root=False, timeout=None, checked=True):
        timeout = timeout or self.args.timeout_seconds
        record = self.output / (name + ".json")
        launch = ["python3", "scripts/hepta_ci_exec.py", "--timeout-seconds", str(timeout),
                  "--minimum-tests", str(minimum), "--output", str(record), "--", *command]
        if root:
            environment = {key: os.environ[key] for key in ENV_KEYS if key in os.environ}
            environment.update({
                "CARGO_HOME": os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")),
                "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(Path.home() / ".rustup")),
                "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": str(self.repo),
                "HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT": str(self.root_dir / "bind"),
                "HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE": str(self.root_dir / "source"),
                "HEPTA_CHECKPOINT_TEST_ROOT": str(self.root_dir / "checkpoints"),
            })
            environment.update(json.loads((self.output / "helpers/env.json").read_text()))
            check_uid = "import os,runpy,sys; assert os.geteuid()==0; print('Root test uid=0',flush=True); runpy.run_path(sys.argv.pop(1),run_name='__main__')"
            launch = ["sudo", "-n", "env", "-i", *(key + "=" + value for key, value in sorted(environment.items())),
                      "python3", "-c", check_uid, *launch[1:]]
        started_at, started = utc_now(), time.monotonic()
        self.save(name + "-launch.json", {"command": launch, "working_directory": str(self.repo),
                  "started_at": started_at, "required_euid": 0 if root else os.geteuid()})
        code = None
        try:
            with (self.output / (name + "-driver.log")).open("xb") as log:
                code = subprocess.run(launch, cwd=self.repo, stdout=log, stderr=subprocess.STDOUT).returncode
        finally:
            result = {"stage": name, "command": command, "launcher_exit_code": code,
                      "started_at": started_at, "finished_at": utc_now(),
                      "elapsed_seconds": time.monotonic() - started, "cpu_seconds": None}
            self.save(name + "-launch-result.json", result)
            self.steps.append(result)
            print(json.dumps(result), flush=True)
        if checked and code != 0:
            raise RuntimeError(name + " failed; recorder and raw launcher log retained")
        return code

    def plain(self, name, command, timeout=60, cwd=None):
        started_at, started = utc_now(), time.monotonic()
        os.chdir(cwd or self.repo)
        before = self.identity()
        result = {"returncode": None, "timed_out": False, "output_limit_exceeded": False}
        failure = None
        try:
            result = self.execute_logged(command, self.output / (name + ".log"), timeout_seconds=timeout)
        except Exception as error:
            failure = error
            result["error"] = repr(error)
        finally:
            result.update(stage=name, command=command, started_at=started_at, finished_at=utc_now(),
                          elapsed_seconds=time.monotonic() - started, before=before, after=self.identity(),
                          kind="bounded-command-not-clean-source-test-claim", cpu_seconds=None)
            self.save(name + ".json", result)
            self.steps.append(result)
            os.chdir(self.repo)
        if failure or result["returncode"] != 0 or result["timed_out"] or result["output_limit_exceeded"]:
            raise RuntimeError(name + " failed; command wall time and raw log retained") from failure

    def restore_ownership(self, label):
        paths = [self.target, self.output, self.junit.parents[1]]
        if any(path.is_symlink() for path in paths):
            raise RuntimeError("refusing ownership restoration through a symlink")
        self.plain(label, ["sudo", "-n", "chown", "-R", "-h", f"{os.getuid()}:{os.getgid()}", "--",
                           *(str(path) for path in paths if path.exists())])

    def tests(self, name, arguments, *, root=False):
        if self.junit.is_symlink():
            raise RuntimeError("JUnit path must not be a symlink")
        if self.junit.exists():
            self.junit.rename(self.output / (name + "-prior-junit-excluded.xml"))
        command = ["just", "test", "--locked", "--offline", *arguments, "--retries", "0",
                   "--success-output", "final", "--failure-output", "final"]
        code = None
        try:
            code = self.command(name, command, minimum=7 if root else 1, root=root, checked=False)
        finally:
            if root:
                self.restore_ownership("root-evidence-ownership")
        retained = self.collect(self.output / (name + ".json"), self.junit, self.output / (name + ".xml"))
        coverage_error = None
        if (self.output / (name + ".xml")).exists():
            tree = ET.parse(self.output / (name + ".xml"))
            cases = [{"name": case.get("name"), "classname": case.get("classname"),
                      "time": case.get("time"), "skipped": case.find("skipped") is not None,
                      "failed": case.find("failure") is not None, "error": case.find("error") is not None}
                     for case in tree.iter("testcase")]
            observed = [case["name"] for case in cases if not case["skipped"]]
            if root and (len(observed) != len(set(observed)) or sorted(observed) != sorted(ROOT_PARENTS)):
                coverage_error = "Root JUnit must contain exactly the seven distinct requested parents"
            self.save(name + "-cases.json", {"cases": cases, "expected_root_parents": ROOT_PARENTS if root else None,
                      "observed_executed_names": observed, "coverage_error": coverage_error})
        if code or retained or coverage_error:
            raise RuntimeError(name + " failed; execution, fresh JUnit or collection rejection retained")

    def retain_maintenance(self):
        patch = self.git("diff", "--binary", "HEAD", "--", raw=True)
        with (self.output / "maintenance.patch.gz").open("xb") as stream:
            stream.write(gzip.compress(patch, mtime=0))
        changes = self.git("diff", "--name-only", "--no-renames", "-z", "HEAD", "--", raw=True)
        root = self.output / "maintenance-postimages"
        root.mkdir()
        rows = []
        total_bytes = 0
        for raw in changes.split(b"\0"):
            if not raw:
                continue
            name = os.fsdecode(raw)
            source = self.repo / name
            if not name.endswith(".rs") or not name.startswith(tuple("codex-rs/" + package.removeprefix("codex-") + "/" for package in PACKAGES)):
                raise RuntimeError("maintenance changed a path outside its three Rust owners: " + name)
            if source.is_symlink() or not source.is_file() or source.stat().st_size > 256 * 1024:
                raise RuntimeError("maintenance postimage has an unexpected kind or size: " + name)
            total_bytes += source.stat().st_size
            if len(rows) >= 64 or total_bytes > 1024 * 1024:
                raise RuntimeError("maintenance postimages exceed the reviewed transport bound")
            row = {"path": name, "exists": source.exists(), "symlink": source.is_symlink()}
            if source.is_file() and not source.is_symlink():
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                row.update(bytes=source.stat().st_size, sha256=file_digest(destination))
            rows.append(row)
        if self.git("ls-files", "--others", "--exclude-standard", "-z", raw=True):
            raise RuntimeError("maintenance created unexpected untracked source")
        self.save("maintenance-postimages.json", {"complete": self.maintenance_complete, "files": rows,
                  "patch_sha256": hashlib.sha256(patch).hexdigest(), "behavior_tests_after_maintenance": False})

    def run(self):
        try:
            self.prepare()
            if self.root_available:
                self.root_available = self.command("sudo-preflight", ["sudo", "-n", "true"], timeout=60, checked=False) == 0
                if not self.root_available:
                    self.root_unavailable_reason = "sudo -n preflight did not succeed"
            self.save("root-availability.json", {"available": self.root_available, "reason": self.root_unavailable_reason})
            for name, command in (("rustc-version", ["rustc", "-vV"]), ("cargo-version", ["cargo", "--version"]),
                                  ("just-version", ["just", "--version"]), ("nextest-version", ["cargo", "nextest", "--version"])):
                self.command(name, command, timeout=60)
            self.command("v8-resolution", ["python3", "scripts/hepta_ci_v8.py"], timeout=600)
            v8 = {}
            path = self.output / "v8.env"
            for line in path.read_text().splitlines() if path.exists() else []:
                key, value = line.split("=", 1)
                if key not in ("RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH") or key in v8 or not value:
                    raise RuntimeError("unexpected V8 resolver export")
                v8[key] = value
            if v8 and len(v8) != 2:
                raise RuntimeError("V8 resolver must export the complete pair")
            for key in ("RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH"):
                os.environ.pop(key, None)
            os.environ.update(v8)
            self.save("v8-environment.json", v8)
            self.command("helper-build", self.helper, timeout=3600)
            self.command("helper-verify-before", [*self.helper, "--verify-only"], timeout=120)
            helper_manifest = json.loads((self.output / "helpers/manifest.json").read_text())
            if helper_manifest["source_sha"] != self.args.source_sha or any(
                not Path(artifact["compiler_executable"]).resolve().is_relative_to(self.target)
                for artifact in helper_manifest["artifacts"].values()
            ):
                raise RuntimeError("helper was not compiled from this source into the fresh target")
            helper_env = json.loads((self.output / "helpers/env.json").read_text())
            os.environ.update(helper_env)
            if self.snapshot("before-tests") != self.initial:
                raise RuntimeError("source changed before tests")
            self.tests("ordinary", [*self.package_args, "--lib", "--test-threads", "2"])
            self.ordinary_passed = True
            if self.root_available:
                self.root_attempted = True
                self.command("root-setup", ["sudo", "-n", "python3", "-c", ROOT_SETUP, str(self.root_dir)], timeout=60)
                root_filter = " | ".join("test(=" + name + ")" for name in ROOT_PARENTS)
                self.tests("root", ["-p", "codex-hepta-agentd", "--lib", "--run-ignored", "only",
                                    "-E", root_filter, "--test-threads", "1"], root=True)
                self.root_passed = True
            else:
                self.save("root-not-run.json", {"status": "NOT_RUN", "reason": self.root_unavailable_reason,
                          "expected_parents": ROOT_PARENTS, "observed_executed_tests": 0})
            self.command("helper-verify-after", [*self.helper, "--verify-only"], timeout=120)
            if self.snapshot("after-tests") != self.initial:
                raise RuntimeError("source bytes changed during native qualification")
            self.native_passed = self.ordinary_passed and self.root_passed
            if self.args.maintenance and self.native_passed:
                self.maintenance_started = True
                self.plain("fix", ["just", "fix", "--locked", "--offline", *self.package_args], self.args.timeout_seconds)
                self.plain("fmt", ["just", "fmt", "--base", self.args.format_base_sha], 600)
                self.maintenance_complete = True
                maintained = self.snapshot("after-maintenance")
                self.plain("bins-check", ["cargo", "check", "--locked", "--offline", *self.package_args, "--bins"],
                           self.args.timeout_seconds, self.repo / "codex-rs")
                if self.snapshot("after-bins") != maintained:
                    raise RuntimeError("binary check changed source")
        except (Exception, KeyboardInterrupt) as error:
            self.errors.append(f"{type(error).__name__}: {error}")
        finally:
            if self.root_attempted:
                for label, action in (("cleanup-unmount", lambda: self.plain("root-unmount", ["sudo", "-n", "python3", "-c", ROOT_UNMOUNT, str(self.root_dir)])),
                                      ("cleanup-ownership", lambda: self.restore_ownership("final-evidence-ownership"))):
                    try:
                        action()
                    except Exception as error:
                        self.errors.append(label + ": " + repr(error))
            final = None
            try:
                final = self.snapshot("final")
                if self.initial is not None and not self.maintenance_started and final != self.initial:
                    self.errors.append("final source differs from the initial inventory")
                if self.maintenance_started:
                    self.retain_maintenance()
            except Exception as error:
                self.errors.append("retention: " + repr(error))
            status = {"schema": "hepta.common.native.driver.v1", "source_sha": self.args.source_sha,
                      "status": "passed" if self.native_passed and not self.errors else "failed-or-incomplete",
                      "native_tests_passed_on_original_source": self.native_passed,
                      "ordinary_passed": self.ordinary_passed,
                      "root_status": "passed" if self.root_passed else ("failed-or-incomplete" if self.root_attempted else "NOT_RUN"),
                      "root_unavailable_reason": self.root_unavailable_reason,
                      "source_unchanged_at_finish": final == self.initial if final and self.initial else None,
                      "maintenance_started": self.maintenance_started, "maintenance_complete": self.maintenance_complete,
                      "steps": self.steps, "errors": self.errors, "finished_at": utc_now(),
                      "driver_wall_seconds": time.monotonic() - self.started, "cpu_seconds": None,
                      "complete_research_cost": None, "independent_real_confirmations": 0,
                      "ordinary_abc_route_executed": False, "real_daemon_root_cold_restart_executed": False,
                      "production_adoption_authorized": False}
            self.save("qualification-status.json", status)
            print(json.dumps(status), flush=True)
        return 0 if self.native_passed and not self.errors else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--cargo-build-jobs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--maintenance", action="store_true")
    parser.add_argument("--format-base-sha")
    args = parser.parse_args()
    if args.cargo_build_jobs <= 0 or args.timeout_seconds <= 0:
        parser.error("job and timeout bounds must be positive")
    try:
        return NativeDriver(args).run()
    except Exception as error:
        print("Native driver did not complete: " + repr(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
