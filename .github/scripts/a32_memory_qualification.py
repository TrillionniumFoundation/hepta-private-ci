"""Two-job, no-publication native diagnostic. Never updates frozen control digests."""
from __future__ import annotations

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

from a32_memory_qualification_guard import (
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
    def __init__(self, evidence):
        self.root = Path(__file__).resolve().parents[2]
        self.evidence = Path(evidence).resolve()
        require(not self.evidence.is_relative_to(self.root), "evidence must be outside checkout")
        self.state_path = self.evidence / "source.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.commands_path = self.evidence / "commands.json"
        self.commands = json.loads(self.commands_path.read_text()) if self.commands_path.exists() else []

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

    def run(self, name, command, *, cwd=None, allow_locks=False, timeout=2700):
        self.guard(allow_locks)
        record = {"name": name, "argv": command, "cwd": cwd or ".", "timeout_seconds": timeout,
                  "started_unix": time.time(), "status": "running"}
        self.commands.append(record)
        self.flush()
        log = self.evidence / "logs" / f"{name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log.open("wb") as output:
                result = subprocess.run(command, cwd=self.root / (cwd or "."), stdout=output,
                                        stderr=subprocess.STDOUT, timeout=timeout, check=False)
            record.update(exit_code=result.returncode, status="passed" if result.returncode == 0 else "failed")
            require(result.returncode == 0, f"{name} exited {result.returncode}; see {log}")
            return log.read_text(encoding="utf-8", errors="replace")
        except BaseException as error:
            record.update(status="failed", error=str(error))
            raise
        finally:
            try:
                self.guard(allow_locks)
            except BaseException as error:
                record.update(status="failed", post_guard_error=str(error))
                raise
            finally:
                record["finished_unix"] = time.time()
                self.flush()
                print(json.dumps(record), flush=True)

    def init(self):
        require(not self.evidence.exists(), "evidence directory already exists")
        self.evidence.mkdir(parents=True)
        source = os.environ["SOURCE_SHA"]
        manifest = verify_input(self.root, source, os.environ["GITHUB_REF_NAME"])
        require(git(self.root, "config", "--get", "core.autocrlf").decode().strip() == "false",
                "checkout must be configured for canonical bytes before materialization")
        (self.evidence / "input-eol.txt").write_bytes(git(self.root, "ls-files", "--eol"))
        self.state = {"input_sha": source,
                      "input_tree": git(self.root, "rev-parse", "HEAD^{tree}").decode().strip(),
                      "base": manifest["base"], "source_manifest_sha256": digest((self.root / MANIFEST).read_bytes()),
                      "input_head_qualified": False, "full_project_qualified": False,
                      "input_verified": True, "native_completed": False, "published": False,
                      "strict_implementation_maps_rebound": False,
                      "sandbox_deletion_issue_qualified": False,
                      "job": os.environ["GITHUB_JOB"], "runner_os": os.environ["RUNNER_OS"],
                      "runner_arch": os.environ["RUNNER_ARCH"], "checkout_autocrlf": False}
        versions = ["version-" + n for n in ("python", "rustc", "cargo", "nextest", "just", "uv", "bazel", "dotslash")]
        common = ["native-locked-metadata", "fmt-check", "clippy-nonmutating", *[p + "-tests" for p in PACKAGES]]
        if sys.platform == "win32":
            plan = [*versions, *common, "acquisition-oracle", "recovery-oracle", "acquisition-controls", "recovery-controls"]
        else:
            plan = [*versions, "version-cargo-deny", "guard-tests", "rustsec-oracle", "rustsec-policy",
                    "cargo-resolve", "cargo-locked-metadata", "cargo-deny-full-policy", "bazel-lock-update",
                    "bazel-lock-check", "bazel-lock-repeat", "bazel-lock-recheck", *common]
        installation = ["install-dotslash-version"]
        if sys.platform == "linux":
            installation.insert(0, "install-dotslash-system-copy")
        self.state["command_plan"] = {name: "not_run" for name in [*installation, *plan]}
        self.state["identity"] = self.identity()
        (self.evidence / "input.index").write_bytes(git(self.root, "ls-tree", "-r", "HEAD"))
        (self.evidence / "input.patch").write_bytes(git(self.root, "diff", "--binary", manifest["base"], source))
        shutil.copyfile(self.root / MANIFEST, self.evidence / "source-manifest.json")
        for path in [*LOCKS, *[f["path"] for f in manifest["files"]], *manifest["auxiliary_paths"]]:
            output = self.evidence / "input" / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(git(self.root, "show", f"{source}:{path}"))
        self.flush()

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
        if sys.platform == "linux":
            self.run("install-dotslash-system-copy", ["sudo", "cp", str(binary), "/usr/local/bin/dotslash"])
        else:
            shutil.copyfile(binary, Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WindowsApps/dotslash.exe")
        with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8") as path:
            print(str(folder), file=path)
        output = self.run("install-dotslash-version", [str(binary), "--version"])
        require(output.strip() == "DotSlash 0.5.9", "wrong pinned DotSlash binary version")
        save(folder / "installation.json", {"url": url, "sha256": expected, "bytes": size,
             "binary_sha256": digest(binary_data), "version": "0.5.9"})
        self.guard()

    def versions(self):
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
            require(("bazel 9.3.0" in output.splitlines()) if name == "bazel"
                    else output.strip().startswith(expected[name]), f"unexpected {name} version")
            if name == "rustc":
                host = "x86_64-pc-windows-msvc" if sys.platform == "win32" else "x86_64-unknown-linux-gnu"
                require(f"host: {host}" in output.splitlines(), "unexpected native Rust host")
        require((self.root / ".bazelversion").read_text().strip() == "9.3.0", "wrong repository Bazel version")

    def resolve(self):
        require(sys.platform == "linux", "resolver must run on native Linux")
        self.versions()
        self.run("version-cargo-deny", ["cargo", "deny", "--version"])
        require("cargo-deny 0.19.0" in (self.evidence / "logs/version-cargo-deny.log").read_text(),
                "unexpected cargo-deny version")
        self.run("guard-tests", [sys.executable, "-m", "unittest", "discover", "-s", ".github/scripts",
                                 "-p", "test_a32_memory_qualification.py", "-v"])
        self.run("rustsec-oracle", [sys.executable, "-m", "unittest", "-v", "scripts.tests.test_hepta_rustsec_guard"])
        self.run("rustsec-policy", [sys.executable, "scripts/check_hepta_rustsec_advisories.py", "--repo-root", "."])
        self.run("cargo-resolve", ["cargo", "metadata", "--format-version", "1", "--all-features"],
                 cwd="codex-rs", allow_locks=True)
        before = (self.evidence / "input/codex-rs/Cargo.lock").read_bytes()
        cargo_delta(before, (self.root / LOCKS[0]).read_bytes())
        self.run("cargo-locked-metadata", ["cargo", "metadata", "--locked", "--format-version", "1", "--all-features"],
                 cwd="codex-rs", allow_locks=True)
        # Same complete policy/check selection and cargo-deny release as a32's action.
        self.run("cargo-deny-full-policy", ["cargo", "deny", "--log-level", "warn", "--all-features", "check"],
                 cwd="codex-rs", allow_locks=True)
        self.run("bazel-lock-update", ["just", "bazel-lock-update"], allow_locks=True)
        first = (self.root / LOCKS[1]).read_bytes()
        (self.evidence / "MODULE.bazel.lock.first").write_bytes(first)
        self.run("bazel-lock-check", ["just", "bazel-lock-check"], allow_locks=True)
        self.run("bazel-lock-repeat", ["just", "bazel-lock-update"], allow_locks=True)
        require((self.root / LOCKS[1]).read_bytes() == first, "Bazel repeat generation changed bytes")
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
             "cargo_delta": "exactly two codex-utils-path edges; no other semantic changes",
             "bazel_version": "9.3.0", "bazel_repeat_identical": True})
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            print("lock_manifest_sha256=" + digest((bundle / "manifest.json").read_bytes()), file=output)
            print("candidate_tree=" + self.state["candidate"]["tree"], file=output)
        self.state["resolver_completed"] = True
        self.flush()

    def make_candidate(self):
        (self.evidence / "generated-locks.patch").write_bytes(git(self.root, "diff", "--binary", os.environ["SOURCE_SHA"]))
        self.state["candidate"] = local_candidate(self.root, os.environ["SOURCE_SHA"])
        (self.evidence / "generated.index").write_bytes(git(self.root, "ls-tree", "-r", "HEAD"))
        self.flush()

    def consume(self, incoming):
        require(sys.platform == "win32", "consumer must run on native Windows")
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
        require(self.state["candidate"] == manifest["candidate"], "Windows generated candidate differs from resolver")
        require(self.state["candidate"]["tree"] == os.environ["EXPECTED_CANDIDATE_TREE"],
                "Windows tree differs from independent resolver step output")
        shutil.copyfile(bundle / "manifest.json", self.evidence / "consumed-lock-manifest.json")
        self.state["same_run_locks_verified"] = True
        self.flush()

    def native(self):
        require("candidate" in self.state, "native tests require genuine generated locks")
        if sys.platform == "win32":
            require(self.state.get("same_run_locks_verified"), "unverified Windows lock source")
            self.versions()
        else:
            require(self.state.get("resolver_completed"), "resolver incomplete")
        self.run("native-locked-metadata", ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"], cwd="codex-rs")
        fmt = ["cargo", "fmt"]
        clippy = ["just", "clippy", "--locked"]
        for package in PACKAGES:
            fmt.extend(["--package", package])
            clippy.extend(["-p", package])
        self.run("fmt-check", [*fmt, "--", "--check"], cwd="codex-rs")
        self.run("clippy-nonmutating", clippy, cwd="codex-rs")
        for package in PACKAGES:
            output = self.run(package + "-tests", ["just", "test", "--locked", "-p", package,
                "--test-threads", "1", "--retries", "0", "--no-tests", "fail", "--status-level", "all",
                "--final-status-level", "all", "--failure-output", "immediate", "--success-output", "immediate"], cwd="codex-rs")
            if sys.platform == "win32" and package == "codex-hepta-memory":
                verify_pass_cases(output, MEMORY_CASES)
            if sys.platform == "win32" and package == "codex-state":
                verify_pass_cases(output, ("retained_sources_deny_same_size_write_and_byte_identical_replacement",
                    "every_present_sidecar_is_pinned_and_absent_sidecar_appearance_is_indeterminate",
                    "attributes_are_part_of_the_complete_retained_identity",
                    "materialized_copy_is_private_complete_bounded_and_create_new"))
        if sys.platform == "win32":
            for name, folder, pattern in (("acquisition-oracle", ".github/scripts", "test_check_windows_private_state_acquisition.py"),
                                         ("recovery-oracle", "codex-rs/state/tests/windows-recovery-controls", "test_run.py")):
                self.run(name, [sys.executable, "-m", "unittest", "discover", "-s", folder, "-p", pattern, "-v"])
            self.run("acquisition-controls", [sys.executable, ".github/scripts/check_windows_private_state_acquisition.py",
                     str(self.evidence / "acquisition-controls")], timeout=3900)
            self.run("recovery-controls", [sys.executable, "codex-rs/state/tests/windows-recovery-controls/run.py",
                     str(self.evidence / "recovery-controls")], timeout=3900)
        self.guard()
        self.state["native_completed"] = True
        self.flush()

    def collect(self):
        self.evidence.mkdir(parents=True, exist_ok=True)
        for path in LOCKS:
            output = self.evidence / "observed-current-locks" / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes((self.root / path).read_bytes())
        for name, args in {"final-status.txt": ("status", "--porcelain", "--untracked-files=all"),
                           "final-diff.patch": ("diff", "--binary", "HEAD"),
                           "final-index-flags.txt": ("ls-files", "-v", "-f"),
                           "final-index.index": ("ls-files", "--stage")}.items():
            (self.evidence / name).write_bytes(git(self.root, *args))
        self.state["steps"] = json.loads(os.environ.get("STEP_RESULTS", "{}"))
        self.state["final_head"] = git(self.root, "rev-parse", "HEAD").decode().strip()
        self.state["final_source_clean"] = False
        for record in self.commands:
            self.state.setdefault("command_plan", {})[record["name"]] = record["status"]
        try:
            self.guard()
            self.state["final_source_clean"] = True
        finally:
            self.flush()
            save(self.evidence / "inventory.json", inventory(self.evidence, ("inventory.json",)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("init", "dotslash", "resolve", "consume", "native", "collect"))
    parser.add_argument("evidence")
    parser.add_argument("--incoming")
    args = parser.parse_args()
    qualification = Qualification(args.evidence)
    try:
        if args.phase == "consume":
            qualification.consume(args.incoming)
        else:
            getattr(qualification, args.phase)()
    except BaseException as error:
        save(qualification.evidence / (args.phase + "-failure.json"),
             {"phase": args.phase, "error": str(error), "traceback": traceback.format_exc()})
        if args.phase == "collect":
            save(qualification.evidence / "inventory.json", inventory(qualification.evidence, ("inventory.json",)))
        raise


if __name__ == "__main__":
    main()
