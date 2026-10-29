#!/usr/bin/env python3
"""Fixed diverse60 evidence, retaining every original qualification and install gate."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_neural_evidence_v1 as original
import hepta_neural_evidence_binary_v2 as binary
import hepta_neural_candidate_transport_v1 as transport
import hepta_neural_diverse_v3 as work
import hepta_neural_study_diverse_v3 as study_driver

require, read, regular, canonical = (
    original.require,
    original.read,
    original.regular,
    original.canonical,
)
REPOSITORIES = {"hepta", "chain", "chain-answer-eos", "chain-observed", "chain-diverse"}
COMMANDS = {
    **binary.COMMANDS,
    "diverse-trace-controls": 9,
    "diverse-training-controls": 7,
    "diverse-reader-controls": 13,
    "diverse-chain-controls": 14,
}
EXCLUSION_ROOT = Path(__file__).resolve().parents[1] / (
    "codex-rs/hepta-infer-worker-host/fixtures"
)
EXCLUSION_PARTS = (
    EXCLUSION_ROOT / "smollm-a593-exclusions.part1",
    EXCLUSION_ROOT / "smollm-a593-exclusions.part2",
)


def published_source(item):
    require(
        all(
            type(value) is str and re.fullmatch("[0-9a-f]{40}", value)
            for value in (study_driver.TRAINING_COMMIT, study_driver.TRAINING_TREE)
        ),
        "published exact diverse source identities required",
    )
    require(
        item["identity"]["commit"] == study_driver.TRAINING_COMMIT
        and item["identity"]["tree"] == study_driver.TRAINING_TREE,
        "exact separately published diverse training commit and tree",
    )


def excluded_prompts():
    parts = []
    for path in EXCLUSION_PARTS:
        identity = regular(path, 512_000)
        with original.open_regular(path) as stream:
            chunk = stream.read(512_001)
        require(
            hashlib.sha256(chunk).hexdigest() == identity["sha256"],
            "frozen exclusion shard changed",
        )
        parts.append(chunk)
    raw = b"".join(parts)
    require(
        type(study_driver.EXCLUSION_SHA) is str
        and re.fullmatch("[0-9a-f]{64}", study_driver.EXCLUSION_SHA)
        and hashlib.sha256(raw).hexdigest() == study_driver.EXCLUSION_SHA,
        "exact frozen all-observed prompt exclusions",
    )
    value = original.decode(raw)
    work.closed(
        value,
        "schema encoding formal_study_count formal_unique_prompts labels_or_scores_included "
        "new_holdout_generated observed_cutoff_utc purpose qualification source_manifest_sha256 "
        "unique_consumed_prompts excluded_prompt_sha256",
    )
    hashes = value["excluded_prompt_sha256"]
    require(
        value["schema"] == "hepta-neural-consumed-prompt-exclusion-v3"
        and value["encoding"] == "sha256(UTF-8 exact prompt bytes)"
        and value["formal_study_count"] == 10
        and value["formal_unique_prompts"] == 9382
        and value["unique_consumed_prompts"] == 10382
        and hashes == sorted(set(hashes))
        and len(hashes) == 10382
        and all(work.digest(item) for item in hashes)
        and value["labels_or_scores_included"] is False
        and value["new_holdout_generated"] is False
        and value["qualification"] is False,
        "complete hash-only fixed exposure exclusion",
    )
    return set(hashes)


def future_prompts(windows, excluded):
    require(
        len(windows) == 2 and all(len(rows) == 512 for rows in windows),
        "original two512 future windows",
    )
    seen = set()
    for rows in windows:
        for row in rows:
            digest = hashlib.sha256(row["prompt"].encode()).hexdigest()
            require(
                digest not in excluded and digest not in seen,
                "no known or repeated future prompt",
            )
            seen.add(digest)
    require(len(seen) == 1024, "complete distinct future prompts")


def complete_lineage(parent_step, execution, raw, trained, expected_output):
    require(
        Path(execution["output"])
        == expected_output
        == Path(trained["training"]["path"]).parent,
        "complete material reread belongs to this exact training output",
    )
    require(
        canonical(execution["source"])
        == canonical(raw["source"])
        == canonical(parent_step.sources(work.PROFILE)),
        "complete actual input and receipt source closure",
    )
    require(
        parent_step.verify_completion(execution) == trained["training"]["sha256"],
        "original complete parent setup and candidate material reread",
    )


def publication_provenance(raw, context, descriptor):
    source = raw["source"]
    require(
        source["binary_diverse60_training_data"] == work.DATA_SHA256
        and work.digest(source["binary_diverse60_observed"])
        and canonical(raw[work.CONTEXT_KEY]) == canonical(context),
        "complete diverse publication source and execution binding",
    )
    binding = dict(
        schema="hepta-diverse60-training-code-binding-v3",
        source=source,
        execution=context,
    )
    expected = hashlib.sha256(canonical(binding)).hexdigest()
    require(
        descriptor["source_manifest"]["training_code_digest"] == expected,
        "published diverse code digest binds every source and execution field",
    )
    require(
        descriptor["ledger"]["binding"]
        == hashlib.sha256(
            b"controlled-neural-diverse60-training-ledger-v3"
        ).hexdigest(),
        "published diverse descriptor reopens the actual sixty-row ledger",
    )
    return expected


class DiverseEvidence(original.Evidence):
    loop_schema = "hepta-real-neural-ordinary-loop-diverse-v3"
    study_schema = work.STUDY_SCHEMA + "-preregistered"
    training_steps, training_source_rows, consumed_step_records = 30, 60, 300
    positive_selector = "test(real_diverse_trained_child_prospective_qualification_cell_install_next_ordinary_read)"

    def validate_training_data(self, data, consumed, raw, trained, study_root):
        plan_path = study_root / "trained/model-plan.json"
        plan = read(plan_path)
        with original.open_regular(plan_path) as stream:
            plan_raw = stream.read(1024 * 1024 + 1)
        public = work.training_data()
        study_driver.checked_training_data(data, plan, plan_raw, public)
        work.closed(
            consumed,
            "schema training_data actual_receipt actual_trace original_runtime_source_sha256 "
            "experiment optimizer_steps distinct_source_rows actual_row_exposures fixed_training_data_sha256 "
            "update_schedule_sha256 steps evidence_scope",
        )
        require(
            consumed["schema"] == "hepta-neural-diverse-training-consumption-v3"
            and consumed["training_data"] == trained["training_data"]
            and consumed["actual_receipt"] == trained["training"]
            and consumed["actual_trace"] == raw["training"]["objective"]["trace"]
            and consumed["fixed_training_data_sha256"] == work.DATA_SHA256
            and consumed["update_schedule_sha256"]
            == work.identity(public["update_schedule"])
            and consumed["experiment"] == work.identity(plan)
            and consumed["original_runtime_source_sha256"] == raw["source"]["runtime"]
            and data["source_dataset_digest"] == trained["source_dataset_digest"],
            "exact independent diverse consumption and admitted dataset",
        )
        require(
            all(
                type(consumed[key]) is int and consumed[key] == count
                for key, count in (
                    ("optimizer_steps", 30),
                    ("distinct_source_rows", 60),
                    ("actual_row_exposures", 300),
                )
            )
            and len(consumed["steps"]) == 300
            and sum(len(row["input_ids"]) for row in consumed["steps"])
            == raw["training"]["tokens"]
            == 15600
            and sum(row["supervised_tokens"] for row in consumed["steps"])
            == raw["training"]["supervised_tokens"]
            == 300,
            "all scheduled scalar consumption remains explicit",
        )

    def loop(self):
        summary = super().loop()
        study_root = Path(summary["study_root"])
        loop = read(study_root / "positive-loop-result.json")
        trained, declaration = loop["training"], self.pin(loop["study"])
        require(
            declaration["optimizer_steps"] == 30
            and declaration["actual_row_exposures"] == 300
            and declaration["distinct_source_rows"] == 60
            and declaration["physical_microbatch"] == 1
            and declaration["expected_input_tokens"] == 15600
            and declaration["disclosed_adaptive_followup_to_known_NoGain"] is True
            and declaration["previous_consumed_prompt_exclusion_sha256"]
            == study_driver.EXCLUSION_SHA,
            "explicit diverse workload and disclosed adaptive hypothesis",
        )
        source = read(self.root / "source-before.json")["repositories"]["chain-diverse"]
        published_source(source)
        chain = Path(source["root"])
        study_driver.checkout_training_tree(chain)
        require(
            trained["schema"] == work.STUDY_SCHEMA + "-training-result"
            and trained["training_chain"] == study_driver.TRAINING_COMMIT
            and trained["training_tree"] == study_driver.TRAINING_TREE
            and trained["runtime_chain"] == study_driver.original.RUNTIME
            and trained["installation_authority"] is False,
            "actual exact diverse source result",
        )
        sys.path.insert(0, str(chain / "scripts"))
        import llm_binary_diverse60_observed_v3 as diverse
        import llm_runtime_parent_step_v2 as parent_step
        import llm_runtime_pilot as runtime
        from transformers import AutoTokenizer

        require(
            Path(diverse.__file__).resolve()
            == chain / "scripts/llm_binary_diverse60_observed_v3.py"
            and Path(parent_step.__file__).resolve()
            == chain / "scripts/llm_runtime_parent_step_v2.py"
            and Path(runtime.__file__).resolve()
            == chain / "scripts/llm_runtime_pilot.py",
            "reader uses only the pinned actual trainer and runtime",
        )
        raw, complete = self.pin(trained["training"]), self.pin(trained["completion"])
        consumed, context = (
            self.pin(trained["training_consumption"]),
            trained[work.CONTEXT_KEY],
        )
        require(
            raw["schema"] == "llm-runtime-parent-step-actual-" + work.SUFFIX
            and complete["schema"] == "llm-runtime-parent-step-result-" + work.SUFFIX
            and canonical(raw[work.CONTEXT_KEY])
            == canonical(complete[work.CONTEXT_KEY])
            == canonical(context),
            "complete new namespace without legacy substitution",
        )
        execution = read(
            study_root / ("trained/training/parent-step-input-" + work.SUFFIX + ".json")
        )
        require(
            self.path(execution["output"]) == study_root / "trained/training/execution",
            "actual completed material output in this study",
        )
        complete_lineage(
            parent_step,
            execution,
            raw,
            trained,
            study_root / "trained/training/execution",
        )
        objective = raw["training"]["objective"]
        require(
            runtime.identity(execution) == raw["input"] == complete["input"]
            and self.path(execution["files"]["plan"])
            == study_root / "trained/model-plan.json"
            and self.path(execution["initial_setup"]["diverse_plan"]["path"])
            == study_root / "trained/diverse-execution-plan-v3.json"
            and execution["initial_setup"]["training_data"]
            == dict(
                path=str(chain / "config/pon/binary-diverse60-training-v3.json"),
                sha256=work.DATA_SHA256,
            )
            and canonical(context) == canonical(diverse.context(execution))
            and canonical(objective)
            == canonical(
                diverse.objective_record(execution, objective["trace"], 15600)
            ),
            "exact parent input, data role, closed context and complete objective",
        )
        diverse.verify_supervisor(execution, complete["supervisor"])
        policy = runtime.exit_observation_profile(diverse.OBSERVER)
        costs = {
            "training": binary.observed_cost(
                complete["supervisor"], policy, 1800, 16 * 1024**3
            )
        }
        for window in range(2):
            for model in ("parent", "child"):
                phase = read(study_root / f"{model}-{window}/phase-result.json")
                costs[f"{model}-{window}"] = binary.observed_cost(
                    self.pin(phase["supervisor"]), policy, 600, 8 * 1024**3
                )
        work_done = transport.diverse_work(
            {"training": trained["training"]}, raw, context
        )
        trace_pin = objective["trace"]
        trace_path = self.path(trace_pin["path"])
        require(
            consumed["actual_trace"] == trace_pin,
            "actual independent complete trace pin",
        )
        with original.open_regular(trace_path) as stream:
            trace_raw = stream.read(1024 * 1024 + 1)
        require(
            len(trace_raw) == trace_pin["bytes"]
            and hashlib.sha256(trace_raw).hexdigest() == trace_pin["sha256"]
            and trace_raw.endswith(b"\n"),
            "unchanged actual trace on independent read",
        )
        public = work.training_data(
            chain / "config/pon/binary-diverse60-training-v3.json"
        )
        materials = Path(read(self.root / "native-input.json")["materials"])
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
            "original exact tokenizer and action IDs",
        )
        plan = runtime.validate_plan(read(study_root / "trained/model-plan.json"))
        require(
            [
                runtime.prompt_tokens(tokenizer, row, plan["input_tokens_max"])
                for row in public["training_rows"]
            ]
            == public["training_token_ids"],
            "independently retokenized all sixty exact public inputs",
        )
        work.validate_trace(
            [original.decode(line) for line in trace_raw.splitlines()],
            raw,
            consumed,
            public,
            context,
        )
        execution_plan_path = study_root / "trained/diverse-execution-plan-v3.json"
        require(
            regular(execution_plan_path)["sha256"] == context["plan_sha256"]
            and canonical(diverse.checked_plan(execution))
            == canonical(read(execution_plan_path))
            and context["recipe"] == runtime.identity(diverse.RECIPE)
            and consumed["original_runtime_source_sha256"]
            == runtime.file_sha(runtime.__file__)
            and objective["source_sha256"] == runtime.file_sha(diverse.__file__)
            and consumed["experiment"] == raw["experiment"] == runtime.identity(plan),
            "whole frozen plan, actual source and original material identity",
        )
        future_prompts(
            [read(study_root / f"future-{index}-inputs.json") for index in range(2)],
            excluded_prompts(),
        )
        publication = read(study_root / "actual-child-publication.json")
        code_digest = publication_provenance(
            raw, context, self.pin(publication["descriptor"])
        )
        transported = self.pin(publication["transport"])
        cell_input_path = study_root / "cell-input.json"
        cell_input = read(cell_input_path)
        require(
            transported["schema"]
            == "hepta-neural-candidate-transport-diverse-result-v3"
            and canonical(transported[work.CONTEXT_KEY]) == canonical(context)
            and transported["training_receipt_sha256"] == trained["training"]["sha256"]
            and transported["input_sha256"] == regular(cell_input_path)["sha256"]
            and cell_input["schema"] == transport.DIVERSE_SCHEMA
            and cell_input["training"] == trained["training"]
            and cell_input["completion"] == trained["completion"]
            and cell_input["binary"]["path"]
            == os.environ.get("HEPTA_NEURAL_STUDY_CELL"),
            "actual Cell transport binds this exact completed diverse child",
        )
        transport.preflight(cell_input)
        return {
            **summary,
            "profile": work.PROFILE,
            "actual_training_work": work_done,
            "supervised_costs": costs,
            "training_code_digest": code_digest,
            "prior_future_prompt_overlap": 0,
            "legacy_training_work_equivalent": False,
        }


def source(output):
    root = Path(original.ci.git("rev-parse", "--show-toplevel")).resolve()
    record = dict(
        schema="hepta-neural-complete-source-diverse-v3",
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
        ("chain-diverse", root.parent / "chain-diverse", "DIVERSE_TRAINING_CHAIN_SHA"),
    ):
        try:
            item = original.collect_source(directory, os.environ.get(variable))
            if name == "chain-diverse":
                published_source(item)
            record["repositories"][name] = item
        except (ValueError, OSError, original.ci.subprocess.SubprocessError) as error:
            record["errors"].append({"repository": name, "error": str(error)})
    record["valid"] = (
        not record["errors"] and set(record["repositories"]) == REPOSITORIES
    )
    original.save(output, record)
    return 0 if record["valid"] else 1


def assess(root):
    evidence = DiverseEvidence(root)
    report = dict(
        schema="hepta-neural-study-assessment-diverse-v3",
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
            and before["schema"] == "hepta-neural-complete-source-diverse-v3"
            and before["run"] == original.run_identity()
            and set(before["repositories"]) == REPOSITORIES
            and before["repositories"]["chain-diverse"]["identity"]["commit"]
            == os.environ.get("DIVERSE_TRAINING_CHAIN_SHA")
            and regular(evidence.root / "final-source-diff.patch")["bytes"] == 0,
            "all five complete current-run source snapshots must be identical",
        )
        published_source(before["repositories"]["chain-diverse"])
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
