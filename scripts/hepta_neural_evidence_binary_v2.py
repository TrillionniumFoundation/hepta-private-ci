#!/usr/bin/env python3
"""Explicit binary-v2 evidence reader; all original product gates remain required."""

import argparse
import hashlib
import math
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_neural_evidence_v1 as original
import hepta_neural_candidate_transport_v1 as transport

require, read, regular, canonical = (
    original.require,
    original.read,
    original.regular,
    original.canonical,
)
TRAINING_TREE = "1ba8d5460f77aa2e00f7bf1b5e400626b555e158"
EXCLUSION_SHA = "d2101f954f9b025d5fe0a87b73ae2d31f20eb6f989ed279a04ffe38d0932b06d"
PROFILE = "canonical-positive-zero-binary-batch-observed-v2"
REPOSITORIES = {"hepta", "chain", "chain-answer-eos", "chain-observed", "chain-binary"}
COMMANDS = {
    **original.COMMANDS,
    "cell-binding-controls": 13,
    "binary-reader-controls": 8,
}


def validate_trace(records, raw, consumed, source_rows, expected_tokens, context):
    """Recompute exposure order, CE from logits, and every original-source token."""
    require(
        len(source_rows) == len(expected_tokens) == 10
        and len(records) == 112
        and len(consumed["steps"]) == 100,
        "complete ten-row/one-hundred-microstep trace",
    )
    start = records[0]
    hashes = [hashlib.sha256(canonical(row)).hexdigest() for row in source_rows]
    require(
        start["event"] == "start"
        and start["input"] == raw["input"]
        and start["profile"] == PROFILE
        and start["recipe"] == context["recipe"]
        and start["plan_sha256"] == context["plan_sha256"]
        and start["source"] == raw["source"]["binary_answer_observed"]
        and start["source_rows"] == hashes
        and type(start["pid"]) is int
        and start["pid"] > 1
        and type(start["start_monotonic_ns"]) is int
        and start["start_monotonic_ns"] > 0,
        "trace start is bound to the actual execution and original source rows",
    )
    position, tokens, previous_cpu = 1, 0, 0
    previous_clock = start["start_monotonic_ns"]
    means = []
    for update in range(10):
        losses = []
        for ordinal, source_row in enumerate(source_rows):
            row = records[position]
            position += 1
            selected = ("yes", "no").index(source_row["expected_output"])
            ids = expected_tokens[ordinal]
            require(
                row["event"] == "microstep"
                and type(row["optimizer_step"]) is int
                and row["optimizer_step"] == update
                and type(row["row_ordinal"]) is int
                and row["row_ordinal"] == ordinal
                and row["source_row_sha256"] == hashes[ordinal]
                and type(row["input_ids"]) is list
                and row["input_ids"] == ids
                and 0 < len(ids) <= 128
                and all(
                    type(token) is int and 0 <= token < 49152
                    for token in row["input_ids"]
                )
                and row["answer_token_ids"] == [10407, 4607]
                and all(type(token) is int for token in row["answer_token_ids"])
                and type(row["target_index"]) is int
                and row["target_index"] == selected
                and row["backward_completed"] is True,
                "actual ordered microstep matches independently tokenized source",
            )
            require(
                type(row["answer_logits"]) is list
                and len(row["answer_logits"]) == 2
                and all(
                    type(value) is str and math.isfinite(float(value))
                    for value in row["answer_logits"]
                )
                and type(row["loss"]) is str
                and math.isfinite(float(row["loss"])),
                "finite original answer logits and loss",
            )
            logits = [float(value) for value in row["answer_logits"]]
            difference = logits[1 - selected] - logits[selected]
            expected_loss = max(difference, 0) + math.log1p(math.exp(-abs(difference)))
            observed = float(row["loss"])
            require(
                math.isfinite(expected_loss)
                and observed >= 0
                and abs(observed - expected_loss) <= 0.00001 * max(1, expected_loss),
                "binary CE must agree with the recorded actual two-token logits",
            )
            require(
                type(row["completed_monotonic_ns"]) is int
                and row["completed_monotonic_ns"] >= previous_clock
                and type(row["completed_process_cpu_ns"]) is int
                and row["completed_process_cpu_ns"] >= previous_cpu,
                "actual trace clocks cannot rewind",
            )
            previous_clock, previous_cpu = (
                row["completed_monotonic_ns"],
                row["completed_process_cpu_ns"],
            )
            require(
                canonical(consumed["steps"][update * 10 + ordinal])
                == canonical(
                    dict(
                        optimizer_step=update,
                        row_ordinal=ordinal,
                        source_row_sha256=hashes[ordinal],
                        input_ids=ids,
                        supervised_tokens=1,
                    )
                ),
                "independent consumption receipt must exactly match each trace row",
            )
            losses.append(observed)
            tokens += len(ids)
        update_row = records[position]
        position += 1
        require(
            update_row["event"] == "optimizer-step"
            and type(update_row["optimizer_step"]) is int
            and update_row["optimizer_step"] == update
            and type(update_row["microsteps"]) is int
            and update_row["microsteps"] == 10
            and update_row["optimizer_completed"] is True
            and type(update_row["gradient_l2_squared"]) is str
            and math.isfinite(float(update_row["gradient_l2_squared"]))
            and float(update_row["gradient_l2_squared"]) > 0
            and type(update_row["completed_monotonic_ns"]) is int
            and update_row["completed_monotonic_ns"] >= previous_clock
            and type(update_row["completed_process_cpu_ns"]) is int
            and update_row["completed_process_cpu_ns"] >= previous_cpu,
            "ten actual optimizer completions with finite nonzero gradients",
        )
        previous_clock, previous_cpu = (
            update_row["completed_monotonic_ns"],
            update_row["completed_process_cpu_ns"],
        )
        means.append(format(math.fsum(losses) / 10, ".17g"))
    end = records[position]
    require(
        end["event"] == "complete"
        and type(end["completed_monotonic_ns"]) is int
        and end["completed_monotonic_ns"] >= previous_clock
        and all(
            type(end[key]) is int and end[key] == expected
            for key, expected in (
                ("optimizer_steps", 10),
                ("microsteps", 100),
                ("tokens", tokens),
                ("supervised_tokens", 100),
            )
        )
        and raw["training"]["loss"] == means
        and raw["training"]["tokens"] == tokens
        and raw["training"]["supervised_tokens"] == 100,
        "actual complete trace totals and mean losses",
    )
    return dict(
        optimizer_updates=10,
        gradient_microsteps=100,
        independent_source_rows=10,
        input_tokens=tokens,
        answer_supervised_tokens=100,
        eos_supervised_tokens=0,
    )


def observed_cost(value, policy, seconds, rss):
    """Read additional full policy and actual cost fields after original gates."""
    require(
        value["exit_observation_profile"] == policy
        and value["terminal_reconciliation_profile"] == "explicit-" + policy["profile"]
        and value["budget"] == dict(wall_seconds=seconds, rss_bytes=rss)
        and value["child_spawned"] is True
        and value["owned_child_exit_observed"] is True
        and value["cleanup_method"] == "wait4"
        and value["sample_interval_ms"] == 50,
        "exact full original owned-exit source policy and resource owner",
    )
    for key in (
        "observed_wall_ns",
        "child_cpu_ns",
        "observer_cpu_ns",
        "sampled_peak_rss_bytes",
        "waited_child_peak_rss_bytes",
    ):
        require(
            type(value[key]) is int and value[key] >= 0,
            "actual nonnegative integer resource counters",
        )
    require(
        value["observed_wall_ns"] <= seconds * 1_000_000_000
        and value["sampled_peak_rss_bytes"] <= rss
        and value["waited_child_peak_rss_bytes"] <= rss,
        "actual recorded wall and RSS remain within the unchanged original budgets",
    )
    elapsed = None
    if "exit_cleanup_observation" in value:
        cleanup = value["exit_cleanup_observation"]
        require(
            cleanup["outcome"] == "terminal-wait4"
            and "error" not in cleanup
            and cleanup["retirement_closed_by"] == "exact-owned-child-terminal-wait4"
            and type(cleanup["completed_ns"]) is int
            and type(cleanup["missing_sample_ns"]) is int,
            "present exit-cleanup observation must close on the actual original wait4",
        )
        elapsed = cleanup["completed_ns"] - cleanup["missing_sample_ns"]
        require(
            0 <= elapsed <= 100_000_000,
            "observed terminal cleanup respects the original100ms",
        )
    return {
        key: value[key]
        for key in (
            "observed_wall_ns",
            "child_cpu_ns",
            "observer_cpu_ns",
            "sampled_peak_rss_bytes",
            "waited_child_peak_rss_bytes",
        )
    } | {
        "exit_cleanup_elapsed_ns": elapsed,
        "missing_cleanup_timestamps_do_not_mean_zero": True,
        "rss_scope": "maximum single-process high-water, not simultaneous whole process tree",
    }


class BinaryEvidence(original.Evidence):
    loop_schema = "hepta-real-neural-ordinary-loop-binary-v2"
    study_schema = "hepta-neural-study-binary-v2-preregistered"
    consumed_step_records = 100
    positive_selector = "test(real_binary_trained_child_prospective_qualification_cell_install_next_ordinary_read)"

    def loop(self):
        summary = super().loop()
        study_root = Path(summary["study_root"])
        loop = read(study_root / "positive-loop-result.json")
        trained = loop["training"]
        study = self.pin(loop["study"])
        require(
            study["optimizer_steps"] == 10
            and study["actual_row_exposures"] == 100
            and study["independent_source_rows"] == 10
            and study["disclosed_adaptive_followup_to_known_NoGain"] is True
            and study["previous_consumed_prompt_exclusion_sha256"] == EXCLUSION_SHA,
            "explicit new workload and disclosed adaptive followup",
        )
        source = read(self.root / "source-before.json")["repositories"]["chain-binary"]
        chain = Path(source["root"])
        require(
            source["identity"]["tree"] == TRAINING_TREE
            and trained["training_chain"] == source["identity"]["commit"]
            and trained["training_tree"] == TRAINING_TREE,
            "training used the independently snapshotted exact binary source",
        )
        sys.path.insert(0, str(chain / "scripts"))
        import llm_binary_answer_observed_v2 as binary
        import llm_runtime_pilot as runtime
        from transformers import AutoTokenizer

        require(
            Path(binary.__file__).resolve()
            == chain / "scripts/llm_binary_answer_observed_v2.py"
            and Path(runtime.__file__).resolve()
            == chain / "scripts/llm_runtime_pilot.py",
            "reader imports only the independently snapshotted training source",
        )
        raw = self.pin(trained["training"])
        complete = self.pin(trained["completion"])
        consumed = self.pin(trained["training_consumption"])
        data = self.pin(trained["training_data"])
        context = trained["binary_observed_execution"]
        require(
            raw["schema"] == "llm-runtime-parent-step-actual-binary-observed-v2"
            and complete["schema"]
            == "llm-runtime-parent-step-result-binary-observed-v2"
            and consumed["schema"] == "hepta-neural-binary-training-consumption-v2"
            and consumed["actual_row_exposures"] == 100
            and consumed["independent_source_rows"] == 10
            and raw["binary_observed_execution"]
            == complete["binary_observed_execution"]
            == context
            and context["profile"] == PROFILE
            and context["recipe"] == runtime.identity(binary.RECIPE),
            "new namespace and exact frozen trainer recipe; no old-profile substitution",
        )
        objective = raw["training"]["objective"]
        execution_input = read(
            study_root / "trained/training/parent-step-input-binary-observed-v2.json"
        )
        require(
            runtime.identity(execution_input) == raw["input"] == complete["input"]
            and self.path(execution_input["files"]["plan"])
            == study_root / "trained/model-plan.json"
            and self.path(execution_input["initial_setup"]["binary_plan"]["path"])
            == study_root / "trained/binary-execution-plan-v2.json"
            and canonical(context) == canonical(binary.context(execution_input))
            and canonical(objective)
            == canonical(
                binary.objective_record(
                    execution_input, objective["trace"], raw["training"]["tokens"]
                )
            ),
            "exact original input, closed context and every objective field",
        )
        binary.verify_supervisor(execution_input, complete["supervisor"])
        policy = runtime.exit_observation_profile(binary.OBSERVER)
        costs = {
            "training": observed_cost(
                complete["supervisor"], policy, 1800, 16 * 1024**3
            )
        }
        for window in range(2):
            for model in ("parent", "child"):
                phase = read(study_root / f"{model}-{window}/phase-result.json")
                costs[f"{model}-{window}"] = observed_cost(
                    self.pin(phase["supervisor"]), policy, 600, 8 * 1024**3
                )
        require(
            objective["same_work_as_legacy_ten_single_rows"] is False
            and objective["execution"] == context
            and objective["source_sha256"] == runtime.file_sha(binary.__file__),
            "actual workload is not claimed equivalent to the old ten single rows",
        )
        transport.binary_work({"training": trained["training"]}, raw, context)
        trace_pin = objective["trace"]
        trace_path = self.path(trace_pin["path"])
        require(
            trace_path
            == Path(trained["training"]["path"]).parent
            / "binary-training-trace-v2.jsonl"
            and regular(trace_path, 1024 * 1024)
            == {key: trace_pin[key] for key in ("bytes", "sha256")}
            and consumed["actual_trace"] == trace_pin,
            "complete bounded actual trace pin",
        )
        with original.open_regular(trace_path) as stream:
            trace_bytes = stream.read(1024 * 1024 + 1)
        require(
            hashlib.sha256(trace_bytes).hexdigest() == trace_pin["sha256"]
            and trace_bytes.endswith(b"\n"),
            "trace bytes stay unchanged during parsing",
        )
        records = [original.decode(line) for line in trace_bytes.splitlines()]
        config = read(self.root / "native-input.json")
        materials = Path(config["materials"])
        runtime.verify_materials(materials)
        tokenizer = AutoTokenizer.from_pretrained(
            str(materials),
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
        tokenizer.padding_side = "left"
        require(
            tokenizer.bos_token_id == 1
            and tokenizer.eos_token_id == tokenizer.pad_token_id == 2
            and len(tokenizer) == 49152
            and [
                tokenizer.encode(answer, add_special_tokens=False)
                for answer in ("yes", "no")
            ]
            == [[10407], [4607]],
            "all original tokenizer files and both original answer tokens",
        )
        model_plan = runtime.validate_plan(read(study_root / "trained/model-plan.json"))
        execution_plan = read(study_root / "trained/binary-execution-plan-v2.json")
        require(
            regular(study_root / "trained/binary-execution-plan-v2.json")["sha256"]
            == context["plan_sha256"]
            and execution_plan["recipe"] == binary.RECIPE
            and execution_plan["base_model_plan"]["identity"]
            == runtime.identity(model_plan)
            and consumed["original_runtime_source_sha256"]
            == runtime.file_sha(runtime.__file__)
            and consumed["experiment"] == runtime.identity(model_plan),
            "frozen exact recipe, original model plan and consumer runtime",
        )
        require(
            canonical(binary.checked_plan(execution_input))
            == canonical(execution_plan),
            "the entire frozen binary plan is reproduced from the original execution input",
        )
        rows = data["consumed_training_rows"]
        require(
            rows == binary.rows(model_plan),
            "trace uses exactly the original first ten source rows",
        )
        expected = [runtime.prompt_tokens(tokenizer, row, 128) for row in rows]
        work = validate_trace(records, raw, consumed, rows, expected, context)
        previous = (
            Path(__file__).resolve().parents[1]
            / "codex-rs/hepta-infer-worker-host/fixtures/smollm-consumed-prompts-067-v2.json"
        )
        require(
            regular(previous)["sha256"] == EXCLUSION_SHA,
            "frozen prior prompt exclusions",
        )
        excluded = set(read(previous)["excluded_prompt_sha256"])
        require(len(excluded) == 1024, "all previous consumed prompt identities")
        seen = set()
        for window in range(2):
            tasks = read(study_root / f"future-{window}-inputs.json")
            for task in tasks:
                digest = hashlib.sha256(task["prompt"].encode()).hexdigest()
                require(
                    digest not in excluded and digest not in seen,
                    "no repeated or previously observed future prompt",
                )
                seen.add(digest)
        require(len(seen) == 1024, "two complete new future prompt cohorts")
        publication = read(study_root / "actual-child-publication.json")
        transported = self.pin(publication["transport"])
        cell_input_path = study_root / "cell-input.json"
        cell_input = read(cell_input_path)
        require(
            transported["schema"] == "hepta-neural-candidate-transport-binary-result-v2"
            and canonical(transported["binary_observed_execution"])
            == canonical(context)
            and transported["training_receipt_sha256"] == trained["training"]["sha256"]
            and transported["input_sha256"] == regular(cell_input_path)["sha256"]
            and cell_input["schema"] == transport.BINARY_SCHEMA
            and cell_input["training"] == trained["training"]
            and cell_input["completion"] == trained["completion"]
            and cell_input["binary"]["path"]
            == os.environ.get("HEPTA_NEURAL_STUDY_CELL"),
            "Cell consumed this exact completed binary training lineage and actual executable",
        )
        transport.preflight(cell_input)
        return {
            **summary,
            "profile": PROFILE,
            "actual_training_work": work,
            "supervised_costs": costs,
            "prior_future_prompt_overlap": 0,
            "legacy_training_work_equivalent": False,
        }


def source(output):
    root = Path(original.ci.git("rev-parse", "--show-toplevel")).resolve()
    record = dict(
        schema="hepta-neural-complete-source-binary-v2",
        run=original.run_identity(),
        repositories={},
        errors=[],
        valid=False,
    )
    for name, directory, variable in (
        ("hepta", root, "SOURCE_SHA"),
        ("chain", root.parent / "chain", "CHAIN_SHA"),
        ("chain-answer-eos", root.parent / "chain-answer-eos", "RESEARCH_CHAIN_SHA"),
        ("chain-observed", root.parent / "chain-observed", "OBSERVATION_CHAIN_SHA"),
        ("chain-binary", root.parent / "chain-binary", "BINARY_TRAINING_CHAIN_SHA"),
    ):
        try:
            item = original.collect_source(directory, os.environ.get(variable))
            if name == "chain-binary":
                require(
                    item["identity"]["tree"] == TRAINING_TREE,
                    "exact separately frozen binary training tree",
                )
            record["repositories"][name] = item
        except (ValueError, OSError, original.ci.subprocess.SubprocessError) as error:
            record["errors"].append({"repository": name, "error": str(error)})
    record["valid"] = (
        not record["errors"] and set(record["repositories"]) == REPOSITORIES
    )
    original.save(output, record)
    return 0 if record["valid"] else 1


def assess(root):
    evidence = BinaryEvidence(root)
    report = dict(
        schema="hepta-neural-study-assessment-binary-v2",
        run=original.run_identity(),
        required_outcomes={name: os.environ.get(name) for name in original.REQUIRED},
        checks={},
        passed=False,
        installation_authority=False,
    )

    def check(name, action):
        try:
            report["checks"][name] = dict(passed=True, result=action())
        except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
            report["checks"][name] = dict(passed=False, error=str(error))

    def sources():
        before, after = (
            read(evidence.root / name)
            for name in ("source-before.json", "source-after.json")
        )
        require(
            before == after
            and before["valid"] is True
            and before["schema"] == "hepta-neural-complete-source-binary-v2"
            and before["run"] == original.run_identity()
            and set(before["repositories"]) == REPOSITORIES
            and before["repositories"]["chain-binary"]["identity"]["tree"]
            == TRAINING_TREE
            and before["repositories"]["chain-binary"]["identity"]["commit"]
            == os.environ.get("BINARY_TRAINING_CHAIN_SHA")
            and regular(evidence.root / "final-source-diff.patch")["bytes"] == 0,
            "all five complete current-run source snapshots must be identical",
        )
        return {name: item["identity"] for name, item in before["repositories"].items()}

    check(
        "declared_outcomes",
        lambda: require(
            all(value == "success" for value in report["required_outcomes"].values()),
            "every original required outcome must succeed; skipped is not passed",
        ),
    )
    check("complete_source", sources)
    for name, minimum in COMMANDS.items():
        check(name, lambda name=name, minimum=minimum: evidence.command(name, minimum))
    check("actual_positive_loop", evidence.loop)
    report["passed"] = all(value["passed"] for value in report["checks"].values())
    original.save(evidence.root / "qualification-summary.json", report)
    return 0 if report["passed"] else 1


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("source").add_argument("--output", type=Path, required=True)
    commands.add_parser("assess").add_argument("--root", type=Path, required=True)
    archiver = commands.add_parser("archive")
    archiver.add_argument("--root", type=Path, required=True)
    archiver.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "source":
        return source(args.output)
    if args.command == "assess":
        return assess(args.root)
    return original.archive(args.root, args.output)


if __name__ == "__main__":
    sys.exit(main())
