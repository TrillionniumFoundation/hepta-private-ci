"""Run the four research stages and emit source-bound, non-promotional evidence."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import io
import json
from pathlib import Path
import platform
import time
import unittest

import numpy as np
import PIL

from .adapters import run_adapter_experiment
from .core import Config, Environment, enumerate_policy_trees, optimal
from .experiments import SEEDS, compare_routers
from .generation import fixture_smoke
from .gradients import SoftmaxPolicy, check_gradient, train_policy
from .streaming import run_streaming_experiment

BASE_SHA = "732e934ba496d90fbe042b8d41d479ef901643e5"


def native_golden_reference():
    """Independent integer arithmetic for the existing NDU-GV-001 vector.

    This reads the published profile; it does not execute the native Rust crate.
    No cross-backend equivalence is inferred outside this single golden vector.
    """
    scale = 1 << 32
    discount = int((Decimal("0.8") * scale).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    values = [scale]
    for instant in (scale // 4, scale // 2):
        product = discount * values[0]
        quotient, remainder = divmod(product, scale)
        if remainder * 2 > scale or (remainder * 2 == scale and quotient % 2):
            quotient += 1
        values.insert(0, instant + quotient)
    expected = [5755256177, 4509715661, 4294967296]
    if values != expected:
        raise AssertionError("native published golden vector mismatch")
    return {"vector": "NDU-GV-001", "q32_values": values, "pass": True,
            "native_rust_executed": False,
            "scope": "independent arithmetic matches published vector, not native integration"}


def phase_one(seeds, quick):
    oracle_checks, gradients, learning = [], [], []
    for risk in (0.0, 0.25, 2.0):
        tiny = Environment(Config(budget=3, horizon=3, durations=(1, 1),
                                  dynamic_preferences=False, risk=risk))
        dp, _, values = optimal(tiny)
        enumerated, count = enumerate_policy_trees(tiny)
        error = abs(dp - enumerated)
        if error > 1e-12:
            raise AssertionError("DP differs from independent contingent-plan enumeration")
        oracle_checks.append({"risk": risk, "dp_value": dp, "enumerated_value": enumerated,
                              "absolute_error": error, "policy_trees": count,
                              "dp_states": len(values)})
        env = Environment(Config(budget=4, horizon=5, risk=risk))
        result = check_gradient(SoftmaxPolicy(env, seeds[0]))
        if result["max_absolute_error"] > 1e-7:
            raise AssertionError("policy gradient disagrees with finite differences")
        gradients.append({"risk": risk, **result})
        for seed in seeds:
            _, receipt = train_policy(env, seed, steps=30 if quick else 120)
            learning.append({"risk": risk, "config": vars(env.config), **receipt})
    return {"status": "PASS_FINITE_CONTROL_REFERENCE", "native_golden": native_golden_reference(),
            "oracle_checks": oracle_checks, "policy_gradient_checks": gradients,
            "tabular_learning": learning,
            "scope": "finite two/three-branch control; no continuous-time FBSDE or generation efficacy claim"}


def tests_receipt(output_directory):
    root = Path(__file__).resolve().parent
    for name in ("test_core", "test_experiments", "test_generation", "test_adapters_streaming", "test_assessment"):
        if not (root / (name + ".py")).is_file():
            raise RuntimeError("missing required test module: " + name)
    suite = unittest.defaultTestLoader.discover(str(root), pattern="test_*.py",
                                               top_level_dir=str(root.parent))
    stream = io.StringIO()
    started = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    (output_directory / "tests.log").write_text(stream.getvalue(), encoding="utf-8")
    if not result.wasSuccessful() or result.testsRun < 30 or result.skipped:
        raise RuntimeError("reference tests did not qualify:\n" + stream.getvalue())
    return {"tests_run": result.testsRun, "failures": len(result.failures),
            "errors": len(result.errors), "skipped": len(result.skipped),
            "wall_seconds": time.perf_counter() - started, "log": stream.getvalue()}


def source_identity():
    package = Path(__file__).resolve().parent
    repo = package.parents[1]
    files = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(package.glob("*.py"))}
    config = repo / "qualification/ndu-portfolio-v1/preregistration.json"
    files[str(config.relative_to(repo))] = hashlib.sha256(config.read_bytes()).hexdigest()
    for path in (package / "requirements.txt", repo / ".github/workflows/blocking-ci.yml"):
        files[str(path.relative_to(repo))] = hashlib.sha256(path.read_bytes()).hexdigest()
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"base_source_sha": BASE_SHA, "source_files_sha256": files,
            "source_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
            "python": platform.python_version(), "numpy": np.__version__, "pillow": PIL.__version__,
            "platform": platform.platform(), "precision": "float64",
            "execution_device": "CPU", "run_timestamp_utc": datetime.now(timezone.utc).isoformat()}


def render_report(result):
    phase1, adapter, stream = result["phase_1"], result["phase_3"], result["phase_4"]
    max_error = max(r["max_absolute_error"] for r in phase1["policy_gradient_checks"])
    oracle_error = max(r["absolute_error"] for r in phase1["oracle_checks"])
    lines = [
        "# NDU portfolio validation: measured results",
        "",
        "Overall status: **RESEARCH_ONLY_HOLD**. Finite control and reference contracts run; real multimodal efficacy is unmeasured.",
        "",
        f"Base source: `{BASE_SHA}`. Exact tested source manifest: `{result['source']['source_manifest_sha256']}`.",
        f"Run mode: **{'quick smoke' if result['quick'] else 'full predeclared toy protocol'}**. "
        f"Python {result['source']['python']}, NumPy {result['source']['numpy']}, float64 CPU.",
        "",
        "## Evidence by stage",
        "",
        "| Stage | Executed evidence | Decision |",
        "|---|---|---|",
        f"| 1: exact control | {result['tests']['tests_run']} focused regression tests across the package; DP/enumeration; gradients; learned gaps | PASS for finite reference only |",
        "| 2: real text + image | Artifact transport and independent scoring contracts; synthetic transport fixture | HOLD: no configured frozen real provider, dataset, or independent evaluator |",
        f"| 3: adapter training | Actual NumPy updates through {adapter['trainable_parameters']} parameters; heldout synthetic probes | {adapter['synthetic_candidate_admission']} synthetic candidate; real stage HOLD |",
        "| 4: audio/video streaming | Multirate prefix, budget, shared-work and reservation invariants | PASS for ledger reference; real media HOLD |",
        "",
        "## Exact control checks",
        "",
        f"The largest DP versus exhaustive policy-tree discrepancy is {oracle_error:.3g}. "
        f"The largest checked policy-gradient error is {max_error:.3g}.",
        "The published Q32 NDU-GV-001 arithmetic vector also matches. The native Rust workspace was not compiled in this environment.",
        "The entropic profile includes policy randomization in the risk lottery and discounts by actual action duration. "
        "Its zero-risk limit is ordinary expected utility. It is not the general stochastic FBSDE solver.",
        "",
        "| Risk | Seed | Learned recursive value | DP optimum | Gap |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in phase1["tabular_learning"]:
        lines.append(f"| {row['risk']:g} | {row['seed']} | {row['learned_value']:.8f} | {row['optimal_value']:.8f} | {row['optimality_gap']:.8f} |")
    lines += ["", "Different-risk rows have different objectives; their raw utilities are not efficacy comparisons.",
              "", "## Common-observer controller comparisons", "",
              "All controllers below are scored on the same original toy environment. "
              "The shared learned routers have 130 parameters, identical initializations per seed and equal update counts. "
              "Test configurations never enter gradient fitting. These are exact model-based routers, not actor-critic training.", ""]
    for split, title in (("train", "Training configurations"), ("heldout", "Unseen budget/cost configurations")):
        rows = [r for r in result["comparisons"]["comparisons"] if r["split"] == split]
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["controller"]].append(row)
        lines += [f"### {title}", "",
                  "Equal-weight means across configurations and seeds; descriptive toy results, without a real-model significance claim.", "",
                  "| Controller | Joint success | Weakest quality | Compute units | Duration ticks | NDU gap |",
                  "|---|---:|---:|---:|---:|---:|"]
        for label, group in grouped.items():
            mean = lambda key: float(np.mean([r[key] for r in group]))
            lines.append(f"| {label} | {mean('joint_success_rate'):.4f} | {mean('weakest_modality_quality'):.4f} | {mean('expected_generation_compute_units'):.3f} | {mean('expected_generation_duration_ticks'):.3f} | {mean('optimality_gap'):.5f} |")
        ordinary = np.mean([r["joint_success_rate"] for r in grouped["ordinary_learned_router"]])
        ndu = np.mean([r["joint_success_rate"] for r in grouped["ndu_learned_router"]])
        lines += ["", f"NDU minus ordinary-router joint success: **{(ndu-ordinary)*100:+.3f} percentage points**.", ""]
    lines += [
        "The explicit cross-modal-feature ablation preserves the joint reward; it removes minimum/product features only. "
        "A separate fully factorized model has not been tested. No-risk and ordinary router are identical in this profile.",
        "The fixed single-pass run is a cheaper reference. The fixed cyclic schedule uses spare quota before final verification. "
        "Equal generation caps do not imply equal actual expenditure or matched total physical computation.",
        "The two-step planner uses oracle model continuation. Its measured host wall time is reported in JSON, "
        "but is not charged to toy generation units. Planner expansion counters are exhaustive-evaluator totals and exclude leaf recursion. "
        "No net efficiency benefit is established.",
        "",
        "## Adapter outcome and retention gate",
        "",
        f"Training objective: {adapter['train_objective_before']:.9f} to {adapter['train_objective_after']:.9f}. "
        f"Maximum adapter-gradient error: {adapter['gradient_check']['max_absolute_error']:.3g}.",
        f"Heldout Brier scores: {adapter['heldout_brier_before']} to {adapter['heldout_brier_after']}.",
        f"Old-base prediction drift: **{adapter['old_probe_brier_drift']:.9f}**, with a fixed 0.02 limit. "
        f"Candidate decision: **{adapter['synthetic_candidate_admission']}**. Selected parameters remain unchanged; the candidate is not selected.",
        "These are synthetic probability-prediction probes. Prediction spread is a diversity proxy, "
        "and old-base drift is a retention proxy. Neither substitutes for semantic diversity or real old-task evaluation.",
        "",
        "## Streaming accounting",
        "",
        f"The fixture records {stream['ledger']['compute_units']} compute units, with shared encoder work counted once. "
        "Controller and verification work remain charged. Delivered audio/video prefixes cover 80 ms at different chunk rates; "
        "an attempted delivered-prefix rewrite is rejected.",
        "Only timestamp coverage and ledger behavior were tested. No audio/video content was generated and no perceptual synchronization score was measured.",
        "",
        "## Concrete remaining qualifications",
        "",
        "1. Bind actual frozen text/image model revisions and weights, task dataset, provider execution path, and independent evaluator provenance.",
        "2. Run every registered baseline on paired real tasks at equal total budgets, including controller/planning, verification, failures and evaluation.",
        "3. Collect independent task quality, contradictions, omissions, critic calibration, tail failure, OOD performance, diversity and old-task retention.",
        "4. Train real Cell/control/generator adapters only as candidate snapshots, then apply the frozen independent gates.",
        "5. Bind real audio/video decoders and evaluate long-horizon streaming, content synchronization and delivery latency.",
        "",
        "Increasing internal NDU or lowering numerical residuals alone does not close these qualifications. "
        "The present evidence does not establish that NDU is necessary or superior to an ordinary controller.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quick", action="store_true", help="one seed and reduced steps; labelled smoke only")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    source = source_identity()
    (args.output / "results.json").write_text('{"overall_status":"RUNNING_NOT_EVIDENCE"}\n', encoding="utf-8")
    (args.output / "RESULTS.md").write_text("# Run in progress\n\nPrevious output is superseded; no result is established.\n", encoding="utf-8")
    try:
        tests = tests_receipt(args.output)
        print(f"Reference regressions: {tests['tests_run']} passed", flush=True)
        seeds = (SEEDS[0],) if args.quick else SEEDS
        core = phase_one(seeds, args.quick)
        print("Exact control, gradient and tabular policy checks complete", flush=True)
        comparisons = compare_routers(seeds=seeds, steps=20 if args.quick else 80)
        print(f"Common-observer comparisons: {len(comparisons['comparisons'])}", flush=True)
        result = {"schema": "hepta.ndu.portfolio.evidence.v1", "overall_status": "RESEARCH_ONLY_HOLD",
                  "quick": args.quick, "source": source, "tests": tests,
                  "phase_1": core, "comparisons": comparisons,
                  "phase_2": {"status": "HOLD_REAL_GENERATION_NOT_EXECUTED",
                              "transport_fixture": fixture_smoke(args.output / "transport_fixture"),
                              "statistical_assessment": {"status": "HOLD_NO_REAL_PANEL",
                                                         "estimator": "paired-group-bootstrap-v1",
                                                         "real_observations": 0},
                              "missing": ["frozen real text/image provider", "task dataset",
                                          "independent evaluator", "verified provenance"]},
                  "phase_3": run_adapter_experiment(), "phase_4": run_streaming_experiment(),
                  "native_integration": "not executed; no Rust source changes",
                  "wall_seconds": time.perf_counter() - started}
        if source_identity()["source_manifest_sha256"] != source["source_manifest_sha256"]:
            raise RuntimeError("source changed during execution; evidence rejected")
        result["source_unchanged_during_run"] = True
        (args.output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (args.output / "RESULTS.md").write_text(render_report(result), encoding="utf-8")
    except Exception as error:
        failed = {"overall_status": "FAILED_NOT_EVIDENCE", "source": source,
                  "error": str(error), "wall_seconds": time.perf_counter() - started}
        (args.output / "results.json").write_text(json.dumps(failed, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (args.output / "RESULTS.md").write_text("# Run failed\n\nThis attempt produced no qualifying evidence. See results.json and tests.log.\n", encoding="utf-8")
        raise
    print(json.dumps({"overall_status": result["overall_status"], "tests": tests["tests_run"],
                      "output": str(args.output), "wall_seconds": result["wall_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
