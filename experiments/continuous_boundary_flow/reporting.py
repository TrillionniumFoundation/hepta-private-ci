"""Post-audit descriptive reports; never trains, selects, or reruns an arm.

Run only after confirmation, AUDIT.json, and the durable-owner study complete.
The frozen scientific source is not modified. Logged measured costs and
alternative standalone planning attributions remain separate ledgers.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

VALUE_ARMS = {
    "value_margin",
    "value_call",
    "value_dual",
    "generic_gate",
    "native_sparse",
    "event_reset",
    "dense_recurrent",
    "dp",
}
CONTROLS = {"dp", "always_keep", "always_repair", "always_stop"}
METRICS = ("gross_utility", "net_utility", "failures", "repairs", "stops", "steps")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def reject(value):
        raise ValueError(f"Nonfinite JSON in {path}: {value}")

    return json.loads(Path(path).read_text(), parse_constant=reject)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def contained(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root), "Report input escapes the frozen run")
    return path


def _empty_calibration():
    return {
        "count": 0,
        "squared_error": 0.0,
        "episodes": 0,
        "zero_exposure_episodes": 0,
        "excluded_stop_windows": 0,
        "bin_count": [0] * 10,
        "bin_probability": [0.0] * 10,
        "bin_label": [0] * 10,
    }


def _finish_calibration(acc):
    count = acc["count"]
    ece = sum(abs(p - y) for p, y in zip(acc["bin_probability"], acc["bin_label"]))
    return {
        "count": count,
        "brier": acc["squared_error"] / count if count else None,
        "ece": ece / count if count else None,
        "episodes": acc["episodes"],
        "zero_exposure_episodes": acc["zero_exposure_episodes"],
        "excluded_stop_windows": acc["excluded_stop_windows"],
        "aggregation": "pooled non-stopped policy-visited windows; descriptive",
    }


def split_calibration(root, manifest, scenarios):
    """The audit supplies combined calibration; split descriptions use same bins."""
    accumulators = {
        (arm, split): _empty_calibration()
        for arm in manifest["arms"]
        for split in manifest["splits"]
    }
    scenario_map = {row["id"]: row["spec"] for row in scenarios}
    for entry in manifest["records"]:
        path = contained(root, entry["path"])
        require(digest(path) == entry["sha256"], "Post-audit raw record digest changed")
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                key = (record["arm"], record["split"])
                acc = accumulators[key]
                context_index = record["episode_id"].split(".c", 1)[1].split(".p", 1)[0]
                context_id = (
                    f"{record['train_seed']}.{record['split']}.context{context_index}"
                )
                require(
                    scenario_map.get(context_id) == record["spec"],
                    "Scenario/raw task specification mismatch",
                )
                acc["episodes"] += 1
                exposed = False
                for step in record["steps"]:
                    p = step["predicted_risk"]
                    if p is None:
                        require(
                            step["action"] == "stop",
                            "Unexplained calibration exclusion",
                        )
                        acc["excluded_stop_windows"] += 1
                        continue
                    y = int(step["failed"])
                    require(math.isfinite(p) and 0 <= p <= 1, "Invalid audited risk")
                    exposed = True
                    index = min(int(p * 10), 9)
                    acc["count"] += 1
                    acc["squared_error"] += (p - y) ** 2
                    acc["bin_count"][index] += 1
                    acc["bin_probability"][index] += p
                    acc["bin_label"][index] += y
                acc["zero_exposure_episodes"] += not exposed
    result = {}
    for arm in manifest["arms"]:
        result[arm] = {
            split: _finish_calibration(accumulators[(arm, split)])
            for split in manifest["splits"]
        }
        total = _empty_calibration()
        for split in manifest["splits"]:
            for key, value in accumulators[(arm, split)].items():
                if isinstance(value, list):
                    total[key] = [a + b for a, b in zip(total[key], value)]
                else:
                    total[key] += value
        result[arm]["combined"] = _finish_calibration(total)
    return result


def _cost_sum(rows):
    result = {
        key: 0.0 for key in ("wall_seconds", "python_cpu_seconds", "child_cpu_seconds")
    }
    result.update(
        {
            key: 0
            for key in (
                "kernel_calls",
                "ndu_calls",
                "wire_request_bytes",
                "wire_response_bytes",
                "semantic_input_bytes",
                "fits",
            )
        }
    )
    for row in rows:
        result["wall_seconds"] += row.get("wall_seconds", 0)
        result["python_cpu_seconds"] += row.get("python_cpu_seconds", 0)
        result["child_cpu_seconds"] += row.get("completed_child_cpu_seconds", 0)
        native = (row.get("native_process") or {}).get("counters", {})
        kernels = native.get("actual_kernel_calls", row.get("actual_kernel_calls", 0))
        result["kernel_calls"] += kernels
        result["ndu_calls"] += native.get(
            "actual_ndu_calls", row.get("actual_ndu_calls", 0)
        )
        result["wire_request_bytes"] += native.get(
            "request_bytes", row.get("wire_request_bytes", 0)
        )
        result["wire_response_bytes"] += native.get(
            "response_bytes", row.get("wire_response_bytes", 0)
        )
        # Training rows omit the fixed-size semantic field; derive it from actual
        # kernel inputs. Full process JSON wire bytes are measured separately.
        result["semantic_input_bytes"] += row.get(
            "semantic_message_bytes", 160 * kernels
        )
        result["fits"] += row.get("fits", 0)
    result["cpu_seconds"] = result["python_cpu_seconds"] + result["child_cpu_seconds"]
    result["wire_total_bytes"] = (
        result["wire_request_bytes"] + result["wire_response_bytes"]
    )
    return result


def cost_report(rows, scenarios, arms, engineering):
    phases = sorted({row["phase"] for row in rows})
    phase_totals = {
        phase: _cost_sum([r for r in rows if r["phase"] == phase]) for phase in phases
    }
    shared = [r for r in rows if r.get("arm") == "shared"]
    scenario_setup = {
        "model_build_cpu_seconds": 0.0,
        "dp_cpu_seconds": 0.0,
        "model_build_wall_seconds": 0.0,
        "dp_wall_seconds": 0.0,
        "contexts": len(scenarios),
    }
    for context in scenarios:
        scenario_setup["model_build_cpu_seconds"] += context["model_build_cost"][
            "cpu_seconds"
        ]
        scenario_setup["model_build_wall_seconds"] += context["model_build_cost"][
            "wall_seconds"
        ]
        scenario_setup["dp_cpu_seconds"] += context["planning_cost"]["cpu_seconds"]
        scenario_setup["dp_wall_seconds"] += context["planning_cost"]["wall_seconds"]
    confirmation_shared = [
        r for r in shared if r["phase"] == "solver_setup_confirmation"
    ]
    for field, scenario_field in (
        ("model_build_cpu_seconds", "model_build_cpu_seconds"),
        ("dp_planning_cpu_seconds", "dp_cpu_seconds"),
    ):
        logged = sum(r[field] for r in confirmation_shared)
        require(
            math.isclose(
                logged, scenario_setup[scenario_field], rel_tol=1e-9, abs_tol=1e-9
            ),
            "Scenario setup sub-timers disagree with audited shared costs",
        )
    by_arm = {}
    for arm in arms:
        own = [r for r in rows if r.get("arm") == arm]
        train = _cost_sum([r for r in own if r["phase"] == "training_and_development"])
        inference = _cost_sum([r for r in own if r["phase"] == "evaluation"])
        serialization = _cost_sum([r for r in own if r["phase"] == "serialization"])
        planned = arm in VALUE_ARMS
        extra_cpu = (
            scenario_setup["model_build_cpu_seconds"] + scenario_setup["dp_cpu_seconds"]
            if planned
            else 0.0
        )
        extra_wall = (
            scenario_setup["model_build_wall_seconds"]
            + scenario_setup["dp_wall_seconds"]
            if planned
            else 0.0
        )
        by_arm[arm] = {
            "training_development_measured": train,
            "confirmation_rollout_measured": inference,
            "serialization_measured": serialization,
            "all_own_phases_measured": _cost_sum(own),
            "standalone_attribution": {
                "dp_context_solves": len(scenarios) if planned else 0,
                "model_and_dp_setup_cpu_seconds": extra_cpu,
                "model_and_dp_setup_wall_seconds": extra_wall,
                "rollout_plus_setup_cpu_seconds": inference["cpu_seconds"] + extra_cpu,
                "rollout_plus_setup_wall_seconds": inference["wall_seconds"]
                + extra_wall,
                "scope": "alternative per-arm planning attribution; never add across arms or into actual measured total",
            },
        }
    measured = _cost_sum(rows)
    eng_cost = engineering["cost"]
    engineering_cpu = (
        eng_cost["python_cpu_seconds"] + eng_cost["completed_child_cpu_seconds"]
    )
    return {
        "actual_logged_scientific_total": measured,
        "actual_by_phase": phase_totals,
        "actual_shared_phases": _cost_sum(shared),
        "shared_training_model_build_cpu_seconds": sum(
            r.get("model_build_cpu_seconds", 0)
            for r in shared
            if r["phase"] == "solver_setup_training"
        ),
        "shared_training_dp_cpu_seconds": sum(
            r.get("dp_planning_cpu_seconds", 0)
            for r in shared
            if r["phase"] == "solver_setup_training"
        ),
        "shared_confirmation_setup_subtimers": scenario_setup,
        "by_arm": by_arm,
        "additional_engineering": {
            "cpu_seconds": engineering_cpu,
            "wall_seconds": eng_cost["wall_seconds"],
            "native_counters": engineering["native_total_counters"],
        },
        "logged_science_plus_engineering_cpu_seconds": measured["cpu_seconds"]
        + engineering_cpu,
        "logged_science_plus_engineering_wall_seconds": measured["wall_seconds"]
        + eng_cost["wall_seconds"],
        "accounting": [
            "Measured actual total sums outer nonoverlapping cost rows once; nested native CPU and model/DP subtimers are not added again.",
            "Evaluation CPU includes sampled environment, adapter, native inference and process/serialization communication; it is not isolated neural compute.",
            "Per-arm standalone setup assigns one model build plus one DP solve per context to value arms and DP; fixed/direct and constant policies receive no inference DP charge.",
            "Shared environment/model overhead is already in actual shared setup; standalone attributions are alternative bookkeeping, not extra measured execution.",
            "Wall totals are sums of logged phase windows, not a measured end-to-end clock including unlogged gaps.",
            "Training semantic input bytes use 160 times actual kernel inputs when absent; full process request/response wire bytes are measured.",
            "No energy measurement or CPU-to-utility conversion is claimed.",
        ],
    }


def aborted_preconfirmation_costs(run_dir):
    """Read completed cost receipts only; never old returns or selections."""
    relative = "history/study-001/costs.jsonl"
    path = Path(run_dir) / relative
    if not path.is_file():
        return {
            "available": False,
            "path": relative,
            "lower_bound": True,
            "reason": "Interrupted-run cost ledger is unavailable, not zero",
        }
    raw = path.read_bytes()
    rows, tail_bytes, roundoff = [], 0, []
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            tail_bytes += len(line)
            continue
        if not line.strip():
            continue
        row = json.loads(line)
        require(
            row["phase"] in {"solver_setup_training", "training_and_development"},
            "Interrupted-run ledger contains a non-preconfirmation phase",
        )
        for field in (
            "wall_seconds",
            "python_cpu_seconds",
            "completed_child_cpu_seconds",
        ):
            if field == "completed_child_cpu_seconds" and -1e-12 <= row[field] < 0:
                roundoff.append(
                    {"cost_row": number, "recorded": row[field], "used": 0.0}
                )
                row[field] = 0.0
            require(
                math.isfinite(row[field]) and row[field] >= 0,
                "Interrupted-run cost receipt is invalid",
            )
        rows.append(row)
    return {
        "available": True,
        "path": relative,
        "sha256": digest(path),
        "completed_phase_rows": len(rows),
        "uncommitted_tail_bytes": tail_bytes,
        "child_cpu_near_zero_roundoff_corrections": roundoff,
        "known_logged_cost": _cost_sum(rows),
        "lower_bound": True,
        "by_phase": {
            phase: _cost_sum([r for r in rows if r["phase"] == phase])
            for phase in sorted({r["phase"] for r in rows})
        },
        "included_in_valid_study_cost": False,
        "effect_or_selection_data_read": False,
        "scope": "Completed preconfirmation phase receipts only; the interrupted arm's unfinished outer window has no complete receipt. This is a lower bound, not the full abandoned-run cost.",
    }


def parameter_budget(arm):
    neural = arm not in CONTROLS
    return {
        "trained_head_scalars": 42 if neural else 0,
        "trained_boundary_scalars": 20 if arm == "learned_margin" else 0,
        "total_trained_scalars": 62 if arm == "learned_margin" else 42 if neural else 0,
        "fixed_encoder_scalars": 420 if neural else 0,
        "fixed_extra_mixing_scalars": 42
        if arm == "generic_gate"
        else 78
        if arm == "dense_recurrent"
        else 0,
        "additional_adapter_state_dimensions": 0
        if arm == "native_sparse" or not neural
        else 6,
        "native_state_width": 20 if neural else 0,
        "stop_head": "literal zero; excluded from active parameter budget",
    }


def build_summary(run_dir, engineering_path=None, amendment_path=None):
    root = Path(run_dir).resolve()
    audit_path = root / "AUDIT.json"
    audit = read_json(audit_path)  # Refuse to touch outcomes before audit exists.
    require(
        audit["integrity_passed"] and audit["selection_seal_verified"],
        "Completed sealed independent audit required",
    )
    manifest_path, scenario_path, cost_path = (
        root / "manifest.json",
        root / "SCENARIOS.json",
        root / "costs.jsonl",
    )
    manifest, scenarios = read_json(manifest_path), read_json(scenario_path)
    require(
        digest(manifest_path) == audit["manifest_sha256"],
        "Manifest changed after audit",
    )
    require(
        digest(cost_path) == manifest["costs_sha256"], "Cost ledger changed after audit"
    )
    rows = [json.loads(line) for line in cost_path.read_text().splitlines() if line]
    require(
        rows == audit["costs"]["records"], "Report cost rows differ from audited rows"
    )
    protocol_path = contained(root, manifest.get("protocol_path", "protocol.json"))
    protocol = read_json(protocol_path)
    require(
        digest(protocol_path) == audit["protocol_sha256"],
        "Protocol changed after audit",
    )
    require(
        {r["id"] for r in scenarios} == set(protocol["phase_ids"]["confirmation"]),
        "Scenario context identities differ from protocol",
    )
    engineering_path = (
        Path(engineering_path)
        if engineering_path
        else root / "engineering" / "SUMMARY.json"
    )
    engineering = read_json(engineering_path)
    require(
        engineering["manifest_sha256"] == audit["manifest_sha256"],
        "Engineering study belongs to another scientific run",
    )
    risk = split_calibration(root, manifest, scenarios)
    performance = {}
    for arm in manifest["arms"]:
        metrics = audit["arm_metrics"][arm]
        pooled = metrics["calibration_pooled_steps_descriptive"]
        for field in ("brier", "ece"):
            observed, expected = risk[arm]["combined"][field], pooled[field]
            require(
                (observed is None and expected is None)
                or math.isclose(observed, expected, abs_tol=1e-9),
                "Split risk reconstruction differs from audit",
            )
        performance[arm] = {
            split: {**metrics["split_metrics"][split], "risk": risk[arm][split]}
            for split in manifest["splits"]
        }
        performance[arm]["combined"] = {
            **{k: metrics[k] for k in METRICS},
            "risk": risk[arm]["combined"],
            "brier_equal_episode_audited": metrics["brier_equal_episode"],
            "episode_count": metrics["episode_count"],
            "stability_failure_episodes": metrics["stability_failure_episodes"],
        }
        performance[arm]["seed_metrics"] = metrics["seed_metrics"]
        performance[arm]["parameter_budget"] = parameter_budget(arm)
        performance[arm]["audited_counters"] = metrics["total_counters"]
    default_amendment = (
        Path(__file__).resolve().parent / "preflight" / "DEADLINE_AMENDMENT.json"
    )
    amendment_path = Path(amendment_path) if amendment_path else default_amendment
    amendment = read_json(amendment_path)
    require(
        amendment["confirmation_observed"] is False
        and amendment["partial_training_preserved"],
        "Pre-confirmation amendment provenance required",
    )
    inputs = {
        "audit": audit_path,
        "manifest": manifest_path,
        "protocol": protocol_path,
        "scenarios": scenario_path,
        "costs": cost_path,
        "engineering": engineering_path,
        "preconfirmation_amendment": amendment_path,
        "reporting_tool": Path(__file__),
    }
    costs = cost_report(rows, scenarios, manifest["arms"], engineering)
    aborted = aborted_preconfirmation_costs(root)
    recorded_work = None
    if aborted["available"]:
        inputs["aborted_preconfirmation_costs"] = root / aborted["path"]
        known = aborted["known_logged_cost"]
        recorded_work = {
            "cpu_seconds": costs["logged_science_plus_engineering_cpu_seconds"]
            + known["cpu_seconds"],
            "summed_logged_wall_seconds": costs[
                "logged_science_plus_engineering_wall_seconds"
            ]
            + known["wall_seconds"],
            "lower_bound": True,
            "scope": "Valid scientific run + repeated engineering checks + completed aborted-run receipts; excludes the unfinished interrupted window and unlogged R&D, compilation and audit. Not complete total elapsed time.",
        }
    return {
        "schema": "hepta.continuous-boundary.results.v1",
        "run_name": root.name,
        "inputs_sha256": {key: digest(path) for key, path in inputs.items()},
        "manifest_sha256": audit["manifest_sha256"],
        "protocol_sha256": audit["protocol_sha256"],
        "source_seal_sha256": manifest["source_seal_sha256"],
        "integrity_passed": True,
        "n_independent_training_seeds": audit["n_training_seeds"],
        "raw_episode_count": audit["raw_episode_count"],
        "split_weights": manifest["split_weights"],
        "arm_order": manifest["arms"],
        "performance": performance,
        "primary_comparisons": audit["primary_comparisons"],
        "primary_gates_passed": sum(
            r["benefit_gate_passed"] for r in audit["primary_comparisons"]
        ),
        "costs": costs,
        "aborted_preconfirmation_costs": aborted,
        "recorded_work_cost_lower_bound": recorded_work,
        "engineering": engineering,
        "preconfirmation_amendment": amendment,
        "risk_scope": audit["scope"]["calibration_limit"],
        "limitations": [
            "Known-model finite-window task; DP-derived boundaries/channels use public-model planning and their measured cost is disclosed.",
            "Generic controls are frozen seeded reservoirs plus fitted readouts, not fully trained GRUs, neural ODEs or end-to-end BPTT.",
            "Risk is the same analytic after-action predictor on different policy-visited states; Brier/ECE differences do not establish learned risk prediction gains.",
            "Primary inference uses independent seed pairs; descriptive arm rankings and split calibration are not extra significance tests.",
            "Physical paths remain sampled; continuous flow is the adapter's previous expected-event input, not an eliminated event process.",
            "Durable-owner replay adds engineering evidence and zero independent scientific samples.",
            "Interrupted study-001 training was retained; its outcomes were not used in this report or to select confirmation analyses.",
            "Logged timings and wire counts do not measure energy or certify a universal total-cost advantage.",
        ],
    }


def _number(value, places=4):
    return "—" if value is None else f"{value:,.{places}f}"


def _table(headers, rows):
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *["| " + " | ".join(map(str, row)) + " |" for row in rows],
    ]


def render_markdown(summary):
    costs, performance, arms = (
        summary["costs"],
        summary["performance"],
        summary["arm_order"],
    )
    lines = [
        "# Continuous-boundary confirmation results",
        "",
        f"Run `{summary['run_name']}`: independent audit passed; **{summary['primary_gates_passed']}/3 registered primary benefit gates passed**. "
        f"There are {summary['n_independent_training_seeds']} independent training seeds and {summary['raw_episode_count']:,} audited episodes across all arms.",
        "",
        "## Pre-confirmation amendment",
        "",
        "Before confirmation data existed, the common deadline input changed from per-episode remaining fraction to `remaining_windows/16`, so every arm could recover the absolute remaining duration with `dt`. "
        "The interrupted training-only `study-001` was retained. This report uses the new sealed run; it does not use the old run's training effects as evidence.",
        "",
        "## Registered paired comparisons",
        "",
        "Differences are in mean message-priced net utility, paired by independent seed. Intervals use the registered two-sided Bonferroni Student-t procedure: 95% simultaneous family coverage across three comparisons. "
        "A gate requires the lower interval endpoint to exceed 0.005 and no recorded stability failure in either arm.",
        "",
    ]
    rows = []
    for comparison in summary["primary_comparisons"]:
        interval = comparison["simultaneous_interval"]
        rows.append(
            [
                comparison["name"],
                f"`{comparison['treatment']}` − `{comparison['control']}`",
                _number(comparison["mean_difference"]),
                f"[{_number(interval[0])}, {_number(interval[1])}]",
                "yes" if comparison["minimum_effect_established"] else "no",
                "yes" if comparison["stability_passed"] else "no",
                "PASS" if comparison["benefit_gate_passed"] else "NOT ESTABLISHED",
            ]
        )
    lines += _table(
        [
            "Comparison",
            "Pair",
            "Δ net",
            "Simultaneous interval",
            "Minimum effect",
            "Stability",
            "Gate",
        ],
        rows,
    )
    for split, title in (
        ("test_id", "ID"),
        ("test_ood", "OOD"),
        ("combined", "Combined, equal ID/OOD weights"),
    ):
        lines += [
            "",
            f"## {title}",
            "",
            "Utilities and event counts are per episode. Stop is the percentage of episodes that stop. Brier/ECE pool non-stopped visited windows and are descriptive.",
            "",
        ]
        rows = []
        for arm in arms:
            item = performance[arm][split]
            rows.append(
                [
                    f"`{arm}`",
                    _number(item["gross_utility"]),
                    _number(item["net_utility"]),
                    _number(item["failures"], 3),
                    _number(item["repairs"], 3),
                    _number(100 * item["stops"], 1),
                    _number(item["risk"]["brier"]),
                    _number(item["risk"]["ece"]),
                    f"{item['risk']['count']:,}",
                ]
            )
        lines += _table(
            [
                "Arm",
                "Gross",
                "Net",
                "Failures",
                "Repairs",
                "Stop %",
                "Brier",
                "ECE",
                "Risk windows",
            ],
            rows,
        )
    measured = costs["actual_logged_scientific_total"]
    lines += [
        "",
        "## Measured computation and communication",
        "",
        f"Logged scientific phases total **{_number(measured['cpu_seconds'], 2)} CPU seconds** and **{_number(measured['wall_seconds'], 2)} summed wall seconds**. "
        f"They executed {measured['kernel_calls']:,} native kernel calls and {measured['ndu_calls']:,} NDU calls; full process JSON wire traffic was {measured['wire_total_bytes']:,} bytes "
        f"({measured['wire_request_bytes']:,} request + {measured['wire_response_bytes']:,} response). "
        "Wall sums are logged phase windows, not an uninstrumented end-to-end elapsed clock; CPU is not converted to energy.",
        "",
    ]
    rows = []
    for phase, item in costs["actual_by_phase"].items():
        rows.append(
            [
                phase,
                _number(item["cpu_seconds"], 2),
                _number(item["wall_seconds"], 2),
                f"{item['kernel_calls']:,}",
                f"{item['ndu_calls']:,}",
                f"{item['wire_total_bytes']:,}",
            ]
        )
    lines += _table(
        ["Actual phase", "CPU s", "Wall s", "Kernel calls", "NDU calls", "Wire bytes"],
        rows,
    )
    setup = costs["shared_confirmation_setup_subtimers"]
    lines += [
        "",
        f"The {setup['contexts']} confirmation contexts used {_number(setup['model_build_cpu_seconds'], 3)} CPU seconds for model construction and {_number(setup['dp_cpu_seconds'], 3)} for DP. "
        "These are included subtimers of the shared setup row, never extra additions to the actual total. The following per-arm planning column is an alternative standalone attribution: value arms and DP receive one model build plus one solve per context; fixed/direct policies receive no inference DP charge.",
        "",
    ]
    rows = []
    for arm in arms:
        item = costs["by_arm"][arm]
        rows.append(
            [
                f"`{arm}`",
                _number(item["training_development_measured"]["cpu_seconds"], 2),
                _number(item["confirmation_rollout_measured"]["cpu_seconds"], 2),
                _number(
                    item["standalone_attribution"]["model_and_dp_setup_cpu_seconds"], 3
                ),
                _number(
                    item["standalone_attribution"]["rollout_plus_setup_cpu_seconds"], 2
                ),
                f"{item['confirmation_rollout_measured']['wire_total_bytes']:,}",
            ]
        )
    lines += _table(
        [
            "Arm",
            "Train/dev CPU s",
            "Rollout CPU s",
            "Standalone setup s",
            "Rollout + setup s",
            "Eval wire bytes",
        ],
        rows,
    )
    lines += [
        "",
        "Rollout costs include the environment sampler and adapter. Shared environment/model overhead must not be added again. Standalone columns must not be summed across arms or into measured totals. "
        "The net-utility price applies only to 160-byte numerical feature payloads at the registered rate, not JSON framing, CPU or power.",
        "",
        "## Parameter and comparison scope",
        "",
        "Each neural arm fits 42 wait/repair-head scalars; stop is literal zero. `learned_margin` adds 20 fitted boundary coefficients (62 trained scalars total). "
        "The common encoder has 420 frozen coefficients. `generic_gate` and `dense_recurrent` add 42 and 78 frozen seeded mixing coefficients respectively. "
        "These controls are fixed reservoirs plus learned readouts; the results do not establish superiority over fully trained GRUs or end-to-end BPTT.",
        "",
        "Risk uses the same analytic conditional first-hit formula on each policy's visited states. Brier/ECE differences are not risk-learning gains; zero-exposure STOP windows are excluded, not scored as perfect predictions.",
        "",
        "## Durable owner study",
        "",
    ]
    engineering = summary["engineering"]
    aborted = summary["aborted_preconfirmation_costs"]
    abandoned_text = "The interrupted-run cost ledger is unavailable; its cost is not treated as zero."
    if aborted["available"]:
        known, work = (
            aborted["known_logged_cost"],
            summary["recorded_work_cost_lower_bound"],
        )
        abandoned_text = (
            f"Retained `study-001` contains {aborted['completed_phase_rows']} completed cost receipts: "
            f"{_number(known['cpu_seconds'], 2)} CPU seconds and {_number(known['wall_seconds'], 2)} logged wall seconds. "
            "This is a lower bound because the interrupted arm's unfinished cost window has no complete receipt. "
            "These costs are excluded from the valid study's totals. "
            f"Valid science + engineering + known abandoned receipts record at least {_number(work['cpu_seconds'], 2)} CPU seconds "
            f"and {_number(work['summed_logged_wall_seconds'], 2)} summed wall-window seconds. "
            "This excludes unlogged R&D, compilation, audit and the unfinished window; it is not complete total elapsed time. "
            "Only old cost receipts were read, never old development returns or selection results."
        )
    lines += [
        f"Engineering parity {'passed' if engineering['passed'] else 'did not pass'} for {engineering['engineering_episode_count']} reused episodes; "
        f"{engineering['cold_resumes']} cold resumes, {engineering['continued_after_resume_episodes']} episodes with subsequent execution, "
        f"{engineering['terminal_only_resume_episodes']} terminal-only resumes, and {engineering['stop_rejection_checks']} post-STOP rejection checks. "
        f"It adds zero independent scientific samples and {_number(costs['additional_engineering']['cpu_seconds'], 2)} separately measured CPU seconds. "
        "Native logical ticks are 10 ms; physical task windows use their separate `dt`.",
        "",
        "## Interrupted preconfirmation work: separately recorded lower bound",
        "",
        abandoned_text,
        "",
        "## Evidence",
        "",
        "The JSON summary preserves split and seed metrics, all primary intervals and gates, parameter budgets, cost attribution, source hashes, and the amendment record. "
        "The audit is bound to the trusted manifest and raw records; it is not a cryptographic signature against wholesale replacement of the bundle.",
        "",
    ]
    return "\n".join(lines)


def generate_report(run_dir, output=None, engineering_path=None, amendment_path=None):
    summary = build_summary(run_dir, engineering_path, amendment_path)
    output = Path(output) if output else Path(run_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "SUMMARY.json": canonical(summary) + b"\n",
        "RESULTS.md": render_markdown(summary).encode(),
    }
    for name, data in artifacts.items():
        path = output / name
        if path.exists():
            require(path.read_bytes() == data, f"Existing report differs: {path}")
        else:
            with path.open("xb") as stream:
                stream.write(data)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--engineering", type=Path)
    parser.add_argument("--amendment", type=Path)
    args = parser.parse_args()
    result = generate_report(
        args.run_dir, args.output, args.engineering, args.amendment
    )
    print(
        json.dumps(
            {
                "run": result["run_name"],
                "primary_gates_passed": result["primary_gates_passed"],
                "independent_seeds": result["n_independent_training_seeds"],
            }
        )
    )


if __name__ == "__main__":
    main()
