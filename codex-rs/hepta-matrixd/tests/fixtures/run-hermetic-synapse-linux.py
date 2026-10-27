#!/usr/bin/env python3
"""Independent native ARM64 qualification; original macOS entry remains unchanged."""

import sys

if not sys.flags.isolated:
    raise SystemExit(
        "Run this qualification controller with the sealed Python interpreter and -I"
    )

import argparse
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess

sys.dont_write_bytecode = True


def durable_json(path, value):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Bootstrap evidence requires an absolute physical path")
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError("Symlink in bootstrap evidence path")
    with path.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal_host_tools(output):
    tools = {}
    for name in ("python3", "git", "docker"):
        found = sys.executable if name == "python3" else shutil.which(name)
        if found is None:
            raise ValueError(f"Required trusted host controller tool is absent: {name}")
        path = Path(found).resolve(strict=True)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("Host controller tool is not an actual executable file")
        tools[name] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return durable_json(
        output, {"schema": "hepta.synapse.linux.host-tools.v1", "tools": tools}
    )


def bootstrap_modules(args):
    """The workflow-selected driver stays separate from the untrusted candidate.

    Load only byte-for-byte HEAD module sources into memory. Do not put the
    fixture directory on sys.path: that would allow a staged tomllib.py (or a
    valid-looking .pyc) to execute before the candidate policy guard.
    """

    def sealed_json(path, expected):
        data = Path(path).read_bytes()
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or hashlib.sha256(data).hexdigest() != expected
        ):
            raise ValueError("Bootstrap JSON SHA-256 differs")
        return json.loads(data)

    if args.phase == "probe-inside":
        plan = sealed_json(args.plan, args.plan_sha256)
        source = sealed_json(plan["source_seal"]["path"], plan["source_seal"]["sha256"])
        git, expected_head = plan["bootstrap_git"], source["qualification_commit"]
    elif args.phase in {"build-inside", "run-inside", "seed-inside"}:
        plan = sealed_json(args.plan, args.plan_sha256)
        seal = sealed_json(plan["builder_seal"]["path"], plan["builder_seal"]["sha256"])
        source = sealed_json(plan["source_seal"]["path"], plan["source_seal"]["sha256"])
        git, expected_head = seal["tools"]["git"], source["qualification_commit"]
    else:
        seal = sealed_json(args.host_tools, args.host_tools_sha256)
        git, expected_head = seal["tools"]["git"], args.source_commit
    executable = Path(git["path"])
    if (
        executable.resolve(strict=True) != executable
        or executable.stat().st_size != git["bytes"]
        or hashlib.sha256(executable.read_bytes()).hexdigest() != git["sha256"]
    ):
        raise ValueError("Bootstrap actual Git executable differs from the sealed tool")
    root = Path(__file__).resolve().parents[4]
    environment = {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
    }

    def git_bytes(arguments):
        result = subprocess.run(
            [
                str(executable),
                "--no-pager",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                *arguments,
            ],
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return result.stdout

    if git_bytes(["rev-parse", "HEAD"]).strip().decode() != expected_head:
        raise ValueError("Driver HEAD differs from the workflow/plan-selected source")
    entry_name = "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse-linux.py"
    if Path(__file__).read_bytes() != git_bytes(
        ["show", f"{expected_head}:{entry_name}"]
    ):
        raise ValueError("Driver entry bytes differ from the workflow-selected HEAD")
    prefix = "codex-rs/hepta-matrixd/tests/fixtures/linux_synapse/"
    names = git_bytes(["ls-tree", "-rz", expected_head, "--", prefix]).split(b"\0")
    sources = {}
    for item in names:
        if not item:
            continue
        entry, name_bytes = item.split(b"\t", 1)
        mode, kind, _object = entry.split(b" ")
        name = name_bytes.decode()
        if not name.endswith(".py"):
            continue
        path = root / name
        data = git_bytes(["show", f"{expected_head}:{name}"])
        if (
            kind != b"blob"
            or mode not in {b"100644", b"100755"}
            or path.resolve(strict=True) != path
            or path.read_bytes() != data
        ):
            raise ValueError("Driver module differs from the exact HEAD source")
        if stat.S_IMODE(path.stat().st_mode) != (0o755 if mode == b"100755" else 0o644):
            raise ValueError("Driver module file mode differs from HEAD")
        module = "linux_synapse." + name.removeprefix(prefix).removesuffix(
            ".py"
        ).replace("/", ".")
        if module.endswith(".__init__"):
            module = module.removesuffix(".__init__")
        sources[module] = (str(path), data)
    if "linux_synapse" not in sources:
        raise ValueError(
            "The workflow-selected HEAD does not contain this Linux qualification driver"
        )

    class VerifiedSourceLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in sources:
                return importlib.machinery.ModuleSpec(
                    fullname, self, is_package=fullname == "linux_synapse"
                )
            return None

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            filename, data = sources[module.__name__]
            module.__file__ = filename
            exec(compile(data, filename, "exec", dont_inherit=True), module.__dict__)

    sys.meta_path.insert(0, VerifiedSourceLoader())


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="phase", required=True)
    for phase in ("build-inside", "run-inside", "probe-inside", "seed-inside"):
        internal = sub.add_parser(phase)
        internal.add_argument("--plan", type=Path, required=True)
        internal.add_argument("--plan-sha256", required=True)
    sub.add_parser("idle")
    host = sub.add_parser("seal-host-tools")
    host.add_argument("--output", type=Path, required=True)
    ci = sub.add_parser("ci")
    for name in (
        "restored-root",
        "producer",
        "producer-result-sha256",
        "source-commit",
        "output",
        "docker-socket",
    ):
        ci.add_argument("--" + name, required=True)
    cleanup = sub.add_parser("cleanup-ci")
    for name in ("restored-root", "source-commit", "output", "docker-socket"):
        cleanup.add_argument("--" + name, required=True)
    prepare = sub.add_parser("prepare")
    for name in (
        "restored-root",
        "producer",
        "producer-result-sha256",
        "source-commit",
        "worktree",
        "output",
        "host-tools",
        "host-tools-sha256",
        "docker-socket",
    ):
        prepare.add_argument("--" + name, required=True)
    run = sub.add_parser("run")
    for name in (
        "restored-root",
        "producer",
        "producer-result-sha256",
        "source-commit",
        "worktree",
        "output",
        "builder-seal",
        "builder-seal-sha256",
        "tool-bundle",
        "cargo-seed",
        "seed-ledger",
        "seed-ledger-sha256",
        "host-tools",
        "host-tools-sha256",
        "docker-socket",
    ):
        run.add_argument("--" + name, required=True)
    run.add_argument("--builder-archive")
    return result


def main():
    args = parser().parse_args()
    if args.phase in {"run", "prepare", "ci", "cleanup-ci"}:

        def terminate(signum, _frame):
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)
    if args.phase == "ci":
        output = Path(args.output)
        if (
            not output.is_absolute()
            or ".." in output.parts
            or any(item.is_symlink() for item in (output, *output.parents))
        ):
            raise ValueError("CI output requires a new absolute physical directory")
        if not output.parent.is_dir():
            raise ValueError("CI output parent must already exist")
        output.mkdir(mode=0o700, exist_ok=False)
        args.host_tools = str(output / "HOST_TOOLS.json")
        args.worktree_parent = str(output.parent / (output.name + "-worktrees"))
        try:
            args.host_tools_sha256 = seal_host_tools(Path(args.host_tools))
            durable_json(
                output / "BOOTSTRAP_AUTHORITY.json",
                {
                    "source_commit": args.source_commit,
                    "host_tools_sha256": args.host_tools_sha256,
                    "producer_result_sha256": args.producer_result_sha256,
                },
            )
            bootstrap_modules(args)
        except BaseException as error:
            durable_json(
                output / "CI_BOOTSTRAP_FAILURE.json",
                {
                    "status": "failed",
                    "source_commit": args.source_commit,
                    "producer_result_sha256": args.producer_result_sha256,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "qualification_executed": False,
                },
            )
            raise
    elif args.phase == "cleanup-ci":
        authority = json.loads(
            (Path(args.output) / "BOOTSTRAP_AUTHORITY.json").read_bytes()
        )
        if authority["source_commit"] != args.source_commit:
            raise ValueError(
                "Cleanup source differs from the original workflow authority"
            )
        args.host_tools = str(Path(args.output) / "HOST_TOOLS.json")
        args.host_tools_sha256 = authority["host_tools_sha256"]
        bootstrap_modules(args)
    elif args.phase not in {"idle", "seal-host-tools"}:
        bootstrap_modules(args)
    if args.phase == "idle":
        signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))
        print("Linux qualification runtime namespace ready", flush=True)
        while True:
            signal.pause()
    elif args.phase == "build-inside":
        from linux_synapse.build import build_inside

        build_inside(args.plan, args.plan_sha256)
    elif args.phase == "run-inside":
        from linux_synapse.runtime import run_inside

        run_inside(args.plan, args.plan_sha256)
    elif args.phase == "probe-inside":
        from linux_synapse.prep_inside import probe_tools

        probe_tools(Path("/hepta-probe"))
    elif args.phase == "seed-inside":
        from linux_synapse.prep_inside import fetch_seed

        fetch_seed(args.plan, args.plan_sha256)
    elif args.phase == "prepare":
        from linux_synapse.prepare import preparation

        preparation(args)
    elif args.phase == "ci":
        from linux_synapse.ci import ci

        ci(args)
    elif args.phase == "cleanup-ci":
        from linux_synapse.recovery import recover

        recover(args)
    elif args.phase == "seal-host-tools":
        if args.output.resolve() != args.output or not args.output.parent.is_dir():
            raise ValueError(
                "Host tool seal requires a physical absolute path in an existing directory"
            )
        print(seal_host_tools(args.output))
    else:
        from linux_synapse.orchestrate import run

        run(args)


if __name__ == "__main__":
    main()
