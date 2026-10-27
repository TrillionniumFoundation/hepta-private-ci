#!/usr/bin/env python3
"""Enter the pinned original evaluator while retaining Python isolated mode."""

import argparse
import hashlib
import importlib
import importlib.util
from pathlib import Path
import subprocess
import sys


def load_controls():
    # This helper belongs to the same pinned Hepta checkout as this entry. Do not
    # add its directory, the caller's directory, or PYTHONPATH to module lookup.
    path = Path(__file__).resolve().with_name("hepta_cumulative_controls.py")
    spec = importlib.util.spec_from_file_location("hepta_cumulative_controls", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked_pilot(chain, controls):
    controls.require(chain.is_absolute(), "absolute Chain source")
    names = ("llm_runtime_pilot", "llm_runtime_parent_step", "llm_parent_material")
    controls.require(
        all(name not in sys.modules for name in names), "preloaded Chain runtime"
    )
    # git diff, used by checked_runtime, checks tracked source. A new package can
    # shadow a tracked sibling module, including when ignored by .gitignore.
    extra = subprocess.check_output(
        [
            "git",
            "-C",
            str(chain),
            "ls-files",
            "--others",
            "-z",
            "--",
            "scripts",
            "formal",
            "config",
        ]
    )
    controls.require(not extra, "untracked fixed source is not importable")
    runtime, _ = controls.checked_runtime(chain)
    for name in names:
        module = importlib.import_module(name)
        controls.require(
            Path(module.__file__).resolve()
            == (chain / "scripts" / (name + ".py")).resolve(),
            "fixed Chain module origin",
        )
    return runtime


def main():
    if not (
        sys.flags.isolated == 1
        and sys.flags.ignore_environment == 1
        and sys.flags.no_user_site == 1
        and sys.flags.dont_write_bytecode == 1
    ):
        raise ValueError("isolated Python with -I -B is required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", type=Path, required=True)
    parser.add_argument("pilot_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    controls = load_controls()
    controls.require(
        args.pilot_args and args.pilot_args[0] == "_child",
        "only the original evaluator child is allowed",
    )
    help_only = args.pilot_args == ["_child", "--help"]
    if not help_only:
        child_parser = argparse.ArgumentParser(add_help=False)
        for name in ("materials", "output", "plan", "phase", "role", "artifact"):
            child_parser.add_argument("--" + name, required=True)
        child = child_parser.parse_args(args.pilot_args[1:])
        controls.require(
            child.phase == "evaluate" and child.role in controls.ROLES,
            "only cumulative control evaluation is allowed",
        )
        controls.require(
            all(
                Path(getattr(child, name)).is_absolute()
                for name in ("materials", "output", "plan", "artifact")
            ),
            "absolute evaluator material paths",
        )
        controls.require(
            hashlib.sha256(Path(child.plan).read_bytes()).hexdigest()
            == controls.PLAN_SHA,
            "unchanged evaluator ten-step plan bytes",
        )
    runtime = checked_pilot(args.chain, controls)
    if not help_only:
        controls.verify_runtime_snapshot()
    # The original parser, child implementation, source identity and resource
    # observation remain unchanged. --help imports its real sibling modules but
    # returns before material access, model imports or any execution receipt.
    sys.argv = [runtime.__file__, *args.pilot_args]
    runtime.main()


if __name__ == "__main__":
    main()
