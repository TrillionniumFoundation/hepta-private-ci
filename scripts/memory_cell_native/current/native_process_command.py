"""Retain one exact committed-source `just test` invocation, without retries."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_process_ci import source_identity
from native_trial import retain


def run(args):
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if command[:2] != ["just", "test"]:
        raise ValueError("only the repository test entry is admitted")
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    args.source_profile = "committed"
    start, usage = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {
        "command": command,
        "cwd": str(args.repo.resolve() / "codex-rs"),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "exit_code": None,
        "source_changed_during_execution": ["incomplete"],
        "automatic_retry": False,
    }
    try:
        before = source_identity(args)
        retain(args.out / "source-before.json", before)
        with (
            (args.out / "stdout.log").open("xb") as stdout,
            (args.out / "stderr.log").open("xb") as stderr,
        ):
            completed = subprocess.run(
                command,
                cwd=args.repo / "codex-rs",
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
            )
            receipt["exit_code"] = completed.returncode
        after = source_identity(args)
        retain(args.out / "source-after.json", after)
        receipt["source_changed_during_execution"] = (
            [] if before == after else ["source identity changed"]
        )
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        used = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt.update(
            wall_seconds=time.monotonic() - start,
            outer_child_user_seconds=used.ru_utime - usage.ru_utime,
            outer_child_system_seconds=used.ru_stime - usage.ru_stime,
        )
        retain(args.out / "receipt.json", receipt)
        print(json.dumps(receipt), flush=True)
    return receipt["exit_code"] or bool(receipt["source_changed_during_execution"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    raise SystemExit(run(parser.parse_args()))
