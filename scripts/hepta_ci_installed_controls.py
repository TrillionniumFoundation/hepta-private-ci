#!/usr/bin/env python3
"""Execute both fixed-source image-control suites without promoting qualification."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

if __package__:
    from . import hepta_ci_installed_cell as image
    from .hepta_ci_exec import run
else:
    import hepta_ci_installed_cell as image
    from hepta_ci_exec import run


def controls(chain, chain_sha, chain_tree, host, cell, imported, output):
    image.require(
        all(
            re.fullmatch(r"[0-9a-f]{40}", item) is not None and item != "0" * 40
            for item in (chain_sha, chain_tree)
        ),
        "an explicit final Chain commit/tree is required",
    )
    run_identity, source = image.ci("cell-installed-host-v3"), image.candidate()
    chain_source = image.candidate_plan(
        source=chain_sha, tested=chain_sha, lane="source-head", repository=chain
    )
    image.require(chain_source["tested_tree"] == chain_tree, "fixed Chain tree differs")
    before = {"hepta": image.identity(), "chain": image.identity(repository=chain)}
    binaries = {"hepta": image.native_record(host), "chain": image.native_record(cell)}
    transport = image.read(imported)
    image.require(
        transport.get("schema") == "hepta-cell-native-image-import-v1"
        and all(
            transport.get(key) is False
            for key in ("installed_controls_executed", "model_qualified", "pn0_closed")
        )
        and transport.get("ci") == run_identity
        and transport.get("candidate") == source
        and transport.get("source_identity") == before["hepta"]
        and transport.get("binary") == binaries["hepta"],
        "imported image binding changed",
    )
    build, _ = image.receipt(
        output / "chain-build.json",
        chain_source,
        0,
        command=image.BUILD_COMMAND,
        repository=chain,
    )
    image.require(
        build["job"] == "cell-installed-host-v3", "Chain build from another job"
    )
    record = dict(
        schema="hepta-cell-installed-controls-v1",
        status="running",
        ci=run_identity,
        scope="source-head-native-image-controls-only",
        hepta_candidate=source,
        chain_candidate=chain_source,
        before=before,
        binaries_before=binaries,
        hepta_lock=image.file_record(Path("codex-rs/Cargo.lock")),
        chain_lock=image.file_record(chain / "trillionnium/Cargo.lock"),
        native_pair_qualification=False,
        pn0_closed=False,
        model_qualified=False,
        final_use_qualified=False,
        production_activation=False,
    )
    error = None
    statuses = []
    image.write(output / "installed-controls-started.json", record)
    try:
        os.environ["TRNM_CELL_BIN"] = str(cell)
        commands = [
            (
                "original-handoff",
                14,
                [
                    sys.executable,
                    str(chain / "scripts/ci/test_llm_cell_host_handoff.py"),
                    "-v",
                ],
            ),
            (
                "installed-handoff",
                8,
                [
                    "bash",
                    str(chain / "scripts/ci/run_llm_cell_installed_host_controls.sh"),
                    str(cell),
                    str(host),
                ],
            ),
        ]
        for name, count, command in commands:
            image.require(
                image.identity() == before["hepta"]
                and image.identity(repository=chain) == before["chain"],
                "source changed before control dispatch",
            )
            image.require(
                {"hepta": image.native_record(host), "chain": image.native_record(cell)}
                == binaries,
                "native image changed before control dispatch",
            )
            result = run(output / (name + ".json"), command, minimum_tests=count)
            statuses.append(result)
            try:
                image.receipt(output / (name + ".json"), source, count, exact=True)
            except (ValueError, OSError) as failure:
                error = str(failure)
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        error = str(failure)
    try:
        record["after"] = {
            "hepta": image.identity(),
            "chain": image.identity(repository=chain),
        }
        record["binaries_after"] = {
            "hepta": image.native_record(host),
            "chain": image.native_record(cell),
        }
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        error = str(failure)
    if error is None and (
        record.get("after") != before or record.get("binaries_after") != binaries
    ):
        error = "source or native image changed during controls"
    passed = (
        error is None
        and statuses == [0, 0]
        and record.get("after") == before
        and record.get("binaries_after") == binaries
    )
    record.update(
        status="passed" if passed else "failed", command_statuses=statuses, error=error
    )
    image.write(output / "installed-controls.json", record)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("chain", "host", "cell", "imported", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--chain-sha", required=True)
    parser.add_argument("--chain-tree", required=True)
    return controls(**vars(parser.parse_args()))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        print("installed-image controls rejected: " + str(failure), file=sys.stderr)
        raise SystemExit(2)
