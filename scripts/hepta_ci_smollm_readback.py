"""Read actual original native observations; controlled results always mean no-update."""

import hashlib
from pathlib import Path
import re
import subprocess

if __package__:
    from .hepta_ci_smollm_common import (
        DENIED,
        command,
        load_runtime,
        parent,
        read,
        require,
        run_context,
        save,
        sha,
        source_pair,
    )
else:
    from hepta_ci_smollm_common import (
        DENIED,
        command,
        load_runtime,
        parent,
        read,
        require,
        run_context,
        save,
        sha,
        source_pair,
    )


def execution(path, kind, pair):
    receipt = read(path)
    require(
        receipt["status"] == "passed"
        and receipt["exit_code"] == receipt["command_exit_code"] == 0,
        "native command failed or missing",
    )
    require(
        receipt["command"] == command(kind), "wrong native selector or execution policy"
    )
    require(
        all(
            type(receipt[key]) is int
            for key in (
                "minimum_tests",
                "observed_passed_tests",
                "observed_failed_tests",
            )
        ),
        "integer native test counts required",
    )
    require(
        receipt["minimum_tests"] == receipt["observed_passed_tests"] == 1
        and receipt["observed_failed_tests"] == 0,
        "exactly one real test must pass",
    )
    require(
        receipt["timed_out"] is False and receipt["output_limit_exceeded"] is False,
        "incomplete native command",
    )
    require(
        receipt["before"] == receipt["after"] and receipt["before"]["dirty"] is False,
        "native source changed",
    )
    for key in ("source_sha", "base_sha", "tested_sha", "lane"):
        require(receipt[key] == pair["hepta"][key], "foreign native source tuple")
    require(
        receipt["before"]["commit"] == pair["hepta"]["tested_sha"],
        "foreign native commit",
    )
    require(
        receipt["before"]["tree"] == pair["hepta"]["tested_tree"],
        "foreign native source tree",
    )
    for key, field in (
        ("GITHUB_RUN_ID", "run_id"),
        ("GITHUB_RUN_ATTEMPT", "run_attempt"),
        ("GITHUB_JOB", "job"),
    ):
        require(receipt[field] == run_context()[key], "foreign native run/attempt/job")
    require(
        Path(receipt["log_file"]).name == receipt["log_file"], "nonlocal native log"
    )
    require(
        sha(path.parent / receipt["log_file"]) == receipt["log_sha256"],
        "native log changed",
    )
    return {"receipt_sha256": sha(path), "log_sha256": receipt["log_sha256"]}


def original_result(path, schema, count):
    value = read(path)
    require(value["schema"] == schema, "wrong original result schema")
    require(
        all(value[key] is False for key in DENIED),
        "controlled fixture cannot grant product qualification",
    )
    require(
        value["original_control_reopen_exact"] is True
        and value["terminal_unload_observed"] is True,
        "original cleanup/reopen missing",
    )
    require(
        type(value["original_final_use_claims"]) is int
        and value["original_final_use_claims"] == count,
        "wrong original FinalUse count",
    )
    ids = value["original_control_requests"]
    require(
        type(ids) is list and all(type(item) is str and item for item in ids),
        "original request IDs must be a list",
    )
    require(
        len(ids) == len(set(ids)) == count, "missing/duplicate original control request"
    )
    return value


def scores(value):
    require(
        type(value) is list
        and len(value) == 2
        and all(type(item) is int and -(1 << 63) <= item < (1 << 63) for item in value),
        "two actual signed Q32 scores required",
    )


def verify(args):
    output, chain = args.output, args.chain.resolve(strict=True)
    summary = {
        "schema": "hepta-controlled-smollm-pair-readback-v1",
        "status": "failed",
        "adoption": "no-update",
        "controlled_contract_only": True,
        **dict.fromkeys(DENIED, False),
    }
    try:
        pair = source_pair(chain)
        prepared = read(output / "prepared.json")
        require(prepared["source_pair"] == pair, "prepared source pair changed")
        require(
            prepared["run_context"] == run_context(), "prepared run/attempt/job changed"
        )
        runtime, inherited = load_runtime(chain)
        runtime.verify_materials(Path(read(output / "native-input.json")["materials"]))
        for generation in (1, 2, 3):
            parent(output, generation, inherited)
        baseline = output / "gen2/worker/parent-material.json"
        candidate = output / "gen3/worker/parent-material.json"
        require(
            prepared["parent_sha256"] == {"2": sha(baseline), "3": sha(candidate)},
            "prepared parent changed",
        )
        receipts = {
            kind: execution(output.parent / f"smollm-{kind}.json", kind, pair)
            for kind in ("native", "comparison")
        }
        native = original_result(
            output / "native/native-owner-bridge-result.json",
            "hepta-smollm-neural-native-check-result-v1",
            3,
        )
        require(
            native["controlled_test_issuer"] is True
            and native["denied_query_executed"] is False,
            "original issuer denial missing",
        )
        require(
            native["cross_owner_rejected_before_admission"] is True
            and native["cross_body_generation_rejected_before_admission"] is True,
            "cross-owner refusal missing",
        )
        require(
            native["parent_file_sha256"] == sha(candidate)
            and native["parameters_sha256"] == read(candidate)["file_sha256"],
            "wrong native parent",
        )
        require(
            type(native["generation"]) is int and native["generation"] == 3,
            "wrong native generation",
        )
        scores(native["actual_scores_q32"])
        require(
            native["original_control_journal_sha256"]
            == sha(output / "native/original-inference.control"),
            "native journal changed",
        )
        comparison = original_result(
            output / "comparison/native-comparison-result.json",
            "controlled-real-neural-comparison-result-v1",
            66,
        )
        require(
            comparison["controlled_contract_only"] is True
            and comparison["controlled_signers"] is True,
            "comparison scope changed",
        )
        require(
            comparison["actual_forward_rows"] == 32
            and comparison["claim_scope"] == "Qualification",
            "wrong comparison scope/count",
        )
        require(
            comparison["inference_control_sha256"]
            == sha(output / "comparison/original-inference.control"),
            "comparison journal changed",
        )
        frozen = read(output / "comparison/frozen-controlled-comparison.json")
        require(
            frozen["schema"] == "controlled-neural-comparison-precommit-v1"
            and frozen["controlled_contract_only"] is True
            and frozen["independent_accepted"] is False
            and frozen["prospective_accepted"] is False,
            "holdout precommit scope changed",
        )
        require(
            type(frozen["logging_seed"]) is list
            and len(frozen["logging_seed"]) == 32
            and all(
                type(item) is int and 0 <= item <= 255
                for item in frozen["logging_seed"]
            ),
            "original single seed missing",
        )
        require(
            frozen["candidate_parent"] == sha(candidate)
            and frozen["baseline_parent"] == sha(baseline),
            "holdout used foreign parents",
        )
        require(
            frozen["candidate_parameters"] == read(candidate)["file_sha256"]
            and frozen["baseline_parameters"] == read(baseline)["file_sha256"],
            "holdout used foreign weights",
        )
        raw = read(output / "comparison/actual-forward-observations.json")
        require(
            raw["controlled_contract_only"] is True
            and raw["independent_accepted"] is False
            and raw["prospective_accepted"] is False,
            "forward scope changed",
        )
        require(
            raw["result_error"] is None
            and raw["candidate_shutdown"] is None
            and raw["baseline_shutdown"] is None,
            "holdout/unload failed",
        )
        tasks = {row["decision_id"]: row for row in frozen["tasks"]}
        rows = raw["rows"]
        require(
            len(rows) == len(tasks) == len({row["decision_id"] for row in rows}) == 32,
            "incomplete/duplicate comparison",
        )
        for row in rows:
            task = tasks[row["decision_id"]]
            require(
                row["query_sha256"]
                == hashlib.sha256(task["query"].encode()).hexdigest(),
                "changed holdout query",
            )
            for role in ("candidate", "baseline"):
                scores(row[f"{role}_scores_q32"])
                require(
                    re.fullmatch(r"[0-9a-f]{64}", row[f"{role}_receipt"])
                    and row[f"{role}_receipt"] != "0" * 64,
                    "missing actual receipt",
                )
                require(
                    row[f"{role}_correct"]
                    is (row[f"{role}_choice"] == task["expected_action"]),
                    "inconsistent original correctness",
                )
        require(source_pair(chain) == pair, "paired source changed during readback")
        summary.update(
            status="controlled-execution-observed",
            source_pair=pair,
            execution=receipts,
            original_runner_decision=comparison["original_runner_decision"],
            actual_forward_rows=32,
            original_native_result_sha256=sha(
                output / "native/native-owner-bridge-result.json"
            ),
            original_comparison_result_sha256=sha(
                output / "comparison/native-comparison-result.json"
            ),
            frozen_comparison_sha256=sha(
                output / "comparison/frozen-controlled-comparison.json"
            ),
            raw_forward_observations_sha256=sha(
                output / "comparison/actual-forward-observations.json"
            ),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        summary["error"] = str(error)
        raise
    finally:
        save(output / "readback.json", summary)
