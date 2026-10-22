"""Resolver plus three parallel native lanes; local diagnostic draft only. Never updates frozen control digests."""

import argparse
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request

from a32_sshsig_evidence import census, reconcile_nextest, reconcile_bazel, bep_events
from a32_sshsig_controls_nokill import wait_owned

from a32_sshsig_guard import (
    LOCKS, MANIFEST, MEMORY_CASES, PACKAGES, cargo_delta, check_clean, check_delta,
    digest, git, inventory, local_candidate, require, save, verify_bundle,
    verify_input, verify_pass_cases,
)


def dotslash_binary(data, size, expected):
    require(len(data) == size and digest(data) == expected, "DotSlash release asset hash/size mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = [m for m in archive.getmembers() if m.isfile()
                   and Path(m.name).name.lower() in ("dotslash", "dotslash.exe")]
        require(len(members) == 1 and 0 < members[0].size <= 10000000, "wrong DotSlash archive member")
        with archive.extractfile(members[0]) as executable:
            binary = executable.read(10000001)
        require(len(binary) == members[0].size, "truncated DotSlash archive member")
        return binary


class Qualification:
    def __init__(self, evidence, recover_partial=False):
        self.root = Path(__file__).resolve().parents[2]
        self.evidence = Path(evidence).resolve()
        require(not self.evidence.is_relative_to(self.root), "evidence must be outside checkout")
        self.state_path = self.evidence / "source.json"
        self.commands_path = self.evidence / "commands.json"
        self.state, self.commands = {}, []
        for name, path, expected_type in (("state", self.state_path, dict), ("commands", self.commands_path, list)):
            try:
                value = json.loads(path.read_bytes()) if path.exists() else expected_type()
                require(isinstance(value, expected_type), "wrong saved metadata type")
                setattr(self, name, value)
            except (OSError, ValueError, RuntimeError) as error:
                if not recover_partial:
                    raise
                self.state["active_child_latch"] = True
                self.state.setdefault("metadata_errors", []).append({"file": path.name, "error": str(error)})
        if self.state.get("metadata_errors"):
            self.state["input_verified"] = False

    def identity(self):
        return {"source_sha": os.environ["SOURCE_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
                "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "branch": os.environ["GITHUB_REF_NAME"],
                "repository": os.environ["GITHUB_REPOSITORY"], "input_tree": self.state["input_tree"]}

    def flush(self):
        save(self.state_path, self.state)
        save(self.commands_path, self.commands)

    def guard(self, allow_locks=False):
        expected = self.state.get("candidate", {}).get("commit", os.environ["SOURCE_SHA"])
        require(git(self.root, "rev-parse", "HEAD").decode().strip() == expected, "HEAD changed unexpectedly")
        if allow_locks:
            check_delta(self.root, os.environ["SOURCE_SHA"], LOCKS)
        else:
            check_clean(self.root)

    def run(self, name, command, *, cwd=None, allow_locks=False, separate=False):
        """No timeout/kill: admission budget only; unique command/log identities."""
        self.guard(allow_locks)
        require(not any(x["name"] == name for x in self.commands), "command already attempted; no implicit retry")
        budget = self.state.get("admission_seconds", 0)
        require(budget and time.time() - self.state["started_unix"] < budget,
                "admission budget exhausted; preserve partial evidence, do not kill a running Rust process")
        record = {"name": name, "argv": command, "cwd": cwd or ".",
                  "started_unix": time.time(), "status": "running", "subprocess_timeout": None}
        self.commands.append(record); self.flush()
        log = self.evidence / "logs" / f"{name}.log"; log.parent.mkdir(parents=True, exist_ok=True)
        journal = self.evidence / "journal"; journal.mkdir(exist_ok=True)
        save(journal / f"{name}.started.json", record)
        process = None; pending = None; result_bytes = None
        def remember(error):
            nonlocal pending
            if pending is None:
                pending = error
            else:
                pending.add_note("subsequent deferred error: " + type(error).__name__ + ": " + str(error))
        try:
            with log.open("xb") as output, (log.with_suffix(".stderr")).open("xb") as errors:
                process = subprocess.Popen(command, cwd=self.root / (cwd or "."), stdout=output,
                                           stderr=errors if separate else subprocess.STDOUT)
                record["pid"] = process.pid
                try:
                    self.flush()
                except BaseException as error:
                    remember(error)  # Keep ownership: still wait before propagating a journal failure.
                try:
                    result = wait_owned(process, lambda event: self.child_event(name, event))
                except BaseException as error:
                    remember(error)
                    result = process.returncode
            if result is not None:
                record["exit_code"] = result
            record["status"] = "passed" if result == 0 and pending is None else "failed-or-interrupted"
            if pending is None:
                require(result == 0, f"{name} exited {result}; see {log}")
                result_bytes = log.read_bytes()
        except BaseException as error:
            remember(error)
        finally:
            # Normally wait_owned already observed terminal; retain ownership if an intervening observer failed.
            if process is not None and process.returncode is None:
                try:
                    wait_owned(process, lambda event: self.child_event(name, event))
                except BaseException as error:
                    remember(error)
            terminal = process is None or process.returncode is not None
            if not terminal:
                record["status"] = "active-outcome-unknown"
                self.state["active_child_latch"] = True
            else:
                try:
                    self.guard(allow_locks)
                except BaseException as error:
                    record["post_guard_error"] = str(error); remember(error)
            if pending is not None:
                record.update(status="failed", error=str(pending))
            record["finished_unix"] = time.time()
            for operation in (self.flush, lambda: save(journal / f"{name}.finished.json", record),
                              lambda: print(json.dumps(record), flush=True)):
                try:
                    operation()
                except BaseException as error:
                    remember(error)
        if pending is not None:
            raise pending
        return result_bytes

    def child_event(self, name, event):
        self.state.setdefault("child_events", []).append({"command": name, **event})
        self.flush()

    def init(self):
        require(not self.evidence.exists(), "evidence directory already exists")
        self.evidence.mkdir(parents=True)
        source = os.environ["SOURCE_SHA"]
        manifest = verify_input(self.root, source, os.environ["GITHUB_REF_NAME"])
        require(git(self.root, "config", "--get", "core.autocrlf").decode().strip() == "false",
                "checkout must be configured for canonical bytes before materialization")
        (self.evidence / "input-eol.txt").write_bytes(git(self.root, "ls-files", "--eol"))
        self.state = {"input_sha": source,
                      "started_unix": time.time(), "lane": os.environ["QUALIFICATION_LANE"],
                      "admission_seconds": {"resolver-linux": 1800, "linux": 3000, "windows": 4800, "windows-owner": 2100}[os.environ["QUALIFICATION_LANE"]],
                      "input_tree": git(self.root, "rev-parse", "HEAD^{tree}").decode().strip(),
                      "base": manifest["base"], "source_manifest_sha256": digest((self.root / MANIFEST).read_bytes()),
                      "input_head_qualified": False, "full_project_qualified": False,
                      "input_verified": True, "native_completed": False, "published": False,
                      "control_sources_hash_bound": True,
                      "sandbox_deletion_issue_qualified": False,
                      "job": os.environ["GITHUB_JOB"], "runner_os": os.environ["RUNNER_OS"],
                      "runner_arch": os.environ["RUNNER_ARCH"], "checkout_autocrlf": False}
        self.state["source_bytes_policy"] = {"all_tracked_raw_blobs_and_types": True, "git_index_modes_exact": True,
             "physical_posix_executable_bits_checked": os.name != "nt", "tracked_symlink_placeholder_admitted": False}
        self.state["identity"] = self.identity()
        (self.evidence / "input.index").write_bytes(git(self.root, "ls-tree", "-r", "HEAD"))
        (self.evidence / "input.patch").write_bytes(git(self.root, "diff", "--binary", manifest["base"], source))
        shutil.copyfile(self.root / MANIFEST, self.evidence / "source-manifest.json")
        for path in [*LOCKS, *[f["path"] for f in manifest["files"]], *manifest["auxiliary_paths"]]:
            output = self.evidence / "input" / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(git(self.root, "show", f"{source}:{path}"))
        self.flush()

    def paths(self):
        self.guard()
        root = Path(os.environ["RUNNER_TEMP"]) / "a32-b"
        require(not root.exists(), "fresh per-job build root required; never repurpose an existing tree")
        names = {"BAZEL_OUTPUT_BASE": "o", "BAZEL_OUTPUT_USER_ROOT": "b", "BAZEL_REPOSITORY_CACHE": "r",
                 "BAZEL_REPO_CONTENTS_CACHE": "rc", "CARGO_TARGET_DIR": "c", "TEMP": "t", "TMP": "t"}
        values = {key: str(root / leaf) for key, leaf in names.items()}
        for value in set(values.values()):
            Path(value).mkdir(parents=True)
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
            for key, value in {"CODEX_REPO_ROOT": str(self.root), **values}.items():
                print(key + "=" + value, file=stream)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            print("bazel-output-base=" + values["BAZEL_OUTPUT_BASE"], file=stream)
        save(self.evidence / "build-paths.json", {"paths": values,
             "dev_drive_provisioning": False, "host_security_changes": False})

    def dotslash(self):
        # Same release observed in the owner run, but no mutable releases/latest.
        self.guard()
        assets = {
            "linux": ("dotslash-ubuntu-22.04.x86_64.v0.5.9.tar.gz", 777657,
                      "ba6b6908c69db8264efdb8ee32f4906284ea3b77247c611339b5f60160cc5691", "dotslash"),
            "win32": ("dotslash-windows.v0.5.9.tar.gz", 613807,
                      "c925840a9bf9105a187cd120278cb023c51dac0cecb3234855152422751b7b41", "dotslash.exe"),
        }
        name, size, expected, binary_name = assets[sys.platform]
        url = "https://github.com/facebook/dotslash/releases/download/v0.5.9/" + name
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read(size + 1)
        binary_data = dotslash_binary(data, size, expected)
        folder = self.evidence / "tools"
        folder.mkdir()
        (folder / name).write_bytes(data)
        binary = folder / binary_name
        binary.write_bytes(binary_data)
        binary.chmod(0o755)
        with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8") as path:
            print(str(folder), file=path)
        output = self.run("install-dotslash-version", [str(binary), "--version"])
        require(output.decode().strip() == "DotSlash 0.5.9", "wrong pinned DotSlash binary version")
        save(folder / "installation.json", {"url": url, "sha256": expected, "bytes": size,
             "binary_sha256": digest(binary_data), "version": "0.5.9"})
        self.guard()

    def versions(self):
        from a32_sshsig_bazel import verify_installation
        verify_installation(self)
        save(self.evidence / "host.json", {"platform": platform.platform(), "machine": platform.machine(),
             "image": {k: os.environ.get(k) for k in ("ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH",
                       "VCToolsInstallDir", "WindowsSDKVersion", "WindowsSdkDir")}})
        commands = {"python": [sys.executable, "--version"], "rustc": ["rustc", "--version", "--verbose"],
                    "cargo": ["cargo", "--version"], "nextest": ["cargo", "nextest", "--version"],
                    "just": ["just", "--version"], "uv": ["uv", "--version"],
                    "bazel": ["bazel", "version", "--gnu_format"], "dotslash": ["dotslash", "--version"]}
        expected = {"python": "Python 3.12.10", "rustc": "rustc 1.95.0 ", "cargo": "cargo 1.95.0 ",
                    "nextest": "cargo-nextest 0.9.103 ", "just": "just 1.51.0", "uv": "uv 0.11.3 ",
                    "dotslash": "DotSlash 0.5.9"}
        for name, command in commands.items():
            output = self.run("version-" + name, command)
            require((b"bazel 9.3.0" in output.splitlines()) if name == "bazel"
                    else output.decode().strip().startswith(expected[name]), f"unexpected {name} version")
            if name == "rustc":
                host = "x86_64-pc-windows-msvc" if sys.platform == "win32" else "x86_64-unknown-linux-gnu"
                require(f"host: {host}".encode() in output.splitlines(), "unexpected native Rust host")
        require((self.root / ".bazelversion").read_text().strip() == "9.3.0", "wrong repository Bazel version")

    def resolve(self):
        require(sys.platform == "linux" and self.state["lane"] == "resolver-linux", "resolver-only Linux lane required")
        self.versions()
        self.run("version-cargo-deny", ["cargo", "deny", "--version"])
        require("cargo-deny 0.19.0" in (self.evidence / "logs/version-cargo-deny.log").read_text(),
                "unexpected cargo-deny version")
        self.run("harness-tests", [sys.executable, "-m", "unittest", "discover", "-s", ".github/scripts",
                                 "-p", "test_a32_sshsig*.py", "-v"])
        from a32_sshsig_format_discovery import Discovery
        self.state["format_writer_may_be_active"] = True; self.flush()
        discovery = None; format_error = None
        try:
            manifest = json.loads((self.evidence / "source-manifest.json").read_bytes())
            def admit():
                require(time.time() - self.state["started_unix"] < self.state["admission_seconds"],
                        "formatter admission budget exhausted; no new child launched")
            discovery = Discovery(self.root, self.evidence, self.state["input_sha"], self.state["input_tree"], manifest, admit)
            require(discovery.run(), "HOLD: genuine formatting output requires independent integration; no locks/tests/publication")
            self.state["pre_resolution_format_passed"] = True
        except BaseException as error:
            format_error = error; raise
        finally:
            self.state["format_writer_may_be_active"] = discovery is None or discovery.receipt["child_unsettled"]
            try:
                self.flush()
            except BaseException as error:
                if format_error is None:
                    raise
                format_error.add_note("format phase state write failed: " + repr(error))
        self.run("rustsec-oracle", [sys.executable, "-m", "unittest", "-v", "scripts.tests.test_hepta_rustsec_guard"])
        self.run("rustsec-policy", [sys.executable, "scripts/check_hepta_rustsec_advisories.py", "--repo-root", "."])
        self.run("cargo-resolve", ["cargo", "metadata", "--format-version", "1", "--all-features"],
                 cwd="codex-rs", allow_locks=True)
        before = (self.evidence / "input/codex-rs/Cargo.lock").read_bytes()
        cargo_delta(before, (self.root / LOCKS[0]).read_bytes())
        self.run("cargo-locked-metadata", ["cargo", "metadata", "--locked", "--format-version", "1", "--all-features"],
                 cwd="codex-rs", allow_locks=True)
        cargo_first = (self.root / LOCKS[0]).read_bytes()
        (self.evidence / "Cargo.lock.first").write_bytes(cargo_first)
        self.run("cargo-resolve-repeat", ["cargo", "metadata", "--format-version", "1", "--all-features"],
                 cwd="codex-rs", allow_locks=True)
        require((self.root / LOCKS[0]).read_bytes() == cargo_first, "Cargo repeated generation changed bytes")
        (self.evidence / "Cargo.lock.second").write_bytes((self.root / LOCKS[0]).read_bytes())
        # Same complete policy/check selection and cargo-deny release as a32's action.
        self.run("cargo-deny-full-policy", ["cargo", "deny", "--log-level", "warn", "--all-features", "check"],
                 cwd="codex-rs", allow_locks=True)
        self.run("bazel-lock-update", ["just", "bazel-lock-update"], allow_locks=True)
        first = (self.root / LOCKS[1]).read_bytes()
        (self.evidence / "MODULE.bazel.lock.first").write_bytes(first)
        self.run("bazel-lock-check", ["just", "bazel-lock-check"], allow_locks=True)
        self.run("bazel-lock-repeat", ["just", "bazel-lock-update"], allow_locks=True)
        require((self.root / LOCKS[1]).read_bytes() == first, "Bazel repeat generation changed bytes")
        (self.evidence / "MODULE.bazel.lock.second").write_bytes((self.root / LOCKS[1]).read_bytes())
        self.run("bazel-lock-recheck", ["just", "bazel-lock-check"], allow_locks=True)
        cargo_delta(before, (self.root / LOCKS[0]).read_bytes())
        self.make_candidate()
        bundle = self.evidence / "locks"
        for path in LOCKS:
            target = bundle / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git(self.root, "show", f"HEAD:{path}"))
        save(bundle / "manifest.json", {"identity": self.identity(), "files": inventory(bundle),
             "candidate": self.state["candidate"], "resolver_gates_passed": True,
             "cargo_delta": "exactly acceptance codex-utils-path and windows-sys0.52 edges; no other semantic changes",
             "bazel_version": "9.3.0", "bazel_repeat_identical": True})
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            print("lock_manifest_sha256=" + digest((bundle / "manifest.json").read_bytes()), file=output)
            print("candidate_tree=" + self.state["candidate"]["tree"], file=output)
        self.state["lock_manifest_sha256"] = digest((bundle / "manifest.json").read_bytes())
        self.state["resolver_completed"] = True
        self.flush()

    def make_candidate(self):
        (self.evidence / "generated-locks.patch").write_bytes(git(self.root, "diff", "--binary", os.environ["SOURCE_SHA"]))
        self.state["candidate"] = local_candidate(self.root, os.environ["SOURCE_SHA"])
        (self.evidence / "generated.index").write_bytes(git(self.root, "ls-tree", "-r", "HEAD"))
        self.flush()

    def consume(self, incoming):
        require((sys.platform, self.state["lane"]) in (("linux", "linux"), ("win32", "windows"), ("win32", "windows-owner")),
                "lock consumer must be one of the three native lanes")
        self.guard()
        bundle = Path(incoming).resolve()
        require(not bundle.is_relative_to(self.root), "incoming bundle must be outside checkout")
        expected_digest = os.environ["EXPECTED_LOCK_MANIFEST_SHA256"]
        require(len(expected_digest) == 64, "missing resolver step manifest digest")
        manifest = verify_bundle(bundle, self.identity(), expected_digest)
        cargo_delta((self.evidence / "input/codex-rs/Cargo.lock").read_bytes(), (bundle / LOCKS[0]).read_bytes())
        for path in LOCKS:
            (self.root / path).write_bytes((bundle / path).read_bytes())
        self.make_candidate()
        require(self.state["candidate"] == manifest["candidate"], "native candidate differs from resolver")
        require(self.state["candidate"]["tree"] == os.environ["EXPECTED_CANDIDATE_TREE"],
                "native tree differs from independent resolver step output")
        shutil.copyfile(bundle / "manifest.json", self.evidence / "consumed-lock-manifest.json")
        self.state["lock_manifest_sha256"] = expected_digest
        self.state["same_run_locks_verified"] = True
        self.flush()

    def probe(self, incoming):
        from a32_sshsig_preflight import PROBE_SHA256, IDENTITY_ENV
        require(sys.platform == "win32", "identity probe needs native Windows")
        require("token_probe" not in self.state, "preflight already consumed; never overwrite observations")
        self.guard()
        incoming = Path(incoming)
        receipt = json.loads((incoming / "receipt.json").read_bytes())
        data = (incoming / "token.json").read_bytes()
        require(receipt.get("schema") == "a32.sshsig-independent-preflight.v1"
                and receipt.get("probe_sha256") == PROBE_SHA256 and receipt.get("exit_code") == 0
                and receipt.get("token_sha256") == digest(data)
                and receipt.get("identity") == {key: os.environ[value] for key, value in IDENTITY_ENV.items()},
                "independent token observation identity/hash/outcome mismatch")
        token = json.loads(data)
        require(token.get("schema") == "a32.sshsig-token-probe.v1" and token.get("thread_impersonating") is False
                and token.get("query_errors") == [], "token query uncertain or actively impersonating")
        for name in ("token.json", "receipt.json"):
            destination = "token.json" if name == "token.json" else "token-preflight.json"
            with (self.evidence / destination).open("xb") as stream:
                stream.write((incoming / name).read_bytes())
        self.state["token_probe"] = {"sha256": digest(data), "owner_capable": bool(token.get("owner_capable_sid")),
              "linked_token": token.get("linked_token"), "process": token.get("process"),
              "normal_user_execution_proved": False, "native_tests_independently_requery": True}
        self.flush()

    def graph(self):
        manifest = json.loads((self.evidence / "source-manifest.json").read_bytes())
        lane = "windows" if sys.platform == "win32" else "linux"
        targets = manifest["bazel_targets"][lane]
        require(targets and len(targets) == len(set(targets)) and len(targets) <= 32,
                "empty/duplicate/unbounded scoped Bazel owners")
        require(all(x.startswith("//codex-rs/") and ":" in x for x in targets), "unscoped Bazel target")
        test_path = (str(self.evidence / "tools") + ":/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
                     if sys.platform != "win32" else os.environ["PATH"])
        self.state["bazel_configuration_flags"] = ["--experimental_convenience_symlinks=ignore", "--test_env=PATH=" + test_path]
        flags = self.state["bazel_configuration_flags"]
        expression = "deps(set(" + " ".join(targets) + "))"
        data = self.run("configured-cquery", ["bazel", "cquery", *flags, "--lockfile_mode=error", expression, "--output=label"])
        from a32_sshsig_closure import validate_closure
        validate_closure(data, targets)
        self.run("configured-aquery", ["bazel", "aquery", *flags, "--lockfile_mode=error", expression, "--output=jsonproto"])
        bep = self.evidence / "analysis.bep.jsonl"
        self.run("configured-analysis", ["bazel", "build", "--jobs=2", *flags, "--nobuild", "--lockfile_mode=error",
                 "--build_event_json_file=" + str(bep), *targets])
        analysis_events = bep_events(bep.read_bytes(), 0, "build", allow_no_build=True)
        self.state["analysis_bep"] = {"sha256": digest(bep.read_bytes()), "event_count": len(analysis_events),
             "expected_no_build_events": sum("aborted" in event for event in analysis_events), "native_execution": False}
        self.state["configured_targets"] = targets; self.flush()

    def native(self):
        require("candidate" in self.state, "native tests require genuinely generated locks")
        require((sys.platform, self.state["lane"]) in (("linux", "linux"), ("win32", "windows"), ("win32", "windows-owner")),
                "resolver is not a native qualification lane")
        require(self.state.get("same_run_locks_verified"), "native lane must consume same-run generated locks")
        if sys.platform == "win32":
            require("token_probe" in self.state, "query-only token preflight must precede native bootstrap")
        self.versions()
        supplemental = self.state["lane"] == "windows-owner"
        if supplemental:
            require(self.state["token_probe"]["owner_capable"],
                    "SETUP_UNAVAILABLE: no enabled owner-capable SID; not a passing owner negative")
        self.graph()  # Configured census precedes every lane's split/execution.
        self.run("native-locked-metadata", ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"], cwd="codex-rs")
        packages = ("codex-utils-path", "codex-hepta-operator-acceptance") if supplemental else PACKAGES
        feature = ["--features", "windows-custody-privileged-tests"] if supplemental else []
        fmt = ["cargo", "fmt"]; clippy = ["just", "clippy", "--locked"]
        for package in packages:
            fmt.extend(["--package", package]); clippy.extend(["-p", package])
        self.run("fmt-check", [*fmt, "--", "--check"], cwd="codex-rs")
        self.run("clippy-nonmutating", [*clippy, *feature], cwd="codex-rs")
        manifest = json.loads((self.evidence / "source-manifest.json").read_bytes())
        lane = "windows" if sys.platform == "win32" else "linux"
        for package in packages:
            package_feature = feature if package == "codex-hepta-operator-acceptance" else []
            listing = self.run(package + "-compiled-census", ["cargo", "nextest", "list", "--locked", "-p", package,
                               *package_feature, "--message-format", "json"], cwd="codex-rs", separate=True)
            expected = census(listing, package, manifest["ignored_tests"][lane].get(package, []))
            output = self.run(package + "-tests", ["just", "test", "--locked", "-p", package, *package_feature,
                "--test-threads", "1", "--retries", "0", "--no-tests", "fail", "--status-level", "all",
                "--final-status-level", "all", "--failure-output", "immediate", "--success-output", "immediate"], cwd="codex-rs")
            result = reconcile_nextest(output, expected)
            if package == "codex-hepta-memory":
                verify_pass_cases(output.decode(), MEMORY_CASES)
            if sys.platform == "win32" and package == "codex-hepta-operator-acceptance":
                required = ["durable::windows::output::tests::read_only_private_directory_exercises_native_sync_helper_error_propagation"]
                if supplemental:
                    required += ["durable::windows::custody_tests::" + case for case in (
                        "wrong_owner_rejects_even_with_a_current_user_only_dacl",
                        "owner_change_after_open_rejects_the_same_retained_descriptor",
                        "final_symlink_rejects_even_when_its_target_is_private_and_valid")]
                require(all(result["cases"].get(package + " " + case) == "PASS" for case in required),
                        "required native owner/reparse/helper case absent or not passed")
                result["required_native_cases"] = required
            save(self.evidence / (package + "-counts.json"), result)
        if not supplemental:
            targets = self.state["configured_targets"]
            testlogs = Path(self.run("bazel-testlogs", ["bazel", "info", "bazel-testlogs"]).decode().strip())
            common = ["bazel", "test", "--jobs=2", *self.state["bazel_configuration_flags"], "--lockfile_mode=error", "--nocache_test_results", "--flaky_test_attempts=1",
                      "--runs_per_test=1", "--test_output=all"]
            listing_bep = self.evidence / "bazel-list.bep.jsonl"
            self.run("bazel-compiled-census", [*common, "--test_arg=--list", "--build_event_json_file=" + str(listing_bep), *targets])
            listing = reconcile_bazel(listing_bep.read_bytes(), 0, targets, testlogs, self.evidence / "bazel-list")
            save(self.evidence / "bazel-compiled-census.json", listing)
            run_bep = self.evidence / "bazel-tests.bep.jsonl"
            self.run("bazel-full-owners", [*common, "--build_event_json_file=" + str(run_bep), *targets])
            actual = reconcile_bazel(run_bep.read_bytes(), 0, targets, testlogs, self.evidence / "bazel-tests",
                                    listing["compiled_cases"], manifest["bazel_ignored_tests"][lane])
            save(self.evidence / "bazel-counts.json", actual)
        if sys.platform == "win32" and not supplemental:
            for name, folder, pattern in (("acquisition-oracle", ".github/scripts", "test_check_windows_private_state_acquisition.py"),
                                         ("recovery-oracle", "codex-rs/state/tests/windows-recovery-controls", "test_run.py")):
                self.run(name, [sys.executable, "-m", "unittest", "discover", "-s", folder, "-p", pattern, "-v"])
            self.run("acquisition-controls", [sys.executable, ".github/scripts/a32_sshsig_controls_nokill.py", "acquisition",
                     str(self.evidence / "acquisition-controls")])
            self.run("recovery-controls", [sys.executable, ".github/scripts/a32_sshsig_controls_nokill.py", "recovery",
                     str(self.evidence / "recovery-controls")])
        self.guard(); self.state["native_completed"] = True
        self.state["scope"] = "supplemental owner/reparse full suites" if supplemental else "configured default scoped owners"
        self.state["product_qualified"] = False
        self.state["open_gates"] = ["independent evidence review", "non-elevated lane if default was elevated",
                                    "public G5 post-admission device-fault scope not proved by helper-only flush control"]
        self.flush()

    def collect(self):
        from a32_sshsig_collection import collect
        collect(self)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("init", "dotslash", "resolve", "consume", "probe", "paths", "native", "collect", "prerequisites", "bazel"))
    parser.add_argument("evidence")
    parser.add_argument("--incoming")
    args = parser.parse_args()
    qualification = Qualification(args.evidence, recover_partial=args.phase == "collect")
    try:
        if args.phase == "bazel":
            from a32_sshsig_bazel import install
            install(qualification)
        elif args.phase == "prerequisites":
            from a32_sshsig_parallel import prerequisites
            prerequisites(qualification)
        elif args.phase in ("consume", "probe"):
            getattr(qualification, args.phase)(args.incoming)
        else:
            getattr(qualification, args.phase)()
    except BaseException as error:
        try:
            save(qualification.evidence / (args.phase + "-failure.json"),
                 {"phase": args.phase, "error": str(error), "traceback": traceback.format_exc()})
        except BaseException as secondary:
            error.add_note("failure receipt write failed: " + repr(secondary))
        raise


if __name__ == "__main__":
    main()
