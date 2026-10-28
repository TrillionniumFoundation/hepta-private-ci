"""Summarize audited online stopping and incremental inference evidence."""

import argparse
import json
from pathlib import Path

from online_audit_common import check, sha
from online_summary_metrics import boundary_summary, performance_summary


def average(row, percent=False, digits=4):
    scale = 100 if percent else 1
    mean, sd = row["mean"] * scale, row["sd"]
    suffix = "%" if percent else ""
    return f"{mean:.{digits}f} ± {sd * scale:.{digits}f}{suffix}"


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        + ["| " + " | ".join(map(str, row)) + " |" for row in rows]
    )


def boundary_markdown(boundary):
    lines = [
        "## Causal paid-observation task",
        "",
        "All four arms share each frozen study001 actor, the new episode arrays and the same observation charge. "
        "One temperature is fitted on training prefixes; direct thresholds use 100 training updates and fixed thresholds use validation utility. "
        "The value policy uses a finite-grid Gaussian transition model informed by the supplied SNR. "
        "The actor's natural threshold remains distinct from this task-level stopping rule.",
        "",
        "The table reports mean ± sample SD across five actor seeds. Accuracy is percent; utility is correctness reward minus every purchased observation cost, including the first read.",
        "",
    ]
    rows = []
    for split, modes in boundary["splits"].items():
        for mode, metrics in modes.items():
            rows.append(
                [
                    split.upper(),
                    mode,
                    average(metrics["accuracy"], True, 2),
                    average(metrics["mean_observations"], digits=3),
                    average(metrics["mean_cost"]),
                    average(metrics["net_utility"]),
                    int(sum(metrics["total_processed_rows"]["values"])),
                    int(sum(metrics["total_avoided_model_steps"]["values"])),
                ]
            )
    lines += [
        table(
            [
                "Split",
                "Policy",
                "Accuracy",
                "Reads / episode",
                "Charge / episode",
                "Net utility",
                "Executed model steps",
                "Avoided model steps",
            ],
            rows,
        ),
        "",
        "Avoided work is measured by actual RAM-source iterator reads and incremental model updates ending at STOP. It does not measure sensor, network or energy savings.",
        "",
        "### Prespecified paired utility contrasts",
        "",
    ]
    rows = [
        [
            name,
            f"{row['mean']:+.6f}",
            f"[{row['lower']:+.6f}, {row['upper']:+.6f}]",
            f"{row['sd']:.6f}",
        ]
        for name, row in boundary["paired_utility_intervals"].items()
    ]
    lines += [
        table(
            [
                "Value minus comparator",
                "Mean difference",
                "98.75% paired Student-t interval",
                "Paired SD",
            ],
            rows,
        ),
        "",
        "These are four Bonferroni-adjusted intervals using the five seed means (df = 4). Episodes and time steps are not counted as independent optimization seeds.",
        "",
        "### Shared temperature calibration",
        "",
    ]
    rows = [
        [
            split.upper(),
            kind,
            average(metrics["prefix_ce"]),
            average(metrics["prefix_brier"]),
        ]
        for split, groups in boundary["calibration"].items()
        for kind, metrics in groups.items()
    ]
    lines += [
        table(["Split", "Odds", "Prefix cross entropy", "Prefix Brier score"], rows),
        "",
        "A fitted temperature changes confidence calibration. It does not establish that neural log-odds follow the transition model used by the Bellman table.",
        "",
        "### Fitting and inherited actor cost",
        "",
    ]
    rows = [
        [
            row["seed"],
            f"{row['shared_temperature']:.6f}",
            f"{row['fixed_threshold']:.4f}",
            f"{row['policy_fit_total_cpu_seconds']:.4f}",
            f"{row['bellman_table_cpu_seconds']:.4f}",
            f"{row['new_study_parent_cpu_seconds']:.4f}",
            f"{row['historical_actor_training_cpu_seconds']:.4f}",
        ]
        for row in boundary["fits"]
    ]
    lines += [
        table(
            [
                "Actor seed",
                "Shared temperature",
                "Fixed threshold",
                "Policy fitting CPU s",
                "Bellman table CPU s",
                "New study parent CPU s",
                "Historical actor training CPU s",
            ],
            rows,
        ),
        "",
        "Historical actor training is explicitly retained, although these actors are reused. Fitting and table time are nested in the new-study parent total; native child CPU is separate.",
    ]
    return lines


def native_markdown(boundary):
    native, lines = boundary["native"], ["## Original native owner and NDU", ""]
    total = native["totals"]
    lines += [
        f"The audited subset contains **{total['episodes']} actual native episodes**, "
        f"**{total['observations']} paid reads**, **{total['processes']} native processes** and "
        f"**{total['cold_recoveries']} cold native recoveries**. "
        f"The consumed native and Python policies have {total['policy_disagreements']} step-level action differences; "
        f"{total['same_stop_as_python']} / {total['episodes']} episodes stop at the same step.",
        "",
    ]
    rows = []
    for split, policies in native["splits"].items():
        for mode, row in policies.items():
            metric = row["metrics"]
            rows.append(
                [
                    split.upper(),
                    mode,
                    f"{100 * metric['accuracy']:.2f}%",
                    f"{metric['mean_observations']:.4f}",
                    f"{metric['net_utility']:.6f}",
                    row["same_stop_count"],
                    row["cold_resume_count"],
                ]
            )
    lines += [
        table(
            [
                "Split",
                "Policy",
                "Accuracy",
                "Reads / episode",
                "Net utility",
                "Same stopping step / 16",
                "Cold recoveries",
            ],
            rows,
        ),
        "",
    ]
    counters = total["counters"]
    rows = [
        [name, counters[name]]
        for name in (
            "owner_ticks",
            "actual_kernel_calls",
            "actual_ndu_calls",
            "original_journal_replay_steps",
            "event_validation_kernel_steps",
            "event_validation_ndu_calls",
            "total_native_kernel_calls",
            "total_native_ndu_calls",
            "rpc_calls",
            "request_bytes",
            "response_bytes",
            "native_errors",
        )
    ]
    lines += [
        table(["Actual native counter", "Total"], rows),
        "",
        f"The exact-child wait4 CPU total is **{total['native_child_cpu_seconds']:.6f} s**. "
        "The native-error count includes the deliberately rejected post-STOP probe for each episode. "
        "Archival integrity covers every original owner file, durable event, checkpoint witness, signal packet and native receipt.",
        "",
        "Each cold recovery starts a new native process and restores the serialized neural state and task cursor in the existing Python process. "
        "The seven standalone neural replays below separately test a fresh Python interpreter. "
        "The native profile compiles the signed decision score into the original sparse head/NDU; these runs do not establish an advantage from learning a native sparse head. "
        "Natural margin, risk and interval activity enter typed native inputs, but their independent causal benefit is not established. "
        "Q24 discrepancies remain in the evidence and are not overridden with Python actions.",
    ]
    if total["quantized_disagreements"]:
        lines += [
            "",
            "### Retained Q24 disagreements",
            "",
            table(
                [
                    "Step",
                    "Float continuation score",
                    "Q24 score",
                    "Python STOP",
                    "Native action",
                ],
                [
                    [
                        r["step"],
                        f"{r['continue_score']:.12g}",
                        r["score_q24"],
                        r["python_stop"],
                        r["native_action"],
                    ]
                    for r in total["quantized_disagreements"]
                ],
            ),
        ]
    return lines


def performance_markdown(performance):
    lines = [
        "## Full-sequence and incremental CPU inference",
        "",
        performance["scope"],
        "",
        "All latencies below are for the same B16 inputs and selected checkpoint. Batch is one complete-sequence final-logit forward; "
        "stream is the sum of genuine one-token forwards over the full sequence, excluding reset. Reset, data loading, output comparisons and recovery are retained separately. "
        "No complete-prefix recomputation is used to implement the stream.",
        "",
        f"There are **{len(performance['cases'])} preselected cases**, each with two warmups and seven measured repeats per mode. "
        f"The largest observed logit difference is **{performance['maximum_logit_error']:.9g}**; "
        f"there are **{performance['prefix_class_changes']} prefix** and **{performance['final_class_changes']} final** predicted-class changes. "
        f"The declared test uses rtol = {performance['rtol']} and atol = {performance['atol']}.",
        "",
    ]
    failures = performance["parity_failures"]
    lines += [
        ("**Retained numerical parity failures:** " + ", ".join(failures))
        if failures
        else "All preselected measured cases satisfy the declared logit, class and saved-prediction parity criteria.",
        "",
    ]
    for stage in ("representation", "scaling"):
        rows = []
        for item in performance["cases"]:
            spec = item["spec"]
            if spec["stage"] != stage:
                continue
            case = (
                spec["task"]
                if stage == "representation"
                else f"{spec['configuration']:02d} / {spec['axis']}"
            )
            rows.append(
                [
                    case,
                    spec["architecture"],
                    f"{spec['width']} × {spec['depth']} × {spec['length']}",
                    f"{1000 * item['batch_wall_seconds']['median']:.3f}",
                    f"{1000 * item['stream_wall_seconds']['median']:.3f}",
                    f"{1000 * item['stream_wall_seconds']['p95']:.3f}",
                    f"{item['stream_over_batch_wall_median']:.3f}",
                    f"{item['state_bytes'] / 1024:.3f}",
                    f"{item['parity']['max_abs_logit_error']:.3g}",
                ]
            )
        lines += [
            f"### {stage.capitalize()}",
            "",
            table(
                [
                    "Task / scale configuration",
                    "Model",
                    "W × D × T",
                    "Batch median ms",
                    "Stream median ms",
                    "Stream p95 ms",
                    "Stream / batch",
                    "State KiB",
                    "Max logit error",
                ],
                rows,
            ),
            "",
        ]
    lines += [
        "Persistent state is tensor payload only: weights, Python objects and transient allocations are excluded. "
        "The Transformer adapter retains the causal KV cache; the recurrent models retain their causal state. "
        "These CPU measurements do not compare fused GPU kernels, long-context generative quality or full multimodal pretraining.",
        "",
        "### Seven standalone neural recoveries",
        "",
    ]
    rows = []
    for item in performance["cold_replay"]:
        child = item["child_costs_seconds"]
        rows.append(
            [
                item["architecture"],
                item["exact_logits"] and item["exact_final_state"],
                f"{item['external_process_cost_seconds']['wall']:.6f}",
                f"{child['model_initialization_reload']['wall']:.6f}",
                f"{child['stream_construction_restore']['wall']:.6f}",
                f"{child['continuation']['wall']:.6f}",
                item["state_receipt"]["serialized_bytes"],
            ]
        )
    lines += [
        table(
            [
                "Model",
                "Exact logits and final state",
                "External process wall s",
                "Model reload wall s",
                "Stream restore wall s",
                "Remainder wall s",
                "Snapshot bytes",
            ],
            rows,
        ),
        "",
        "The external process interval includes interpreter startup and shutdown. Child phase times are nested and cannot be added to that total. "
        "Expected logits are retained by the parent; the child receives only model identity, checkpoint, bound stream snapshot and remaining inputs. "
        "Both the parent expected final-state digest and the child final-state digest are retained and compared.",
    ]
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    parser.add_argument("--audit")
    args = parser.parse_args()
    study = Path(args.study).resolve()
    audit_path = (
        Path(args.audit) if args.audit else study / "analysis/ONLINE_AUDIT.json"
    )
    audit = json.loads(audit_path.read_text())
    check(audit["status"] == "passed", "summary requires complete evidence audit")
    check(
        audit["performance"]["audited_cases"] == 55,
        "all preselected measurements present",
    )
    boundary, performance = (
        boundary_summary(study, audit),
        performance_summary(study, audit),
    )
    check(
        boundary["counts"]["python_policy_episodes"] == 2560,
        "all Python policy episodes",
    )
    check(
        boundary["counts"]["native_policy_episodes"] == 96, "all native subset episodes"
    )
    check(len(performance["cold_replay"]) == 7, "seven standalone neural replays")
    summary = {
        "schema": "hcsn-study002-online-summary-v1",
        "audit_sha256": sha(audit_path),
        "source_seal": audit["source_seal"],
        "boundary": boundary,
        "performance": performance,
        "external_execution": audit.get("external_execution"),
        "analysis_sources": {
            p.name: sha(p) for p in Path(__file__).parent.glob("*online*.py")
        },
    }
    output = study / "analysis"
    (output / "ONLINE_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    lines = [
        "# Study002 online stopping and incremental inference",
        "",
        f"Scientific source seal: `{audit['source_seal']}`.",
        "",
        f"Evidence audit: `{sha(audit_path)}`. Audit success establishes internal evidence consistency; numerical parity failures, if present, are retained separately.",
        "",
    ]
    lines += (
        boundary_markdown(boundary)
        + [""]
        + native_markdown(boundary)
        + [""]
        + performance_markdown(performance)
    )
    external = audit.get("external_execution")
    if external:
        lines += [
            "",
            "## External execution accounting",
            "",
            f"The ledger contains {external['all_attempts']} direct child attempts for {external['current_successful_cases']} completed continuation cases, "
            f"including {len(external['failed_attempts'])} retained failed attempts. "
            f"All-attempt child CPU is {external['all_attempt_child_cpu_seconds']:.6f} s; "
            f"summed launch-to-reap wall is {external['all_attempt_child_wall_seconds']:.6f} s. "
            "All continuation children ran serially after all training children exited.",
            "",
            external["scope"],
        ]
    (output / "ONLINE_TABLES.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "python_episodes": 2560,
                "native_episodes": 96,
                "measurements": len(performance["cases"]),
                "cold_replays": len(performance["cold_replay"]),
                "parity_failures": performance["parity_failures"],
            }
        )
    )


if __name__ == "__main__":
    main()
