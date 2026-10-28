#!/usr/bin/env python3
"""One prespecified public six-arm experiment, after the original real gates.

These unsigned local gate/readback records are execution evidence, never a
product credential. Public fixture scores cannot authorize a model upgrade.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_smollm_three_rounds_v2 as rounds

CHAIN_COMMIT = "9035171271e9f437b7224b53532f41a2b2894be7"
PROFILE = "canonical-positive-zero-answer-eos-balanced-v3"
OUTCOMES = (
    "REQUIRED_CLI_OUTCOME",
    "SCOPED_RUST_OUTCOME",
    "COLD_RUNTIME_OUTCOME",
    "MATERIALS_OUTCOME",
    "ORDINARY_OUTCOME",
    "PROPOSAL_ROUNDS_OUTCOME",
    "DESCENDANTS_OUTCOME",
    "LINT_OUTCOME",
)
PACKAGES = (
    "codex-hepta-agent-protocol",
    "codex-hepta-learning-artifacts",
    "codex-hepta-agentd",
    "codex-hepta-infer-worker-host",
    "codex-app-server",
)
ORDINARY = (
    "test(real_selected_initial_serves_ordinary_context_then_refuses_revocation) | "
    "test(real_public_initial_reopens_same_ordinary_owners)"
)
THREE_ROUNDS = "test(real_public_initial_three_rounds_hold_and_read_original_current)"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_record(path):
    rounds.require(
        path.is_file() and path.stat().st_size <= 1024 * 1024,
        "bounded original record required",
    )
    return json.loads(path.read_bytes())


def validate_gates(root, source):
    required_path = root / "required-outcomes.json"
    required = read_record(required_path)
    rounds.require(
        required["schema"] == "hepta-public-initial-required-outcomes-v2"
        and required["outcomes"] == dict.fromkeys(OUTCOMES, "success")
        and required["model_target_available"] is True
        and required["all_required_outcomes_passed"] is True
        and required["original_full_rust_gate_required"] is True
        and required["product_qualification"] is False
        and required["three_installed_upgrades_proven"] is False,
        "all original outcomes must actually pass before research",
    )
    scoped = ["just", "test", "--locked"]
    for package in PACKAGES:
        scoped += ["-p", package]
    scoped += ["--no-capture"]
    native = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-infer-worker-host",
        "--lib",
        "--profile",
        "hepta-public-initial-v2",
        "-E",
    ]
    roster = (
        ("scoped-rust.json", 1, scoped),
        (
            "ordinary-native.json",
            2,
            native + [ORDINARY, "--run-ignored", "only", "--no-capture"],
        ),
        (
            "three-rounds-native.json",
            1,
            native + [THREE_ROUNDS, "--run-ignored", "only", "--no-capture"],
        ),
    )
    pins = {required_path.name: digest(required_path)}
    run = None
    for name, minimum, command in roster:
        path = root / name
        record = read_record(path)
        rounds.require(
            record["schema_version"] == 1
            and record["status"] == "passed"
            and all(
                type(record[k]) is int and record[k] == 0
                for k in (
                    "command_exit_code",
                    "exit_code",
                    "returncode",
                    "observed_failed_tests",
                )
            )
            and record["timed_out"] is False
            and record["output_limit_exceeded"] is False
            and type(record["observed_passed_tests"]) is int
            and record["observed_passed_tests"] >= minimum
            and type(record["minimum_tests"]) is int
            and record["minimum_tests"] == minimum
            and record["command"] == command
            and record["source_sha"] == record["tested_sha"] == source
            and record["before"] == record["after"]
            and record["before"]["commit"] == source
            and record["before"]["dirty"] is False,
            "original source-bound command failed, skipped or did not execute its tests: "
            + name,
        )
        observed_run = (
            record["run_id"],
            record["run_attempt"],
            record["job"],
            record["lane"],
        )
        rounds.require(
            observed_run[0]
            and observed_run[1]
            and observed_run[2:] == ("cold-ordinary-three-rounds", "source-head")
            and (run is None or run == observed_run),
            "same original run required",
        )
        run = observed_run
        logfile = Path(record["log_file"])
        rounds.require(logfile.name == str(logfile), "original log basename required")
        logfile = root / logfile
        rounds.require(
            logfile.is_file()
            and logfile.stat().st_size == record["log_bytes"]
            and digest(logfile) == record["log_sha256"],
            "original command log pin",
        )
        pins[name] = digest(path)
        pins[logfile.name] = record["log_sha256"]
    return dict(
        source=source,
        run=list(run),
        records=pins,
        scope="unsigned-local-execution-records-not-product-authority",
    )


def validate_ordinary_loop(readback, loop):
    original_schema = "hepta-controlled-public-initial-three-round-loop-v2"
    if loop["schema"] != original_schema:
        import hepta_smollm_observed_execution_v1 as observation

        observation.validate_loop_context(loop)
    else:
        rounds.require(
            "execution_profile" not in loop
            and all("observation_execution" not in row for row in loop["rounds"]),
            "legacy loop cannot relabel observed execution",
        )
    rounds.require(
        loop["controlled_test_issuer"] is True
        and loop["same_original_artifact_owner"] is True
        and loop["completed_rounds"] == 3
        and len(loop["rounds"]) == 3
        and len(loop["ordinary_sessions"]) == 4
        and loop["ordinary_sessions"][0] == readback
        and loop["original_current"] == readback["current"]
        and loop["beneficial_releases"] == loop["installed_children"] == 0
        and loop["product_qualification_issued"] is False,
        "completed original three-round owner readback required",
    )
    for session in loop["ordinary_sessions"]:
        rounds.require(
            session["schema"] == "hepta-controlled-ordinary-public-initial-session-v2"
            and session["withdrawal_refused"] is False
            and session["current_before"] == session["current_after"]
            and session["current"] == readback["current"]
            and all(
                session["current"][key] == session["current_before"][key]
                for key in ("head_digest", "record_count", "file_digest")
            )
            and session["parent"] == readback["parent"]
            and session["home_root"] == loop["same_home_root"]
            and session["ordinary_context_reads"] > 0
            and session["product_qualification_issued"] is False,
            "unwithdrawn original owner, actual parent and unchanged CURRENT required",
        )


def validate_request(args):
    rounds.require(
        args.research_profile == PROFILE
        and args.round == 1
        and args.proposal_parent == args.parent
        and args.proposal_parent_sha256 == args.parent_sha256
        and args.proposal_training_lineage == [],
        "one original-CURRENT parent experiment without diagnostic ancestry required",
    )
    repo = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "scripts",
            "codex-rs/hepta-learning-artifacts/profiles",
            ".github/workflows/hepta-public-initial-v2.yml",
        ],
        check=True,
    )
    gates = validate_gates(args.original_gates, source)
    config = read_record(args.original_native_input)
    rounds.require(
        config["schema"] == "hepta-smollm-neural-native-check-v1"
        and all(
            Path(config[k]).is_absolute()
            for k in ("chain", "materials", "parent", "output")
        )
        and Path(config["materials"]) == args.materials
        and Path(config["parent"]) == args.parent
        and config["parent_sha256"] == args.parent_sha256,
        "original native inputs must match this actual parent",
    )
    original_head = subprocess.check_output(
        ["git", "-C", config["chain"], "rev-parse", "HEAD"], text=True
    ).strip()
    rounds.require(
        original_head == rounds.CHAIN_COMMIT,
        "original model gates use the original source",
    )
    subprocess.run(
        [
            "git",
            "-C",
            config["chain"],
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "scripts",
            "formal",
            "config",
        ],
        check=True,
    )
    rounds.require(
        args.ordinary_readback
        == Path(config["output"]) / "p/ordinary-0/ordinary-session-result.json"
        and args.original_native_input == args.original_gates / "native-input.json"
        and Path(config["output"]) == args.original_gates / "n",
        "readback must belong to the original native gate output",
    )
    readback = read_record(args.ordinary_readback)
    loop_path = Path(config["output"]) / "p/loop-observations.json"
    loop = read_record(loop_path)
    validate_ordinary_loop(readback, loop)
    context = dict(
        schema="hepta-original-gates-for-answer-eos-research-v3",
        gates=gates,
        original_native_input_sha256=digest(args.original_native_input),
        ordinary_readback_sha256=digest(args.ordinary_readback),
        original_loop_sha256=digest(loop_path),
        entry_sha256=digest(Path(__file__)),
        original_chain_commit=original_head,
    )
    if loop["schema"] != "hepta-controlled-public-initial-three-round-loop-v2":
        context.update(
            schema="hepta-observed-original-gates-for-answer-eos-research-v1",
            execution_profile=loop["execution_profile"],
            original_model_material_source_unchanged=True,
        )
    return context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "native-input",
        "ordinary-readback",
        "original-gates",
        "chain",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    rounds.require(
        all(value.is_absolute() for value in vars(args).values()),
        "absolute paths required",
    )
    config = read_record(args.native_input)
    rounds.run(
        SimpleNamespace(
            chain=args.chain,
            materials=Path(config["materials"]),
            parent=Path(config["parent"]),
            parent_sha256=config["parent_sha256"],
            ordinary_readback=args.ordinary_readback,
            output=args.output,
            round=1,
            proposal_parent=Path(config["parent"]),
            proposal_parent_sha256=config["parent_sha256"],
            proposal_training_lineage=[],
            research_profile=PROFILE,
            original_gates=args.original_gates,
            original_native_input=args.native_input,
        )
    )


if __name__ == "__main__":
    main()
