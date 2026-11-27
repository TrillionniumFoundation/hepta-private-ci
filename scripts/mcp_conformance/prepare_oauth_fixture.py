"""Build the reviewed OAuth-origin fixture fork from the pinned upstream source.

Run this only under an explicitly activated source manifest. The existing
hepta_ci_exec process owner captures each real child command. The resulting
receipt binds the fork CLI to this Hepta checkout; it is not a conformance pass.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import re
import sys
import time

_IDENTITY_PATH = Path(__file__).resolve().with_name("conformance_fixture.py")
if _IDENTITY_PATH.is_symlink() or not _IDENTITY_PATH.is_file():
    raise RuntimeError("candidate identity module is not a regular source file")
with _IDENTITY_PATH.open("rb") as _identity_stream:
    _IDENTITY_RAW = _identity_stream.read(128 * 1024 + 1)
if len(_IDENTITY_RAW) > 128 * 1024:
    raise RuntimeError("candidate identity module exceeds its bound")
_IDENTITY_SPEC = importlib.util.spec_from_file_location(
    "conformance_fixture", _IDENTITY_PATH
)
if _IDENTITY_SPEC is None:
    raise RuntimeError("candidate identity module has no source specification")
_IDENTITY_MODULE = importlib.util.module_from_spec(_IDENTITY_SPEC)
_PREVIOUS_IDENTITY_MODULE = sys.modules.get("conformance_fixture")
sys.modules["conformance_fixture"] = _IDENTITY_MODULE
try:
    exec(
        compile(
            _IDENTITY_RAW, str(_IDENTITY_PATH), "exec", dont_inherit=True, optimize=0
        ),
        _IDENTITY_MODULE.__dict__,
    )
except BaseException:
    if sys.modules.get("conformance_fixture") is _IDENTITY_MODULE:
        if _PREVIOUS_IDENTITY_MODULE is None:
            del sys.modules["conformance_fixture"]
        else:
            sys.modules["conformance_fixture"] = _PREVIOUS_IDENTITY_MODULE
    raise
_IDENTITY_MODULE.__hepta_compiled_sha256__ = hashlib.sha256(_IDENTITY_RAW).hexdigest()
del _IDENTITY_RAW

from conformance_fixture import (  # noqa: E402 - exact raw module above.
    CAPS,
    HEPTA_EXEC_GIT_BLOB,
    FIXTURE_STEP,
    inspect_original_build,
    record_sdk_build_boundary,
    verify_receipt,
    PATCH_PATHS,
    UPSTREAM_COMMIT,
    UPSTREAM_TREE,
    commit_identity,
    git_blob,
    load_manifest,
    read_json,
    regular_bytes,
    require,
    snapshot_dist,
    source_tree,
    validate_controls,
    validate_source_controls,
)


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def cpu_time(kind: int) -> float:
    usage = resource.getrusage(kind)
    return usage.ru_utime + usage.ru_stime


def load_executor(root: Path):
    path = root / "scripts" / "hepta_ci_exec.py"
    raw = regular_bytes(path, 64 * 1024)
    require(
        git_blob(raw) == HEPTA_EXEC_GIT_BLOB, "original process owner identity differs"
    )
    name = "_hepta_oauth_fixture_original_exec"
    require(name not in sys.modules, "process owner module already loaded")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None, "cannot bind original process owner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(
            compile(raw, str(path), "exec", dont_inherit=True, optimize=0),
            module.__dict__,
        )
    except BaseException:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        raise
    return module


class Build:
    def __init__(self, root: Path, output: Path, started: float):
        self.root = root
        self.output = output
        self.started = started
        self.command_deadline = started + CAPS["command_seconds"]
        self.deadline = started + CAPS["whole_seconds"]
        self.commands = []
        self.executor = load_executor(root)

    def run(self, label: str, command: list[str], cwd: Path, cap: float) -> bytes:
        require(
            time.monotonic() < self.command_deadline, "fixture command deadline reached"
        )
        require(
            all(row["label"] != label for row in self.commands),
            "duplicate command label",
        )
        log = self.output / (label + ".log")
        row = {"label": label, "command": command, "cwd": str(cwd), "cap_seconds": cap}
        self.commands.append(row)
        previous = Path.cwd()
        began = time.monotonic()
        self_cpu = cpu_time(resource.RUSAGE_SELF)
        child_cpu = cpu_time(resource.RUSAGE_CHILDREN)
        allowance = min(cap, self.command_deadline - began)
        try:
            os.chdir(cwd)
            execution = self.executor.execute_logged(
                command,
                log,
                maximum_bytes=16 * 1024 * 1024,
                timeout_seconds=allowance,
            )
            row["execution"] = execution
        except BaseException as error:
            row["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            os.chdir(previous)
            row["elapsed_seconds"] = time.monotonic() - began
            row["self_cpu_seconds"] = cpu_time(resource.RUSAGE_SELF) - self_cpu
            row["child_cpu_seconds"] = cpu_time(resource.RUSAGE_CHILDREN) - child_cpu
            if log.exists():
                raw = regular_bytes(log, 16 * 1024 * 1024)
                row["log"] = {
                    "path": log.name,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
        require(
            execution["returncode"] == 0
            and not execution["timed_out"]
            and not execution["output_limit_exceeded"]
            and time.monotonic() <= self.command_deadline
            and row["elapsed_seconds"] <= allowance,
            f"fixture command failed or exceeded its bound: {label}",
        )
        return raw

    def identity(self, label: str) -> dict:
        head = (
            self.run(label, ["git", "rev-parse", "HEAD"], self.root, 5)
            .decode("ascii")
            .strip()
        )
        raw = self.run(
            label + "-commit", ["git", "cat-file", "-p", "HEAD"], self.root, 5
        )
        identity = commit_identity(raw)
        require(identity["commit"] == head, "Hepta raw commit identity differs")
        status = self.run(
            label + "-status",
            ["git", "status", "--porcelain", "--untracked-files=no"],
            self.root,
            5,
        )
        require(not status, "Hepta tracked worktree is not clean")
        return identity


def snapshot_source(directory: Path, expected: dict) -> dict:
    require(
        directory.is_dir() and not directory.is_symlink(),
        "upstream source directory is invalid",
    )
    found = set()
    for root, directories, names in os.walk(directory):
        relative = Path(root).relative_to(directory)
        if relative == Path("."):
            directories[:] = [
                name
                for name in directories
                if name not in {".git", "node_modules", "dist"}
            ]
        for name in directories:
            require(not (Path(root) / name).is_symlink(), "symlink source directory")
        for name in names:
            found.add((relative / name).as_posix())
    require(found == set(expected), "upstream source paths missing or extra")
    result = {}
    for relative, leaf in sorted(expected.items()):
        path = directory / relative
        raw = regular_bytes(path, 2 * 1024 * 1024)
        require(
            not path.stat().st_mode & 0o111, "upstream source executable mode changed"
        )
        actual = {"bytes": len(raw), "git_blob": git_blob(raw)}
        require(actual == leaf, f"upstream source bytes differ: {relative}")
        result[relative] = actual
    return result


def prepare(build: Build, manifest: dict, manifest_sha: str, record: dict) -> None:
    root, output = build.root, build.output
    record["source_before"] = build.identity("hepta-before")
    expected = record["original_build"]["identity"]
    require(
        record["source_before"]
        == {
            "commit": expected["source_head"],
            "tree": expected["source_tree"],
            "parents": expected["source_parents"],
            "dirty": False,
        },
        "raw source commit differs from this original provider/build identity",
    )
    record["github"] = {
        key: value for key, value in os.environ.items() if key.startswith("GITHUB_")
    }
    node = (
        build.run("version-node", ["node", "--version"], root, 5)
        .decode("ascii")
        .strip()
    )
    npm = (
        build.run("version-npm", ["npm", "--version"], root, 5).decode("ascii").strip()
    )
    require(
        re.fullmatch(r"v22\.[0-9]+\.[0-9]+", node) is not None
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", npm) is not None,
        "Node/npm observation is outside the existing Node 22 SDK environment",
    )
    require(
        sys.version_info >= (3, 11), "fixture controls require Python 3.11 or newer"
    )
    record["tools"] = {
        "node": node,
        "npm": npm,
        "python": sys.version,
        "python_executable": sys.executable,
    }
    source_controls = build.run(
        "source-controls",
        [
            sys.executable,
            "-m",
            "unittest",
            "-v",
            "test_oauth_authorization_origins.AuthorizationOriginSidebandTests",
            "test_conformance_fixture.FixtureReceiptTests",
            "test_conformance_fixture.OriginalCandidateIdentityTests",
        ],
        Path(__file__).parent,
        10,
    )
    validate_source_controls(source_controls)
    record["manifest_sha256"] = manifest_sha
    patch = regular_bytes(Path(__file__).parent / manifest["patch"]["path"], 128 * 1024)
    require(
        len(patch) == manifest["patch"]["bytes"]
        and hashlib.sha256(patch).hexdigest() == manifest["patch"]["sha256"],
        "reviewed fixture patch identity differs",
    )
    patch_path = output / "reviewed-source.patch"
    patch_path.write_bytes(patch)
    upstream = output / "upstream"
    upstream.mkdir(mode=0o700)
    build.run("upstream-init", ["git", "init", "--quiet"], upstream, 5)
    build.run(
        "upstream-fetch",
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            "core.hooksPath=/dev/null",
            "fetch",
            "--no-tags",
            "--depth=1",
            "https://github.com/modelcontextprotocol/conformance.git",
            UPSTREAM_COMMIT,
        ],
        upstream,
        60,
    )
    build.run(
        "upstream-checkout",
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "checkout",
            "--detach",
            "--quiet",
            "FETCH_HEAD",
        ],
        upstream,
        10,
    )
    head = (
        build.run("upstream-head", ["git", "rev-parse", "HEAD"], upstream, 5)
        .decode("ascii")
        .strip()
    )
    tree = (
        build.run("upstream-tree", ["git", "rev-parse", "HEAD^{tree}"], upstream, 5)
        .decode("ascii")
        .strip()
    )
    require(
        head == UPSTREAM_COMMIT and tree == UPSTREAM_TREE,
        "fetched upstream identity differs",
    )
    before = snapshot_source(upstream, manifest["source_files"])
    write_json(output / "upstream-source-before.json", before)
    build.run(
        "patch-check",
        ["git", "apply", "--check", "--index", str(patch_path)],
        upstream,
        5,
    )
    build.run("patch-apply", ["git", "apply", "--index", str(patch_path)], upstream, 5)
    after = snapshot_source(upstream, manifest["postimage_files"])
    require(
        source_tree(after) == manifest["fork_source_tree"],
        "physical fork source tree differs",
    )
    write_json(output / "fork-source-after.json", after)
    retained = output / "reviewed-sources"
    for relative in PATCH_PATHS:
        target = retained / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(regular_bytes(upstream / relative, 2 * 1024 * 1024))
    record["dependency_install"] = "npm ci --ignore-scripts --no-audit --no-fund"
    build.run(
        "install",
        ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
        upstream,
        180,
    )
    report_path = output / "controls.json"
    require(not report_path.exists(), "fixture controls output already exists")
    build.run(
        "controls",
        [
            "npm",
            "run",
            "test",
            "--",
            manifest["controls"]["file"],
            "--reporter=json",
            "--outputFile=" + str(report_path),
        ],
        upstream,
        45,
    )
    controls, control_sha = read_json(report_path)
    record["controls"] = validate_controls(
        controls,
        upstream / manifest["controls"]["file"],
        manifest["controls"]["titles"],
    )
    record["controls_sha256"] = control_sha
    build.run("build", ["npm", "run", "build"], upstream, 90)
    require(
        snapshot_source(upstream, manifest["postimage_files"]) == after,
        "fixture source changed during install, controls or build",
    )
    record["dist_files"] = snapshot_dist(upstream / "dist")
    record["fork_source_tree"] = manifest["fork_source_tree"]
    record["upstream"] = manifest["upstream"]
    record["source_after"] = build.identity("hepta-after")
    require(
        record["source_after"] == record["source_before"],
        "Hepta source identity changed during fixture build",
    )
    record["cli"] = str(upstream / "dist" / "index.js")
    record["source_files_verified"] = len(after)
    record["dependency_identity_scope"] = (
        "Exact upstream package-lock plus successful npm ci; runtime dependency files are not individually qualified by this receipt."
    )


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sdk-build-boundary", choices=("before", "after"))
    parser.add_argument("--original-codex", type=Path)
    parser.add_argument("--original-code-mode-host", type=Path)
    parser.add_argument("--build-receipt", type=Path)
    parser.add_argument(
        "--verify-sdk-use", choices=("before-reviewer", "after-reviewer")
    )
    parser.add_argument("--fixture-receipt", type=Path)
    parser.add_argument("--codex-binary", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    manifest_path = Path(__file__).parent / "oauth-origin-fixture.json"
    if args.sdk_build_boundary is not None:
        require(
            args.output is not None and args.verify_sdk_use is None,
            "one SDK build boundary required",
        )
        originals = None
        if args.sdk_build_boundary == "after":
            require(
                args.original_codex is not None
                and args.original_code_mode_host is not None,
                "both original Bazel outputs are required",
            )
            originals = {
                "codex": args.original_codex,
                "code_mode_host": args.original_code_mode_host,
            }
        record_sdk_build_boundary(
            args.output.expanduser().resolve(), manifest_path, root, originals
        )
        return 0
    if args.verify_sdk_use is not None:
        require(
            args.fixture_receipt is not None and args.codex_binary is not None,
            "original reviewer fixture and binary are required",
        )
        receipt = args.fixture_receipt.expanduser().resolve()
        verify_receipt(
            receipt,
            manifest_path,
            receipt.parent / "upstream" / "dist" / "index.js",
            None,
            args.codex_binary,
            args.verify_sdk_use,
        )
        return 0
    require(
        args.output is not None and args.build_receipt is not None,
        "original build receipt is required",
    )
    output = args.output.expanduser().resolve()
    require(os.name == "posix", "the fixture build owner requires POSIX")
    require(
        not output.exists() and not output.is_relative_to(root),
        "fixture output must be fresh and outside the Hepta source",
    )
    output.mkdir(parents=True, mode=0o700)
    record = {
        "schema": "hepta-oauth-origin-fixture-build-v2",
        "kind": "reviewed-upstream-fixture-fork",
        "status": "running",
        "caps": CAPS,
        "conformance_pass": False,
    }
    old_env = dict(os.environ)
    github = {key: value for key, value in old_env.items() if key.startswith("GITHUB_")}
    build = None
    manifest = None
    identity_after_checked = False
    exit_code = 1
    try:
        for key in list(os.environ):
            if (
                key.startswith("GIT_")
                or key.upper() == "MCP_CONFORMANCE_AUTHORIZATION_ORIGINS"
            ):
                del os.environ[key]
        os.environ.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "npm_config_cache": str(output / "npm-cache"),
                "npm_config_audit": "false",
                "npm_config_fund": "false",
            }
        )
        manifest, manifest_sha = load_manifest(
            Path(__file__).parent / "oauth-origin-fixture.json"
        )
        build = Build(root, output, started)
        before_identity = output / "identity-before"
        before_identity.mkdir()
        record["original_build"] = inspect_original_build(
            args.build_receipt,
            manifest,
            root,
            before_identity,
            min(build.command_deadline, time.monotonic() + 20),
            FIXTURE_STEP,
        )
        prepare(build, manifest, manifest_sha, record)
        after_identity = output / "identity-after"
        after_identity.mkdir()
        record["original_build_after"] = inspect_original_build(
            args.build_receipt,
            manifest,
            root,
            after_identity,
            min(build.command_deadline, time.monotonic() + 20),
            FIXTURE_STEP,
        )
        require(
            record["original_build_after"] == record["original_build"],
            "source, original build or actual binary changed during fixture preparation",
        )
        identity_after_checked = True
        require(
            time.monotonic() <= build.command_deadline,
            "fixture acceptance exceeded the command deadline",
        )
        record["status"] = "passed"
        exit_code = 0
    except BaseException as error:
        record["status"] = "failed"
        record["error"] = f"{type(error).__name__}: {error}"
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        if build is not None and manifest is not None and not identity_after_checked:
            try:
                failure_identity = output / "identity-after-failure"
                failure_identity.mkdir()
                record["original_build_after_failure"] = inspect_original_build(
                    args.build_receipt,
                    manifest,
                    root,
                    failure_identity,
                    min(build.deadline, time.monotonic() + 20),
                    FIXTURE_STEP,
                )
                require(
                    record.get("original_build")
                    == record["original_build_after_failure"],
                    "original identity changed on failure",
                )
            except BaseException as identity_error:
                record["identity_retention_error"] = repr(identity_error)
                record["status"] = "failed"
                exit_code = 1
        os.environ.clear()
        os.environ.update(old_env)
        require(
            {
                key: value
                for key, value in os.environ.items()
                if key.startswith("GITHUB_")
            }
            == github,
            "GitHub identity environment changed",
        )
        record["commands"] = [] if build is None else build.commands
        record["elapsed_seconds_before_final_io"] = time.monotonic() - started
        record["within_budget_before_final_io"] = (
            record["elapsed_seconds_before_final_io"] <= CAPS["whole_seconds"]
        )
        record["exit_code_before_final_io"] = exit_code
        if not record["within_budget_before_final_io"]:
            record["status"] = "failed"
            exit_code = 1
        write_json(output / "RESULT.json", record)
    print(
        json.dumps(
            {"status": record["status"], "receipt": str(output / "RESULT.json")}
        ),
        flush=True,
    )
    return exit_code if time.monotonic() - started <= CAPS["whole_seconds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
