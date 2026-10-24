"""One Linux process-group deadline around the registered edge mechanism event."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from edge_sources import identity
from evolution_common import digest, read_json, require, retain


def bounded_run(command, log_path, *, seconds):
    require(
        sys.platform == "linux" and seconds > 0, "Linux process-group deadline required"
    )
    started, timed_out, interrupted = time.monotonic_ns(), False, None
    with Path(log_path).open("xb") as log:
        with subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        ) as process:
            try:
                code = process.wait(timeout=seconds)
            except BaseException as error:
                timed_out = isinstance(error, subprocess.TimeoutExpired)
                interrupted = None if timed_out else type(error).__name__
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                code = process.wait()
    return dict(
        command=command,
        pid=process.pid,
        returncode=code,
        timed_out=timed_out,
        interrupted=interrupted,
        elapsed_ns=time.monotonic_ns() - started,
        deadline_seconds=seconds,
        timeout_action="SIGKILL complete process group; worker parent-death binding also retained",
    )


def main(args):
    require(
        args.model_lane_authorized,
        "root must allocate the single model lane before launching",
    )
    require(
        digest(identity(args.repo, args.budget_scripts)) == args.source_sha256,
        "edge runner source pin mismatch",
    )
    require(
        digest(read_json(args.protocol)) == args.protocol_sha256,
        "edge runner protocol pin mismatch",
    )
    output = args.output.absolute()
    require(not output.exists(), "new edge output required; no in-place retry")
    output.parent.mkdir(parents=True, exist_ok=True)
    prefixes = {
        name: output.with_name(output.name + suffix)
        for name, suffix in (
            ("start", ".launch.json"),
            ("log", ".launch.log"),
            ("finish", ".completion.json"),
        )
    }
    require(
        not any(p.exists() for p in prefixes.values()),
        "prior launch evidence must remain untouched",
    )
    command = [
        sys.executable,
        "-B",
        str(args.repo / "scripts/memory_cell_network/model_child.py"),
        "--parent-pid",
        str(os.getpid()),
        str(Path(__file__).with_name("edge_trial.py")),
    ]
    for name in (
        "repo",
        "budget_scripts",
        "protocol",
        "protocol_sha256",
        "source_sha256",
        "output",
    ):
        command.extend(["--" + name.replace("_", "-"), str(getattr(args, name))])
    retain(
        prefixes["start"],
        dict(
            schema="hepta.edge-launch.v1",
            command=command,
            protocol_sha256=args.protocol_sha256,
            source_sha256=args.source_sha256,
            started_unix_ns=time.time_ns(),
            whole_event_deadline_seconds=900,
            automatic_retry=False,
        ),
    )
    try:
        receipt = bounded_run(command, prefixes["log"], seconds=900)
    except BaseException as error:
        retain(
            prefixes["finish"],
            dict(
                error_type=type(error).__name__,
                error=str(error),
                complete_result=False,
                automatic_retry=False,
            ),
        )
        raise
    receipt.update(
        schema="hepta.edge-completion.v1",
        complete_result=(output / "result.json").is_file(),
        automatic_retry=False,
    )
    retain(prefixes["finish"], receipt)
    return (
        0
        if receipt["returncode"] == 0
        and receipt["complete_result"]
        and not receipt["timed_out"]
        else 1
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "budget-scripts", "protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--model-lane-authorized", action="store_true")
    raise SystemExit(main(parser.parse_args()))
