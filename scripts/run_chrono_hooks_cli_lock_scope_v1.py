"""Generate a review-only pair of locks on one exact, complete CI source.

This file is a source candidate. No local execution is authorized by its presence.
The approved input file must be completed by the source owner before publication.
"""

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import stat
import sys
import time
import tomllib


OWNER_SHA = "ccabe2e8066c01a612a378d42cd7580ab183870b59921442a0d208b5ac528cba"
SPEC_PATH = "scripts/hepta_chrono_hooks_cli_lock_inputs_v1.json"
LOCKS = {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}
TARGETS = {
    "cookie": "0.18.3",
    "url": "2.5.9",
    "rmcp": "3.9.0",
    "sqlx": "0.9.1",
    "libsqlite3-sys": "0.39.1",
    "rusqlite": "0.41.0",
}
CONTRACT_PATH = "scripts/hepta_chrono_hooks_cli_lock_contract_v1.py"
CONTRACT_TEST_PATH = "scripts/test_hepta_chrono_hooks_cli_lock_contract_v1.py"
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
REPO = "TrillionniumFoundation/hepta-private-ci"
TOOL_CAP = 180.0
RESOLVER_CAP = 300.0
STDOUT_CAP_BYTES = 64 * 1024 * 1024
EVIDENCE_ACCEPTANCE_CAP_BYTES = 512 * 1024 * 1024
MIN_FREE_BYTES = 4 * 1024 * 1024 * 1024
BAZEL_ASSET = {
    "id": 619248138,
    "name": "bazel-9.3.0-linux-x86_64",
    "url": "https://github.com/bazelbuild/bazel/releases/download/9.3.0/bazel-9.3.0-linux-x86_64",
    "bytes": 77023347,
    "sha256": "d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8",
    "release_json_sha256": "d0bd5b73346d1ebedf9ab28a37a180ce3bad2954f1718a396c931c23ca57d348",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_value(raw):
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def put(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"file": path.name, "bytes": len(raw), "sha256": digest(raw)}


def raw_hash(path):
    value = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": value.hexdigest()}


class Scope:
    def __init__(self, source, stage, phase, start, cap):
        self.source, self.stage, self.phase = source, stage, phase
        self.evidence = stage / "evidence"
        self.start, self.deadline = start, start + cap
        self.commands = []
        self.counter = 0
        self.self_cpu = resource.getrusage(resource.RUSAGE_SELF)
        self.child_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        owner_path = source / "scripts/hepta_ci_exec.py"
        require(
            digest(owner_path.read_bytes()) == OWNER_SHA,
            "original command owner changed",
        )
        spec = importlib.util.spec_from_file_location(
            "original_chrono_hooks_cli_lock_command_owner", owner_path
        )
        self.owner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.owner)

    def remaining(self, reserve=10.0):
        left = self.deadline - time.monotonic() - reserve
        require(left > 0, "shared scope deadline leaves no command allowance")
        return left

    def storage_observation(self):
        total = 0
        for path in self.evidence.rglob("*"):
            require(not path.is_symlink(), "evidence must not follow a symbolic link")
            if path.is_file():
                total += path.stat().st_size
        return {
            "evidence_bytes": total,
            "free_bytes": shutil.disk_usage(self.stage).free,
        }

    def storage_acceptance(self):
        observed = self.storage_observation()
        require(
            observed["free_bytes"] >= MIN_FREE_BYTES,
            "isolated runner disk headroom is insufficient",
        )
        require(
            observed["evidence_bytes"] <= EVIDENCE_ACCEPTANCE_CAP_BYTES,
            "original evidence exceeds the reviewable artifact acceptance bound",
        )
        return observed

    def run(self, label, argv, cwd, limit, environment=None):
        self.counter += 1
        prefix = f"{self.phase}-{self.counter:02d}-{label}"
        stdout = self.evidence / (prefix + ".stdout")
        stderr = self.evidence / (prefix + ".stderr")
        owner_log = stdout
        require(
            not stdout.exists() and not stderr.exists(), "command output already exists"
        )
        storage_before = self.storage_acceptance()
        # exec retains the owner's direct-child identity and session. There is
        # no nested supervisor or independent session between this and the tool.
        wrapper = [
            "/bin/sh",
            "-c",
            'lock_stderr=$1; shift; exec "$@" 2>"$lock_stderr"',
            "chrono-hooks-cli-lock-output",
            str(stderr),
            *argv,
        ]
        old_cwd = Path.cwd()
        changed = dict(environment or {})
        prior = {key: os.environ.get(key) for key in changed}
        before = time.monotonic()
        row = {
            "label": label,
            "argv": argv,
            "cwd": str(cwd),
            "stdout": stdout.name,
            "stderr": stderr.name,
            "owner_log": owner_log.name,
            "storage_before": storage_before,
            "environment_overrides": changed,
        }
        self.commands.append(row)
        try:
            os.chdir(cwd)
            os.environ.update(changed)
            # The unchanged owner retains and bounds raw stdout. Only its
            # console copy is silenced; the actual metadata/log remains in
            # owner_log. stderr is separate original output, checked after
            # the command rather than claimed to have a real-time byte bound.
            with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet):
                row["execution"] = self.owner.execute_logged(
                    wrapper,
                    owner_log,
                    maximum_bytes=STDOUT_CAP_BYTES,
                    timeout_seconds=min(limit, self.remaining()) - 1.0,
                )
        except BaseException as error:
            row["owner_error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            os.chdir(old_cwd)
            for key, value in prior.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            row["elapsed_seconds"] = time.monotonic() - before
            row["files"] = {p.name: raw_hash(p) for p in (stdout, stderr) if p.exists()}
            row["storage_after"] = self.storage_observation()
            put(self.evidence / (prefix + ".json"), row)
        execution = row["execution"]
        require(
            execution["returncode"] == 0
            and not execution["timed_out"]
            and not execution["output_limit_exceeded"],
            "actual command failed: " + label,
        )
        require(
            stdout.stat().st_size <= STDOUT_CAP_BYTES,
            "command stdout exceeds retained bound",
        )
        self.storage_acceptance()
        return stdout, stderr

    def read_git(self, root, *args):
        path, _ = self.run(
            "git-read",
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            root,
            8,
            {"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
        )
        return path.read_bytes()

    def receipt(self):
        own = resource.getrusage(resource.RUSAGE_SELF)
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        return {
            "elapsed_seconds": time.monotonic() - self.start,
            "current_process_cpu_seconds": own.ru_utime
            + own.ru_stime
            - self.self_cpu.ru_utime
            - self.self_cpu.ru_stime,
            "current_process_reaped_children_cpu_seconds": child.ru_utime
            + child.ru_stime
            - self.child_cpu.ru_utime
            - self.child_cpu.ru_stime,
            "commands": self.commands,
        }


def load_spec(scope):
    spec = json_value((scope.source / SPEC_PATH).read_bytes())
    require(
        spec["schema"] == "hepta.chrono-hooks-cli-lock-approved-inputs.v1"
        and spec["activated"] is True,
        "final source owner has not activated a complete approved input",
    )
    require(
        os.environ["GITHUB_REPOSITORY"] == REPO
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1",
        "wrong repository or non-original run attempt",
    )
    require(
        os.environ["LOCK_PR_AUTHOR"] == "ProfHepta"
        and os.environ["LOCK_PR_DRAFT"] == "true"
        and os.environ["LOCK_HEAD_REPO"] == REPO
        and os.environ["LOCK_EVENT_ACTION"] == "opened"
        and os.environ["LOCK_HEAD_BRANCH"] == spec["branch"],
        "not the single owned Draft opening",
    )
    head = os.environ["LOCK_EXPECTED_HEAD"]
    require(re.fullmatch(r"[0-9a-f]{40}", head), "head identity missing")
    job_start = json_value((scope.evidence / "job-start.json").read_bytes())
    require(
        job_start["head"] == head
        and job_start["run_id"] == os.environ["GITHUB_RUN_ID"]
        and job_start["run_attempt"] == "1",
        "unique job scope identity differs",
    )
    require(
        scope.read_git(scope.source, "rev-parse", "HEAD").decode().strip() == head,
        "checkout is not the exact event head",
    )
    source_git = scope.source / ".git"
    require(
        source_git.is_dir() and not source_git.is_symlink(),
        "original checkout requires its own Git directory",
    )
    shallow_path = source_git / "shallow"
    require(
        shallow_path.is_file() and not shallow_path.is_symlink(),
        "exact depth-one boundary is absent",
    )
    shallow = shallow_path.read_bytes()
    require(
        shallow == (head + "\n").encode("ascii"),
        "source shallow boundary differs from the one exact event commit",
    )
    commit = scope.read_git(scope.source, "cat-file", "-p", head)
    headers = commit.split(b"\n\n", 1)[0].decode().splitlines()
    require(
        [row[7:] for row in headers if row.startswith("parent ")] == [spec["parent"]],
        "combined source parent differs",
    )
    require(
        not scope.read_git(
            scope.source, "status", "--porcelain=v1", "--untracked-files=all"
        ),
        "original checkout is not clean",
    )
    require(
        all(
            row.startswith(b"H ")
            for row in scope.read_git(scope.source, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "sparse or assumed-unchanged input is not a complete checkout",
    )
    rows = spec["reviewed_sources"]
    require(
        rows and len({r["path"] for r in rows}) == len(rows),
        "reviewed source roster is incomplete",
    )
    required = LOCKS | {
        "scripts/hepta_ci_exec.py",
        "justfile",
        "scripts/just-shell.py",
        ".bazelrc",
        ".bazelversion",
        ".gitattributes",
        "MODULE.bazel",
        "codex-rs/Cargo.toml",
        "codex-rs/deny.toml",
        "codex-rs/rust-toolchain.toml",
        "scripts/run_chrono_hooks_cli_lock_scope_v1.py",
        ".github/workflows/hepta-chrono-hooks-cli-lock-candidate-v1.yml",
        CONTRACT_PATH,
        CONTRACT_TEST_PATH,
    }
    require(
        required <= {r["path"] for r in rows},
        "required original policies/locks are unpinned",
    )
    for row in rows:
        rel = Path(row["path"])
        require(
            not rel.is_absolute()
            and ".." not in rel.parts
            and row["mode"] in ("100644", "100755"),
            "invalid reviewed source path/mode",
        )
        path = scope.source / rel
        require(
            path.is_file() and not path.is_symlink(),
            "reviewed source is not a regular file",
        )
        require(
            bool(path.stat().st_mode & 0o111) == (row["mode"] == "100755"),
            "reviewed source executable mode differs: " + str(rel),
        )
        require(
            raw_hash(path)["sha256"] == row["sha256"],
            "reviewed source differs: " + str(rel),
        )
    require(
        (scope.source / ".bazelversion").read_text().strip() == "9.3.0",
        "Bazel selection changed",
    )
    require(
        tomllib.loads((scope.source / "codex-rs/rust-toolchain.toml").read_text())[
            "toolchain"
        ]["channel"]
        == "1.96.0",
        "Rust selection changed",
    )
    require(
        spec["targets"] == TARGETS
        and spec["resolver_cap_seconds"] == RESOLVER_CAP
        and spec["tool_preparation_cap_seconds"] == TOOL_CAP,
        "reviewed budgets or targets changed",
    )
    return spec, {
        "head": head,
        "tree": next(row[5:] for row in headers if row.startswith("tree ")),
        "parent": spec["parent"],
        "spec_sha256": digest((scope.source / SPEC_PATH).read_bytes()),
        "shallow_sha256": digest(shallow),
    }


def tool_file(path):
    resolved = path.resolve(strict=True)
    require(
        resolved.is_file() and os.access(resolved, os.X_OK),
        "tool is not an executable file",
    )
    return {"path": str(path), "resolved_path": str(resolved), **raw_hash(resolved)}


def original_rc_only(source):
    for path in (
        Path("/etc/bazel.bazelrc"),
        Path.home() / ".bazelrc",
        source / "user.bazelrc",
    ):
        require(
            not path.exists() and not path.is_symlink(),
            "unreviewed Bazel rc exists: " + str(path),
        )


def prepare_start(scope):
    spec, identity = load_spec(scope)
    original_rc_only(scope.source)
    put(
        scope.evidence / "tool-start.json",
        {
            "schema": "hepta.chrono-hooks-cli-lock-tool-start.v1",
            "monotonic_seconds": scope.start,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "source": identity,
            "spec_sha256": identity["spec_sha256"],
            "scope_cap_seconds": TOOL_CAP,
            "installation_logs": "Complete original GitHub job logs for the pinned Rust and just action steps",
            "old_host_tool_budget_reset": False,
        },
    )
    return {"status": "TOOL_PREPARATION_STARTED_ONLY", "source": identity}


def prepare_finish(scope):
    spec, identity = load_spec(scope)
    begin = json_value((scope.evidence / "tool-start.json").read_bytes())
    require(
        begin["boot_id"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and begin["source"] == identity,
        "tool preparation source/host changed",
    )
    outcomes = json_value(os.environ["LOCK_TOOL_STEPS"])
    require(
        all(
            outcomes.get(name, {}).get("outcome") == "success"
            for name in ("rust", "just")
        ),
        "an original tool installation step did not succeed",
    )
    scope.remaining()
    original_rc_only(scope.source)
    tools_dir = scope.stage / "tools"
    tools_dir.mkdir(exist_ok=False)
    asset = spec["bazel_asset"]
    require(
        asset == BAZEL_ASSET,
        "official Linux Bazel asset is not the reviewed exact release",
    )
    binary = tools_dir / "bazel-9.3.0-linux-x86_64"
    scope.run(
        "download-bazel-once",
        [
            "curl",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--tlsv1.2",
            "--location",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            str(max(1, int(min(50, scope.remaining()) - 1))),
            "--output",
            str(binary),
            asset["url"],
        ],
        scope.source,
        50,
    )
    actual = raw_hash(binary)
    require(
        actual == {"bytes": asset["bytes"], "sha256": asset["sha256"]},
        "official Bazel payload mismatch",
    )
    with binary.open("rb") as stream:
        header = stream.read(20)
    require(
        header[:6] == b"\x7fELF\x02\x01"
        and int.from_bytes(header[18:20], "little") == 62,
        "downloaded tool is not the expected Linux x86-64 executable",
    )
    binary.chmod(0o700)
    tools = {
        "bazel": tool_file(binary),
        "cargo_launcher": tool_file(Path(shutil.which("cargo") or "")),
        "rustup": tool_file(Path(shutil.which("rustup") or "")),
        "just": tool_file(Path(shutil.which("just") or "")),
        "python": tool_file(Path(sys.executable)),
        "shell": tool_file(Path("/bin/sh")),
        "git": tool_file(Path(shutil.which("git") or "")),
    }
    for name in ("cargo", "rustc"):
        out, _ = scope.run(
            "locate-" + name,
            [tools["rustup"]["path"], "which", "--toolchain", "1.96.0", name],
            scope.source,
            5,
        )
        lines = out.read_text().splitlines()
        require(
            len(lines) == 1 and Path(lines[0]).is_absolute(),
            "ambiguous installed Rust tool",
        )
        tools[name] = tool_file(Path(lines[0]))
    versions = {}
    for name, argv, expected in (
        ("cargo", [tools["cargo"]["path"], "--version"], "cargo 1.96.0 "),
        ("rustc", [tools["rustc"]["path"], "--version"], "rustc 1.96.0 "),
        ("just", [tools["just"]["path"], "--version"], "just 1.51.0"),
        (
            "bazel",
            [
                str(binary),
                "--batch",
                "--output_base=" + str(scope.stage / "bazel-version-only"),
                "version",
                "--gnu_format",
            ],
            "bazel 9.3.0",
        ),
    ):
        out, err = scope.run("version-" + name, argv, scope.source, 8)
        lines = out.read_text().splitlines()
        correct = (
            expected in lines
            if name in ("just", "bazel")
            else any(line.startswith(expected) for line in lines)
        )
        require(correct, "actual tool version differs: " + name)
        versions[name] = {"stdout": out.name, "stderr": err.name}
    require(
        not scope.read_git(
            scope.source, "status", "--porcelain=v1", "--untracked-files=all"
        ),
        "tool preparation changed the original checkout",
    )
    require(time.monotonic() <= scope.deadline, "tool preparation cap exceeded")
    result = {
        "status": "TOOLS_PREPARED_ONLY",
        "source": identity,
        "actual_tools": tools,
        "versions": versions,
        "official_bazel_asset": asset,
        "tool_installation_steps": outcomes,
        "path_environment": os.environ["PATH"],
        "full_preparation_cpu_seconds": None,
        "cpu_reason": "Rust/just action processes belong to earlier CI steps; only this process/children CPU is available",
        "old_host_tool_attempts_preserved_separately": True,
        "resolver_not_started": True,
    }
    put(scope.evidence / "tool-preparation.json", result)
    return result


def source_snapshot(scope, root, tree):
    entries = scope.read_git(root, "ls-tree", "-r", "-z", tree).split(b"\0")
    snapshot = {}
    for entry in entries:
        if not entry:
            continue
        scope.remaining(reserve=1)
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, expected = header.decode().split()
        rel = raw_path.decode("utf-8")
        require(
            kind == "blob"
            and mode in ("100644", "100755", "120000")
            and rel not in snapshot,
            "unsupported or repeated tree entry",
        )
        path = root / rel
        meta = path.lstat()
        if mode == "120000":
            require(stat.S_ISLNK(meta.st_mode), "tracked symlink changed kind")
            raw = os.fsencode(os.readlink(path))
            blob_hash = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            sha, size = digest(raw), len(raw)
        else:
            require(
                stat.S_ISREG(meta.st_mode)
                and bool(meta.st_mode & 0o111) == (mode == "100755"),
                "tracked regular file changed kind/mode",
            )
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                before = os.fstat(fd)
                blob_state = hashlib.sha1(
                    b"blob " + str(before.st_size).encode() + b"\0"
                )
                sha_state, size = hashlib.sha256(), 0
                while chunk := os.read(fd, 1024 * 1024):
                    scope.remaining(reserve=1)
                    sha_state.update(chunk)
                    blob_state.update(chunk)
                    size += len(chunk)
                after = os.fstat(fd)
                same_path = path.lstat()
                key = lambda value: (
                    value.st_dev,
                    value.st_ino,
                    value.st_mode,
                    value.st_size,
                    value.st_mtime_ns,
                    value.st_ctime_ns,
                )
                require(
                    key(before) == key(after) == key(same_path)
                    and size == before.st_size,
                    "tracked source changed during descriptor read",
                )
                blob_hash, sha = blob_state.hexdigest(), sha_state.hexdigest()
            finally:
                os.close(fd)
        snapshot[rel] = {
            "mode": mode,
            "bytes": size,
            "sha256": sha,
            "git_blob": blob_hash,
            "expected_git_blob": expected,
        }
    return snapshot


def require_tree(snapshot, label):
    require(
        snapshot
        and all(
            row["git_blob"] == row["expected_git_blob"] for row in snapshot.values()
        ),
        label + " is not the complete exact source tree",
    )


def parse_lock(path):
    value = tomllib.loads(path.read_text())
    require(value.get("package"), "actual Cargo lock is empty")
    return value


def lock_targets(lock):
    packages = lock["package"]
    for name, version in TARGETS.items():
        rows = [row for row in packages if row["name"] == name]
        require(
            len(rows) == 1 and rows[0]["version"] == version,
            "reviewed target or vulnerable duplicate differs: " + name,
        )
        require(
            rows[0].get("source") == REGISTRY
            and re.fullmatch(r"[0-9a-f]{64}", rows[0].get("checksum", "")),
            "target registry/checksum differs: " + name,
        )
    for row in packages:
        if row["name"] in (
            "sqlx-core",
            "sqlx-sqlite",
            "sqlx-macros",
            "sqlx-macros-core",
            "sqlx-mysql",
            "sqlx-postgres",
        ):
            require(row["version"] == "0.9.1", "SQLx family is inconsistent")


def graph_readback(metadata, spec, work, old_lock, new_lock):
    require(
        metadata.get("version") == 1
        and metadata.get("workspace_members")
        and metadata.get("packages")
        and metadata.get("resolve", {}).get("nodes"),
        "actual all-feature Cargo graph is incomplete",
    )
    packages = {row["id"]: row for row in metadata["packages"]}
    nodes = {row["id"]: row for row in metadata["resolve"]["nodes"]}
    require(
        len(packages) == len(metadata["packages"])
        and len(nodes) == len(metadata["resolve"]["nodes"]),
        "Cargo graph has repeated identities",
    )
    members = []
    for identity in metadata["workspace_members"]:
        require(
            identity in packages and identity in nodes,
            "workspace member has no actual resolve node",
        )
        members.append(str(Path(packages[identity]["manifest_path"]).relative_to(work)))
    require(
        sorted(members) == spec["workspace_member_manifests"],
        "combined workspace membership differs",
    )
    sqlite = [p for p in packages.values() if p.get("links") == "sqlite3"]
    require(
        len(sqlite) == 1
        and sqlite[0]["name"] == "libsqlite3-sys"
        and sqlite[0]["version"] == "0.39.1",
        "SQLite links owner differs",
    )
    matrix = [p for p in packages.values() if p["name"] == "matrix-sdk-sqlite"]
    require(
        len(matrix) == 1
        and matrix[0]["version"] == "0.19.1"
        and matrix[0]["source"] is None,
        "reviewed Matrix local manifest patch is absent",
    )
    chrono_ids = {p["id"] for p in packages.values() if p["name"] == "chrono"}
    require(
        chrono_ids,
        "known mandatory chrono disappeared; explicit source/feature review is required",
    )
    reverse = [
        {"dependent": identity, "dependency": edge}
        for identity, node in nodes.items()
        for edge in node["deps"]
        if edge["pkg"] in chrono_ids
    ]

    def package_map(lock):
        return {(p["name"], p["version"], p.get("source")): p for p in lock["package"]}

    before, after = package_map(old_lock), package_map(new_lock)
    changes = []
    for identity in sorted(
        before.keys() | after.keys(), key=lambda key: (key[0], key[1], key[2] or "")
    ):
        if before.get(identity) != after.get(identity):
            changes.append(
                {
                    "name": identity[0],
                    "version": identity[1],
                    "source": identity[2],
                    "before": before.get(identity),
                    "after": after.get(identity),
                    "current_graph_nodes": [
                        nodes[key]
                        for key, pkg in packages.items()
                        if (pkg["name"], pkg["version"], pkg["source"]) == identity
                        and key in nodes
                    ],
                }
            )
    return {
        "workspace_member_manifests": sorted(members),
        "package_changes": changes,
        "chrono_reverse_edges": reverse,
        "chrono_unmaintained_unresolved": bool(chrono_ids),
        "every_additional_package_change_requires_root_review": True,
        "full_raw_graph_retained": True,
        "compatibility_or_advisory_qualified": False,
    }


def generate(scope, state):
    spec, identity = load_spec(scope)
    prepared = json_value((scope.evidence / "tool-preparation.json").read_bytes())
    prepared_terminal = json_value(
        (scope.evidence / "prepare-finish.RESULT.json").read_bytes()
    )
    require(
        prepared["status"] == "TOOLS_PREPARED_ONLY" and prepared["source"] == identity,
        "actual tool preparation does not belong to this exact candidate",
    )
    require(
        prepared_terminal["status"] == "TOOLS_PREPARED_ONLY"
        and prepared_terminal["elapsed_seconds"] <= TOOL_CAP
        and prepared_terminal["actual_tools"] == prepared["actual_tools"],
        "tool preparation has no successful original terminal receipt",
    )
    tools = prepared["actual_tools"]
    require(
        os.environ["PATH"] == prepared["path_environment"],
        "prepared tool search path changed",
    )
    for tool in tools.values():
        require(tool_file(Path(tool["path"])) == tool, "prepared tool changed")
    original_rc_only(scope.source)
    before = source_snapshot(scope, scope.source, identity["tree"])
    require_tree(before, "original checkout")
    put(scope.evidence / "source-before.json", before)
    state.update({"source": identity, "before": before})
    work = scope.stage / "work"
    local_git_environment = {"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}
    scope.run(
        "init-isolated-copy",
        [
            tools["git"]["path"],
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "init",
            "--quiet",
            "--template=",
            "--object-format=sha1",
            str(work),
        ],
        scope.stage,
        5,
        local_git_environment,
    )
    # A shallow source makes `git clone --shared` leave its local shared-object
    # path and invoke transport instead. Set up the owned metadata explicitly:
    # no remote, upload-pack, fetch, history deepening or source object writes.
    source_objects = scope.source / ".git/objects"
    require(
        source_objects.is_dir() and not source_objects.is_symlink(),
        "original Git objects directory is not local",
    )
    shared_objects = (str(source_objects) + "\n").encode()
    shallow = (scope.source / ".git/shallow").read_bytes()
    require(
        digest(shallow) == identity["shallow_sha256"], "source shallow boundary changed"
    )
    for path, raw in (
        (work / ".git/objects/info/alternates", shared_objects),
        (work / ".git/shallow", shallow),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    copy_config = (work / ".git/config").read_bytes()
    put(
        scope.evidence / "isolated-git-metadata.json",
        {
            "original_object_directory": str(source_objects),
            "shared_read_only_objects": True,
            "shallow": shallow.decode("ascii"),
            "shallow_sha256": digest(shallow),
            "copy_config_sha256": digest(copy_config),
            "source_history_depth": 1,
            "second_source_network_request": False,
        },
    )
    scope.run(
        "checkout-local-copy",
        [
            tools["git"]["path"],
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-C",
            str(work),
            "checkout",
            "--quiet",
            "--detach",
            identity["head"],
        ],
        scope.stage,
        15,
        local_git_environment,
    )
    state["work"] = work
    require(
        scope.read_git(work, "rev-parse", "HEAD").decode().strip() == identity["head"],
        "isolated copy HEAD differs",
    )
    require(
        not scope.read_git(work, "status", "--porcelain=v1", "--untracked-files=all"),
        "isolated copy did not start clean",
    )
    initial = source_snapshot(scope, work, identity["tree"])
    require(initial == before, "work copy is not the complete identical source")
    put(scope.evidence / "copy-before.json", initial)
    original_rc_only(work)
    require(
        time.monotonic() - scope.start <= 15,
        "identity/source-copy preparation exceeded its reviewed 15-second stage",
    )
    lock_before = parse_lock(work / "codex-rs/Cargo.lock")
    lock_targets(lock_before)
    contract_spec = importlib.util.spec_from_file_location(
        "reviewed_chrono_hooks_cli_workspace_lock_contract", work / CONTRACT_PATH
    )
    contract = importlib.util.module_from_spec(contract_spec)
    contract_spec.loader.exec_module(contract)
    bindings = contract.source_bindings(spec, work)
    module_before = (work / "MODULE.bazel.lock").read_bytes()
    require(
        raw_hash(work / "codex-rs/Cargo.lock")
        == spec["accepted_baseline_locks"]["codex-rs/Cargo.lock"]
        and raw_hash(work / "MODULE.bazel.lock")
        == spec["accepted_baseline_locks"]["MODULE.bazel.lock"],
        "this new scope does not start at the accepted actual two locks",
    )
    original_dir = scope.evidence / "original-locks"
    candidate_dir = scope.evidence / "candidate-locks"
    original_dir.mkdir()
    candidate_dir.mkdir()
    for path in sorted(LOCKS):
        (original_dir / Path(path).name).write_bytes((work / path).read_bytes())
    bin_dir = scope.stage / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "bazel"
    wrapper.write_text(
        "#!/bin/sh\nexec "
        + shlex.quote(tools["bazel"]["path"])
        + " --batch "
        + shlex.quote("--output_base=" + str(scope.stage / "bazel-output"))
        + ' "$@"\n'
    )
    wrapper.chmod(0o700)
    put(
        scope.evidence / "bazel-wrapper.json",
        {"path": str(wrapper), "content": wrapper.read_text(), **raw_hash(wrapper)},
    )
    environment = {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "RUSTUP_TOOLCHAIN": "1.96.0",
        "CARGO_TARGET_DIR": str(scope.stage / "cargo-target"),
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    control_stdout, control_stderr = scope.run(
        "new-lock-contract-controls-once",
        [
            tools["python"]["path"],
            "-m",
            "unittest",
            "-v",
            "test_hepta_chrono_hooks_cli_lock_contract_v1",
        ],
        work / "scripts",
        5,
        environment,
    )
    expected_controls = spec["synthetic_contract_controls"]
    require(
        len(expected_controls) == 9 and len(set(expected_controls)) == 9,
        "the nine new registered contract controls are not bound",
    )
    control_lines = control_stderr.read_text().splitlines()
    expected_lines = {
        f"{name} (test_hepta_chrono_hooks_cli_lock_contract_v1.ChronoHooksCliLockContractTests.{name}) ... ok"
        for name in expected_controls
    }
    observed_lines = [line for line in control_lines if line.startswith("test_")]
    require(
        len(observed_lines) == 9
        and set(observed_lines) == expected_lines
        and sum(
            bool(re.fullmatch(r"Ran 9 tests in [0-9.]+s", line))
            for line in control_lines
        )
        == 1
        and control_lines[-1] == "OK",
        "actual synthetic contract controls are incomplete",
    )
    put(
        scope.evidence / "new-contract-controls.json",
        {
            "status": "NINE_SYNTHETIC_CONTRACT_CONTROLS_PASSED",
            "names": expected_controls,
            "stdout": raw_hash(control_stdout),
            "stderr": raw_hash(control_stderr),
            "application_native_tests": 0,
            "resolver_qualification": False,
        },
    )
    update = [
        tools["cargo_launcher"]["path"],
        "+1.96.0",
        "update",
        "--workspace",
        "--manifest-path",
        "codex-rs/Cargo.toml",
    ]
    scope.run("hooks-cli-workspace-cargo-update-once", update, work, 100, environment)
    lock_after = parse_lock(work / "codex-rs/Cargo.lock")
    lock_targets(lock_after)
    rebinding = contract.lock_rebinding(lock_before, lock_after, bindings, spec)
    put(scope.evidence / "workspace-lock-rebinding.json", rebinding)
    cargo_hash = raw_hash(work / "codex-rs/Cargo.lock")
    metadata_path, _ = scope.run(
        "actual-locked-all-features-graph",
        [
            tools["cargo_launcher"]["path"],
            "+1.96.0",
            "metadata",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--locked",
            "--all-features",
            "--format-version",
            "1",
        ],
        work,
        30,
        environment,
    )
    require(
        raw_hash(work / "codex-rs/Cargo.lock") == cargo_hash,
        "locked metadata changed Cargo.lock",
    )
    metadata = json_value(metadata_path.read_bytes())
    graph = graph_readback(metadata, spec, work, lock_before, lock_after)
    graph["chrono_workspace_correspondence"] = contract.graph_rebinding(
        metadata, spec, work, lock_after, bindings
    )
    put(scope.evidence / "dependency-graph-readback.json", graph)
    scope.run(
        "original-bazel-lock-update-once",
        [tools["just"]["path"], "bazel-lock-update"],
        work,
        120,
        environment,
    )
    require(
        raw_hash(work / "codex-rs/Cargo.lock") == cargo_hash,
        "Bazel changed the already observed Cargo graph",
    )
    module_hash = raw_hash(work / "MODULE.bazel.lock")
    module_correspondence = contract.bazel_lock_correspondence(
        module_before, (work / "MODULE.bazel.lock").read_bytes(), spec
    )
    put(scope.evidence / "bazel-lock-correspondence.json", module_correspondence)
    scope.run(
        "bazel-error-mode-check",
        [str(wrapper), "mod", "deps", "--lockfile_mode=error"],
        work,
        20,
        environment,
    )
    require(
        raw_hash(work / "codex-rs/Cargo.lock") == cargo_hash
        and raw_hash(work / "MODULE.bazel.lock") == module_hash,
        "error-mode check changed either lock",
    )
    require(
        scope.read_git(work, "rev-parse", "HEAD").decode().strip() == identity["head"],
        "generator changed isolated HEAD",
    )
    require(
        (work / ".git/shallow").read_bytes() == shallow
        and (work / ".git/objects/info/alternates").read_bytes() == shared_objects
        and (work / ".git/config").read_bytes() == copy_config,
        "generator changed isolated Git routing or shallow boundary",
    )
    require(
        not scope.read_git(work, "diff", "--cached", "--name-only"),
        "generator changed the isolated index",
    )
    require(
        all(
            row.startswith(b"H ")
            for row in scope.read_git(work, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "generator hid a source through index flags",
    )
    for tool in tools.values():
        require(
            tool_file(Path(tool["path"])) == tool, "generator changed a prepared tool"
        )
    require(
        wrapper.read_text()
        == "#!/bin/sh\nexec "
        + shlex.quote(tools["bazel"]["path"])
        + " --batch "
        + shlex.quote("--output_base=" + str(scope.stage / "bazel-output"))
        + ' "$@"\n',
        "generator changed the scoped Bazel wrapper",
    )
    after = source_snapshot(scope, work, identity["tree"])
    changed = [path for path in before if before[path] != after[path]]
    require(set(changed) <= LOCKS, "resolver changed a tracked non-lock source")
    require(
        not scope.read_git(work, "ls-files", "--others", "--exclude-standard", "-z"),
        "resolver left an unexpected untracked source file",
    )
    ignored = scope.read_git(
        work, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"
    )
    output_links = []
    allowed_links = {"bazel-out", "bazel-bin", "bazel-testlogs", "bazel-" + work.name}
    for encoded in ignored.split(b"\0"):
        if not encoded:
            continue
        name = encoded.decode()
        link = work / name
        require(
            name in allowed_links and link.is_symlink(),
            "unexpected ignored work-copy input",
        )
        require(
            link.resolve().is_relative_to((scope.stage / "bazel-output").resolve()),
            "Bazel convenience link leaves its owned output base",
        )
        output_links.append({"path": name, "target": os.readlink(link)})
    put(scope.evidence / "owned-output-links.json", output_links)
    put(scope.evidence / "copy-after.json", after)
    for path in sorted(LOCKS):
        (candidate_dir / Path(path).name).write_bytes((work / path).read_bytes())
    scope.run(
        "two-lock-diff",
        [
            tools["git"]["path"],
            "-C",
            str(work),
            "diff",
            "--binary",
            "--",
            *sorted(LOCKS),
        ],
        work,
        5,
    )
    return {
        "status": "GENERATED_LOCK_CANDIDATE_REQUIRES_ROOT_REVIEW",
        "source": identity,
        "changed_tracked_paths": changed,
        "lock_postimages": {p: raw_hash(work / p) for p in sorted(LOCKS)},
        "original_generation_attempts": 1,
        "actual_all_feature_graph": True,
        "cargo_update_selection": "workspace-only",
        "workspace_update_attempts": 1,
        "selected_registry_update_attempts": 0,
        "prior_chrono_generation_scope_reopened": False,
        "bazel_postimage_byte_identical": module_correspondence[
            "full_postimage_byte_identical"
        ],
        "unapproved_registry_version_or_checksum_drift": False,
        "workspace_manifest_rebindings": bindings,
        "actual_chrono_inverse_edges": graph["chrono_workspace_correspondence"][
            "actual_inverse_edge_count"
        ],
        "all_features_edges_are_not_default_or_runtime_activity": True,
        "original_security_lock_scope_reopened": False,
        "chrono_unmaintained_unresolved": graph["chrono_unmaintained_unresolved"],
        "advisory_qualification": False,
        "application_native_tests_executed": 0,
        "tool_or_extension_work_inclusive_in_cost": True,
        "original_locked_workflow_replaced": False,
        "production_activation": False,
    }


def retain_failed_locks(scope, work, record):
    # Use the original absolute cutoff, including its existing receipt reserve.
    # A caught one-shot SIGALRM must not leave this collection unarmed.
    cutoff = scope.deadline - 1.5

    def remaining():
        left = cutoff - time.monotonic()
        if left <= 0:
            raise TimeoutError("failed-lock retention has no original scope allowance")
        return left

    signal.setitimer(signal.ITIMER_REAL, remaining())
    partial = scope.evidence / "failed-partial-locks"
    partial.mkdir(exist_ok=False)
    available = (
        EVIDENCE_ACCEPTANCE_CAP_BYTES - scope.storage_observation()["evidence_bytes"]
    )
    require(available >= 0, "failed-lock evidence acceptance allowance is exhausted")
    record.update(
        cutoff_monotonic_seconds=cutoff,
        chunk_bytes=64 * 1024,
        available_bytes_at_start=available,
    )
    for path in sorted(LOCKS):
        remaining()
        candidate = work / path
        try:
            source_fd = os.open(
                candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            )
        except FileNotFoundError:
            record["files"].append({"path": path, "status": "ABSENT"})
            continue
        try:
            before = os.fstat(source_fd)
            require(
                stat.S_ISREG(before.st_mode) and before.st_size <= available,
                "failed lock is not a regular file within retained evidence allowance: "
                + path,
            )
            copied, checksum = 0, hashlib.sha256()
            with (partial / Path(path).name).open("xb", buffering=0) as output:
                while True:
                    remaining()
                    chunk = os.read(
                        source_fd, min(64 * 1024, before.st_size - copied + 1)
                    )
                    remaining()
                    if not chunk:
                        break
                    require(
                        copied + len(chunk) <= before.st_size,
                        "failed lock grew during retention: " + path,
                    )
                    offset = 0
                    while offset < len(chunk):
                        remaining()
                        written = output.write(memoryview(chunk)[offset:])
                        remaining()
                        require(
                            written is not None and written > 0,
                            "failed-lock write made no progress",
                        )
                        offset += written
                    copied += len(chunk)
                    checksum.update(chunk)
            after, current = os.fstat(source_fd), candidate.lstat()
            key = lambda value: (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
            require(
                copied == before.st_size and key(before) == key(after) == key(current),
                "failed lock changed during retention: " + path,
            )
            remaining()
            available -= copied
            record["files"].append(
                {
                    "path": path,
                    "status": "RETAINED_FAILED_EVIDENCE",
                    "bytes": copied,
                    "sha256": checksum.hexdigest(),
                }
            )
        finally:
            os.close(source_fd)
    remaining()
    record["status"] = "COLLECTION_FINISHED"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare-start", "prepare-finish", "generate"))
    args = parser.parse_args()
    source = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    stage = Path(os.environ["LOCK_STAGE"]).resolve(strict=True)
    require(
        source not in stage.parents and stage not in source.parents and stage != source,
        "scope must live outside the original checkout",
    )
    require(
        os.name == "posix" and sys.platform == "linux",
        "Linux command ownership is required",
    )
    require(
        (stage / "evidence/job-start.json").is_file(),
        "unique workflow scope was not created",
    )
    start = time.monotonic()
    if args.mode == "prepare-finish":
        start = json_value((stage / "evidence/tool-start.json").read_bytes())[
            "monotonic_seconds"
        ]
    cap = RESOLVER_CAP if args.mode == "generate" else TOOL_CAP
    scope = Scope(source, stage, args.mode, start, cap)
    state, result = (
        {},
        {
            "status": "FAIL",
            "mode": args.mode,
            "cap_seconds": cap,
            "old_E1_E6_budget_used": 0,
            "old_host_preparation_replayed": False,
            "remote_writes": 0,
            "error": None,
        },
    )

    def elapsed(signum, frame):
        raise TimeoutError("shared engineering scope reached its deadline")

    previous = signal.signal(signal.SIGALRM, elapsed)
    signal.setitimer(
        signal.ITIMER_REAL, max(0.01, scope.deadline - time.monotonic() - 1.5)
    )
    try:
        if args.mode == "prepare-start":
            result.update(prepare_start(scope))
        elif args.mode == "prepare-finish":
            result.update(prepare_finish(scope))
        else:
            result.update(generate(scope, state))
    except Exception as error:
        result.update(status="FAIL", error=f"{type(error).__name__}: {error}")
    finally:
        # Failed/partial locks are evidence, never accepted candidates.
        if args.mode == "generate":
            try:
                if "before" in state:
                    after = source_snapshot(scope, source, state["source"]["tree"])
                    put(scope.evidence / "source-after.json", after)
                    require(after == state["before"], "original checkout changed")
                    require(
                        scope.read_git(source, "rev-parse", "HEAD").decode().strip()
                        == state["source"]["head"],
                        "original checkout HEAD changed",
                    )
                    require(
                        digest((source / ".git/shallow").read_bytes())
                        == state["source"]["shallow_sha256"],
                        "original shallow boundary changed",
                    )
                    require(
                        not scope.read_git(
                            source, "status", "--porcelain=v1", "--untracked-files=all"
                        ),
                        "original checkout became dirty",
                    )
                    result["original_checkout_unchanged"] = True
                else:
                    result["original_checkout_unchanged"] = None
            except Exception as error:
                result.update(
                    status="FAIL",
                    final_readback_error=f"{type(error).__name__}: {error}",
                )
            # A failed original-source readback cannot suppress the separate
            # collection of failed work-copy locks. These remain quarantined
            # evidence, under the same timer, and never accepted candidates.
            try:
                if "work" in state and result["status"] == "FAIL":
                    retention = {
                        "status": "INCOMPLETE",
                        "files": [],
                        "accepted_candidate": False,
                    }
                    result["failed_partial_lock_retention"] = retention
                    retain_failed_locks(scope, state["work"], retention)
            except Exception as error:
                result.update(
                    status="FAIL",
                    partial_lock_readback_error=f"{type(error).__name__}: {error}",
                )
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        result.update(scope.receipt())
        result["storage_final"] = scope.storage_observation()
        result["storage_limits"] = {
            "original_owner_stdout_cap_bytes": STDOUT_CAP_BYTES,
            "evidence_acceptance_cap_bytes": EVIDENCE_ACCEPTANCE_CAP_BYTES,
            "minimum_disk_headroom_bytes": MIN_FREE_BYTES,
            "stderr_has_real_time_byte_limit": False,
            "oversize_failed_originals_are_not_deleted_or_reclassified": True,
            "tool_generated_files_have_no_new_per_file_rlimit": True,
        }
        if (
            result["storage_final"]["evidence_bytes"] > EVIDENCE_ACCEPTANCE_CAP_BYTES
            or result["storage_final"]["free_bytes"] < MIN_FREE_BYTES
        ):
            result.update(status="FAIL", storage_acceptance_failed=True)
        job_start = json_value((scope.evidence / "job-start.json").read_bytes())
        result["whole_job_elapsed_seconds_so_far"] = (
            time.monotonic() - job_start["monotonic_seconds"]
        )
        if result["elapsed_seconds"] > cap:
            result.update(status="FAIL", cap_exceeded=True)
        result["full_job_or_tool_preparation_cpu_is_not_zero_if_unavailable"] = True
        put(scope.evidence / (args.mode + ".RESULT.json"), result)
        print(
            json.dumps(
                {
                    k: result.get(k)
                    for k in ("status", "mode", "elapsed_seconds", "error")
                }
            )
        )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Bootstrap errors happen before a command owner can be constructed.
        # The workflow already created this unique retained evidence directory.
        directory = Path(os.environ["LOCK_STAGE"]) / "evidence"
        failure = {
            "status": "FAIL_BOOTSTRAP",
            "error": f"{type(error).__name__}: {error}",
            "automatic_retry": False,
            "resolver_candidate_qualified": False,
        }
        put(directory / (sys.argv[1] + ".BOOTSTRAP_FAILURE.json"), failure)
        print(json.dumps(failure))
        raise SystemExit(1)
