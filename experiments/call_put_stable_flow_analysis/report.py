"""Build the Chinese scientific report only from completed, bound evidence.

This module never trains, selects, scores or benchmarks. Missing prerequisites
stop execution before any held-out result is opened. No final-audit receipt is
an input: the independent final audit is deliberately downstream of this report.
"""

import argparse
import hashlib
import io
import json
import math
import platform
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np

from .report_figures import figures
from .report_sections import render

EVIDENCE = Path("research_evidence/hepta_stable_flow_20261029")
STUDY = EVIDENCE / "formal_run001"
NUMERICS = EVIDENCE / "trained_numerics_appendix001"
RUNTIME = EVIDENCE / "inference_cost_appendix001"
ANALYSIS = Path("experiments/call_put_stable_flow_analysis")
TASKS = ("selective_copy", "mqar")
ARMS = ("analytic", "matched_c1", "sigmoid", "ordinary", "frozen_flow")
REGIMES = ("cpu30", "updates384")
SEEDS = (81301, 81302, 81303)
GROUPS = ("all", "content", "boundary_input", "boundary_dynamics", "rate_head")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Inputs:
    """Record every consumed scientific file, source and rendering asset."""

    def __init__(self, root):
        self.root, self.records = root.resolve(), {}

    def path(self, name):
        path = self.root / name
        require(path.resolve().is_relative_to(self.root), "Input escapes repository")
        relative = path.relative_to(self.root).as_posix()
        prefixes = (
            "experiments/call_put_stable_flow/",
            "experiments/call_put_stable_flow_appendix/",
            "experiments/call_put_stable_flow_analysis/",
            str(EVIDENCE) + "/",
        )
        require(
            relative.startswith(prefixes)
            and not relative.startswith(str(EVIDENCE / "releases") + "/")
            and ".." not in path.relative_to(self.root).parts,
            "Report input is outside the self-contained complete archive scope",
        )
        require(
            not path.is_symlink() and path.is_file(), f"Missing regular input: {name}"
        )
        return path

    def read(self, name, expected=None, role="evidence"):
        path = self.path(name)
        data = path.read_bytes()
        name = path.relative_to(self.root).as_posix()
        digest = sha(data)
        require(expected is None or digest == expected, f"Digest mismatch: {name}")
        previous = self.records.get(name)
        require(
            previous is None or previous["sha256"] == digest, f"Input changed: {name}"
        )
        roles = sorted(set((previous or {}).get("roles", [])) | {role})
        self.records[name] = {
            "path": name,
            "bytes": len(data),
            "sha256": digest,
            "roles": roles,
        }
        return data

    def json(self, name, expected=None, role="evidence"):
        return json.loads(self.read(name, expected, role))

    def arrays(self, name, expected=None):
        with np.load(
            io.BytesIO(self.read(name, expected)), allow_pickle=False
        ) as archive:
            result = {key: archive[key].copy() for key in archive.files}
        require(
            all(np.isfinite(a).all() for a in result.values()),
            f"Nonfinite arrays: {name}",
        )
        return result

    def unchanged(self):
        for name, record in self.records.items():
            require(
                sha(self.path(name).read_bytes()) == record["sha256"],
                f"Changed input: {name}",
            )

    def manifest(self):
        return [self.records[name] for name in sorted(self.records)]


def prerequisites(root):
    needed = [
        STUDY / "results.json",
        STUDY / "selection_seal.json",
        NUMERICS / "execution/summary.json",
        RUNTIME / "execution/summary.json",
        RUNTIME / "quality_join.json",
    ]
    missing = [str(name) for name in needed if not (root / name).is_file()]
    require(
        not missing,
        "Report prerequisites missing; no result read: " + ", ".join(missing),
    )


def statistics(values):
    values = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(values.mean()),
        "sample_sd": float(values.std(ddof=1)),
        "seed_values": values.tolist(),
    }


def identity(row):
    return tuple(row[name] for name in ("task", "arm", "seed", "regime"))


def validate_scores(inputs, primary, selected):
    rows = primary["results"]
    expected = {
        (t, a, s, r) for t in TASKS for a in ARMS for s in SEEDS for r in REGIMES
    }
    require(
        len(rows) == 60 and {identity(r) for r in rows} == expected,
        "Primary scope mismatch",
    )
    lookup = {identity(row): row for row in selected["selected"]}
    for row in rows:
        chosen = lookup[identity(row)]
        require(
            all(row[k] == chosen[k] for k in chosen),
            "Scored identity differs from selection",
        )
        data = inputs.arrays(STUDY / row["prediction_file"], row["prediction_sha256"])
        logits, targets = data["logits"].astype(np.float64), data["targets"]
        mask, hit = targets != -100, logits.argmax(-1) == targets
        query_logits, query_targets = logits[mask], targets[mask]
        ce = (
            np.logaddexp.reduce(query_logits, axis=-1)
            - query_logits[np.arange(mask.sum()), query_targets]
        )
        recalculated = {
            "accuracy": float(hit[mask].mean()),
            "cross_entropy": float(ce.mean()),
            "sequence_accuracy": float((hit | ~mask).all(axis=1).mean()),
            "queries": int(mask.sum()),
            "examples": len(logits),
        }
        for key, value in recalculated.items():
            require(
                abs(value - row["test"][key])
                <= (1e-5 if key == "cross_entropy" else 1e-12),
                f"Prediction/score mismatch: {row['id']}, {key}",
            )
    require(
        len(primary["step0"]) == 30 and len(primary["comparisons"]) == 24,
        "Incomplete score tables",
    )


def aggregate(primary, protocol):
    indexed = {identity(row): row for row in primary["results"]}
    comparison_keys = [
        tuple(row[name] for name in ("task", "regime", "comparator", "metric"))
        for row in primary["comparisons"]
    ]
    expected_comparisons = {
        (task, regime, comparator, metric)
        for task in TASKS
        for regime in REGIMES
        for comparator in ("matched_c1", "sigmoid", "ordinary")
        for metric in ("accuracy", "cross_entropy")
    }
    require(
        len(comparison_keys) == len(expected_comparisons)
        and len(set(comparison_keys)) == len(comparison_keys)
        and set(comparison_keys) == expected_comparisons,
        "Comparisons must uniquely cover all 24 registered identities",
    )
    grouped = []
    for task in TASKS:
        for regime in REGIMES:
            for arm in ARMS:
                rows = [indexed[task, arm, seed, regime] for seed in SEEDS]
                grouped.append(
                    {
                        "task": task,
                        "arm": arm,
                        "regime": regime,
                        "seeds": list(SEEDS),
                        "metrics": {
                            metric: statistics([r["test"][metric] for r in rows])
                            for metric in (
                                "accuracy",
                                "cross_entropy",
                                "sequence_accuracy",
                            )
                        },
                        "validation_accuracy": statistics(
                            [r["validation"]["accuracy"] for r in rows]
                        ),
                    }
                )
    for comparison in primary["comparisons"]:
        task, regime, comparator, metric = (
            comparison[k] for k in ("task", "regime", "comparator", "metric")
        )
        left = [indexed[task, "analytic", seed, regime] for seed in SEEDS]
        right = [indexed[task, comparator, seed, regime] for seed in SEEDS]
        differences = np.array(
            [a["test"][metric] - b["test"][metric] for a, b in zip(left, right)]
        )
        differences *= -1 if metric == "cross_entropy" else 1
        family = 4 if comparator == "matched_c1" else 8
        z = 1 - 0.05 / family
        critical = math.sqrt(2) * z / math.sqrt(1 - z * z)
        mean, radius = (
            float(differences.mean()),
            critical * float(differences.std(ddof=1)) / math.sqrt(3),
        )
        quality = all(r["validation"]["accuracy"] >= 0.9 for r in left + right) and all(
            r["test"]["accuracy"] >= 0.9 for r in left
        )
        passed = (
            quality
            and mean - radius > 0
            and mean >= protocol["minimum_mean_effect"][metric]
        )
        require(
            np.allclose(
                differences, comparison["paired_seed_differences"], rtol=0, atol=1e-12
            )
            and np.allclose(
                [mean - radius, mean + radius],
                comparison["adjusted_ci"],
                rtol=0,
                atol=1e-12,
            )
            and math.isclose(comparison["mean"], mean, rel_tol=0, abs_tol=1e-12)
            and comparison["family_size"] == family
            and comparison["metric_improvement_gate"] == passed
            and comparison["quality_floor_passed"] == quality,
            "Comparison contract mismatch",
        )
    return grouped


def training(inputs, protocol, seal):
    rows, outcomes, sessions, unsuccessful = [], {}, [], []
    for path in sorted(
        (inputs.root / STUDY / "orchestration").glob(
            "session_*/training_orchestration_summary.json"
        )
    ):
        summary = inputs.json(path.relative_to(inputs.root))
        sessions.append({"path": str(path.relative_to(inputs.root)), **summary})
        for identifier, outcome in summary["outcomes"].items():
            if "verification" in outcome:
                require(
                    identifier not in outcomes, "Duplicate successful candidate cost"
                )
                outcomes[identifier] = outcome
            else:
                unsuccessful.append(outcome)
    require(
        len(outcomes) == 60
        and any(s["status"] == "all_60_training_complete" for s in sessions),
        "Full training-process cost receipts are required",
    )
    for specification in protocol["candidates"]:
        identifier, folder = (
            specification["id"],
            STUDY / "candidates" / specification["id"],
        )
        row = inputs.json(folder / "complete.json", seal["complete_sha256"][identifier])
        require(
            row["status"] == "complete" and row["specification"] == specification,
            "Candidate identity mismatch",
        )
        for checkpoint in row["checkpoints"].values():
            inputs.read(
                folder / checkpoint["file"],
                checkpoint["sha256"],
                "checkpoint-byte-verification",
            )
        inputs.read(folder / "training_trace.jsonl", role="training-trace")
        diagnostic = inputs.arrays(
            folder / "final_train_diagnostics.npz", row["diagnostic_sha256"]
        )
        trace = diagnostic["flow_rate_trace"]
        margin, call = trace[..., 0], trace[..., 1]
        changes = margin[:, 1:] * margin[:, :-1] < 0
        observation = {
            "episodes": len(trace),
            "ticks": trace.shape[1],
            "margin_min": float(margin.min()),
            "margin_max": float(margin.max()),
            "call_min": float(call.min()),
            "call_max": float(call.max()),
            "sampled_post_tick_sign_changes": int(changes.sum()),
            "episodes_with_sampled_sign_change": int(
                changes.reshape(len(trace), -1).any(axis=1).sum()
            ),
            "call_identically_zero_on_probe": bool(np.all(call == 0)),
            "not_selected_checkpoint_diagnostic": True,
        }
        rows.append(
            {
                **row,
                "process_cost": outcomes[identifier],
                "observed_diagnostic": observation,
            }
        )
    phases = []
    for path in sorted((inputs.root / STUDY / "phase_execution").glob("*/finish.json")):
        finish = inputs.json(path.relative_to(inputs.root))
        for name, digest in finish["outputs"].items():
            inputs.read(STUDY / name, digest)
        for name in ("stdout", "stderr"):
            inputs.read(
                path.parent.relative_to(inputs.root) / f"{name}.log",
                finish[name + "_sha256"],
                "phase-log",
            )
        phases.append({"receipt": str(path.relative_to(inputs.root)), **finish})
    require(
        {p["phase"] for p in phases if p["returncode"] == 0} >= {"select", "score"},
        "Selection/score cost receipts missing",
    )
    return {
        "candidates": rows,
        "orchestration_sessions": sessions,
        "phase_execution": phases,
        "unsuccessful_launches": unsuccessful,
        "training_update_cpu_seconds": sum(r["training_cpu_seconds"] for r in rows),
        "candidate_internal_total_cpu_seconds": sum(
            r["total_process_cpu_seconds"] for r in rows
        ),
        "successful_child_total_cpu_seconds": sum(
            r["child_total_cpu_seconds"] for r in outcomes.values()
        ),
        "unsuccessful_child_total_cpu_seconds": sum(
            r.get("child_total_cpu_seconds", 0) for r in unsuccessful
        ),
        "orchestration_session_wall_seconds_sum": sum(
            s["wall_seconds"] for s in sessions
        ),
        "selection_and_scoring_child_cpu_seconds": sum(
            p["child_total_cpu_seconds"] for p in phases
        ),
        "maximum_successful_child_peak_rss_bytes": max(
            r["peak_rss_bytes"] for r in outcomes.values()
        ),
        "not_total_research_energy_or_whole_project_cost": True,
    }


def numerical_appendix(inputs):
    protocol = inputs.json(NUMERICS / "protocol.json")
    inputs.json(NUMERICS / "registration_seal.json")
    inputs.json(NUMERICS / "execution/execution_binding.json")
    summary = inputs.json(NUMERICS / "execution/summary.json")
    require(
        summary["registered_aliases"] == 24
        and summary["dop_aliases"] == 8
        and summary["execution_errors"] == 0,
        "Numerical execution incomplete",
    )
    aliases, dop = [], []
    for record in summary["records"]:
        folder = NUMERICS / record["folder"]
        inputs.json(folder / "receipt.json", record["receipt_sha256"])
        for name, digest in record["raw_artifacts_sha256"].items():
            inputs.read(folder / name, digest, "numerical-raw-arrays")
        for alias in record["aliases"]:
            aliases.append(
                {
                    "alias": alias,
                    "folder": str(folder),
                    "end_to_end": record["end_to_end"],
                }
            )
            if alias["seed"] == protocol["independent_flow"]["seed"]:
                dop.append(
                    {
                        "alias": alias,
                        "folder": str(folder),
                        **record["independent_flow"],
                    }
                )
    require(
        len(aliases) == 24 and len(dop) == 8, "Numerical alias expansion incomplete"
    )
    return {
        "protocol": protocol,
        "summary": summary,
        "aliases": aliases,
        "dop": dop,
        "end_to_end_alias_status": dict(
            Counter(r["end_to_end"]["status"] for r in aliases)
        ),
        "flow_alias_status": dict(Counter(r["status"] for r in dop)),
        "measured_checkpoint_cpu_seconds": sum(
            r["cpu_seconds"] for r in summary["records"]
        ),
    }


def runtime_appendix(inputs, primary_digest):
    protocol = inputs.json(RUNTIME / "protocol.json")
    inputs.json(RUNTIME / "registration_seal.json")
    summary = inputs.json(RUNTIME / "execution/summary.json")
    require(
        summary["status"] == "complete" and summary["alias_count"] == 20,
        "Runtime execution incomplete",
    )
    require(
        summary["timed_repetitions_per_case"] == 11
        and summary["warmups_per_case"] == 3,
        "Runtime repetition mismatch",
    )
    raw = inputs.arrays(
        RUNTIME / "execution/raw_times.npz", summary["raw_times_sha256"]
    )
    inputs.read(RUNTIME / "execution/raw_events.jsonl", summary["raw_events_sha256"])
    plan = inputs.json(
        RUNTIME / "execution/plan.json", summary["execution_plan_sha256"]
    )
    joined = inputs.json(RUNTIME / "quality_join.json")
    require(
        joined["primary_results_sha256"] == primary_digest
        and joined["runtime_summary_sha256"]
        == inputs.records[str(RUNTIME / "execution/summary.json")]["sha256"],
        "Quality join is not bound to the report inputs",
    )
    aliases = []
    for index, case in enumerate(summary["cases"]):
        for clock in ("cpu", "wall"):
            samples = raw[clock + "_nanoseconds"][index] * 1e-9
            require(
                len(samples) == 11 and np.all(samples > 0), "Invalid timing samples"
            )
            require(
                abs(float(np.median(samples)) - case[clock + "_seconds"]["median"])
                <= 1e-12,
                "Timing summary mismatch",
            )
        for alias in case["aliases"]:
            aliases.append(
                {
                    "alias": alias,
                    "case": case,
                    "raw_cpu_seconds": (raw["cpu_nanoseconds"][index] * 1e-9).tolist(),
                    "raw_wall_seconds": (
                        raw["wall_nanoseconds"][index] * 1e-9
                    ).tolist(),
                }
            )
    require(len(aliases) == 40, "Expected twenty aliases at two batch sizes")
    return {
        "protocol": protocol,
        "summary": summary,
        "plan": plan,
        "quality_join": joined,
        "aliases": aliases,
        "eligible_pairs": sum(
            r["empirical_quality_band_eligible"] for r in joined["comparisons"]
        ),
    }


def diagnostics(inputs):
    result = {}
    for name in ("phase_dynamics001", "coupling_diagnostic001"):
        directory = EVIDENCE / name
        payload = inputs.json(directory / "results.json")
        protocol = inputs.json(directory / "protocol.json", payload["protocol_sha256"])
        inputs.read(
            directory / "raw_arrays.npz",
            payload["raw_arrays_sha256"],
            "diagnostic-raw-arrays",
        )
        result[name] = {"protocol": protocol, "results": payload}
    qualification = []
    for run in (
        "independent_run001",
        "independent_run002",
        "independent_run004_execution_optimized",
    ):
        directory = EVIDENCE / "numerical_qualification" / run
        receipt = inputs.json(directory / "receipt.json")
        inputs.json(directory / "protocol.json", receipt["protocol_sha256"])
        inputs.read(
            directory / "raw_arrays.npz",
            receipt["raw_arrays_sha256"],
            "qualification-raw-arrays",
        )
        qualification.append({"run": run, **receipt})
    result["qualification"] = qualification
    for name in (
        "post_format_numerical_binding.json",
        "mathematical_analysis_audit.json",
        "coupling_diagnostic_audit.json",
    ):
        result[name] = inputs.json(EVIDENCE / "independent_review" / name)
    return result


def load(root):
    prerequisites(root)
    inputs = Inputs(root)
    for name in (
        "report.py",
        "report_sections.py",
        "report_figures.py",
        "report_dynamics.py",
    ):
        inputs.read(ANALYSIS / name, role="report-generator")
    for name in ("release.py", "release_parts.py"):
        inputs.read(ANALYSIS / name, role="public-reconstruction-tool")
    theory = inputs.read(
        ANALYSIS / "ANALYSIS.md", role="mathematical-contract"
    ).decode()
    protocol = inputs.json(STUDY / "protocol.json")
    seal = inputs.json(STUDY / "freeze_seal.json")
    require(
        inputs.records[str(STUDY / "protocol.json")]["sha256"]
        == seal["protocol_sha256"],
        "Formal protocol changed",
    )
    for name, digest in protocol["source_sha256"].items():
        inputs.read(
            Path("experiments/call_put_stable_flow") / name,
            digest,
            "frozen-core-source",
        )
    inputs.json(STUDY / "data_manifest.json")
    training_seal = inputs.json(STUDY / "all_training_complete_seal.json")
    selection_seal = inputs.json(STUDY / "selection_seal.json")
    selection = inputs.json(
        STUDY / "selection.json", selection_seal["selection_sha256"]
    )
    primary = inputs.json(STUDY / "results.json")
    validate_scores(inputs, primary, selection)
    historical = EVIDENCE / "historical_context"
    recovery_provenance = inputs.json(historical / "provenance.json")
    recovery = inputs.json(
        historical / "RECOVERY_STATUS.json", recovery_provenance["source_sha256"]
    )
    require(
        inputs.records[str(historical / "RECOVERY_STATUS.json")]["bytes"]
        == recovery_provenance["source_bytes"],
        "Historical recovery disclosure copy size mismatch",
    )
    data = {
        "version": "hepta-new-scientific-report-20261029-v1",
        "protocol": protocol,
        "primary": primary,
        "score_groups": aggregate(primary, protocol),
        "training": training(inputs, protocol, training_seal),
        "numerics": numerical_appendix(inputs),
        "runtime": runtime_appendix(
            inputs, inputs.records[str(STUDY / "results.json")]["sha256"]
        ),
        "diagnostics": diagnostics(inputs),
        "theory_markdown": theory,
        "recovery": recovery,
        "recovery_provenance": recovery_provenance,
        "generated_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "matplotlib": matplotlib.__version__,
            "platform": platform.platform(),
        },
        "no_final_audit_receipt_consumed": True,
        "not_a_claim_that_all_research_blockers_are_closed": True,
    }
    figure_dir = EVIDENCE / "figures/phase001"
    phase_receipt = inputs.json(figure_dir / "figure_receipt.json")
    phase_png = next(r for r in phase_receipt["outputs"] if r["path"].endswith(".png"))
    data["phase_figure_bytes"] = inputs.read(
        figure_dir / phase_png["path"], phase_png["sha256"], "embedded-figure"
    )
    return inputs, data


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        stream.write("\n")


def run(root, output):
    root, output = root.resolve(), output.resolve()
    require(
        not output.exists(),
        "Report output already exists; preserve previous report bytes",
    )
    inputs, data = load(root)
    output.mkdir(parents=True, exist_ok=False)
    images = figures(data, output / "figures")
    inputs.unchanged()
    data["consumed_inputs"] = inputs.manifest()
    html = render(data, images)
    require(
        "data:image/png;base64," in html and "<script src=" not in html,
        "Report is not self-contained",
    )
    (output / "Hepta_New_Scientific_Report_20261029.html").write_text(
        html, encoding="utf-8"
    )
    write_json(output / "report_summary.json", data)
    outputs = [
        {
            "path": str(p.relative_to(output)),
            "bytes": p.stat().st_size,
            "sha256": sha(p.read_bytes()),
        }
        for p in sorted(output.rglob("*"))
        if p.is_file()
    ]
    write_json(
        output / "report_receipt.json",
        {
            "schema": "hepta-scientific-report-input-output-binding-v1",
            "generated_utc": data["generated_utc"],
            "consumed_inputs": inputs.manifest(),
            "outputs": outputs,
            "environment": data["environment"],
            "input_scope": "Every scientific artifact, source, template and external image read by this generator; installed Python dependencies are versioned environment, not evidence inputs",
            "source": [
                r for r in inputs.manifest() if "report-generator" in r["roles"]
            ],
            "independent_final_audit_not_yet_asserted": True,
            "no_training_or_primary_scores_modified": True,
            "all_research_blockers_closed": False,
            "public_repository": "TrillionniumFoundation/hepta-private-ci",
            "public_branch": "research/hcsn-callput-rebuild-20261028",
            "anticipated_complete_archive": "hepta_stable_flow_complete_20261029.tar.gz",
            "anticipated_parts_manifest": "research_evidence/hepta_stable_flow_20261029/releases/complete_parts_20261029/PARTS.json",
        },
    )
    return {
        "status": "report_generated_pending_independent_report_audit",
        "output": str(output),
        "report_receipt_sha256": sha((output / "report_receipt.json").read_bytes()),
        "input_count": len(inputs.records),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.output), ensure_ascii=False))
