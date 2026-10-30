"""Prespecified paired-seed contrasts; no outcomes feed model selection."""
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

HERE = Path(__file__).resolve().parent


def main():
    protocol = json.loads((HERE/"protocol.json").read_text())
    tables = {}
    comparisons = []
    for dataset in protocol["datasets"]:
        result = json.loads((HERE/(dataset+"_results.json")).read_text())
        assert result["complete"]
        groups = []
        for regime in protocol["regimes"]:
            for kind in protocol["models"]:
                rows = sorted([r for r in result["runs"] if r["kind"] == kind and r["regime"] == regime], key=lambda r: r["seed"])
                assert [r["seed"] for r in rows] == protocol["training_seeds"]
                metrics = {}
                for split in ("test", "corrupted_test"):
                    scores = np.array([r["metrics"][split]["accuracy"] for r in rows])
                    metrics[split] = dict(mean=float(scores.mean()), seed_sd=float(scores.std(ddof=1)), values=scores.tolist())
                groups.append(dict(regime=regime, kind=kind, metrics=metrics,
                                   trainable_parameters=rows[0]["trainable_parameters"],
                                   fixed_operator_bytes=rows[0]["fixed_operator_bytes"],
                                   mean_total_cpu_seconds=float(np.mean([r["total_run_cpu_seconds"] for r in rows])),
                                   mean_optimizer_wall_seconds=float(np.mean([r["timing"]["optimizer_execution_seconds"] for r in rows])),
                                   mean_batch1_latency_ms=float(np.mean([r["logits_latency"]["batch1"]["median_ms"] for r in rows]))))
            for split in ("test", "corrupted_test"):
                for control in ("ordinary_c1", "same_call_sigmoid", "gru", "transformer"):
                    def scores(kind):
                        return np.array([next(r for r in result["runs"] if r["kind"] == kind and r["regime"] == regime and r["seed"] == seed)["metrics"][split]["accuracy"]
                                         for seed in protocol["training_seeds"]])
                    difference = scores("full_hx")-scores(control)
                    mean = float(difference.mean())
                    se = float(difference.std(ddof=1)/np.sqrt(len(difference)))
                    ordinary_half = float(t.ppf(.975, len(difference)-1)*se)
                    primary = control == "ordinary_c1"
                    corrected_half = float(t.ppf(1-.05/(2*8), len(difference)-1)*se) if primary else None
                    comparisons.append(dict(dataset=dataset, regime=regime, split=split,
                                            lhs="full_hx", control=control, differences=difference.tolist(),
                                            mean=mean, conditional_seed_ci95=[mean-ordinary_half, mean+ordinary_half],
                                            primary_family=primary,
                                            bonferroni_family95=[mean-corrected_half, mean+corrected_half] if primary else None))
        tables[dataset] = dict(groups=groups, linear_reference=result["linear_reference"],
                               total_head_cpu_seconds=result["total_head_cpu_seconds"],
                               total_head_wall_seconds=result["total_head_wall_seconds"])
    primary = [r for r in comparisons if r["primary_family"]]
    assert len(primary) == 8
    decisions = {}
    for regime in protocol["regimes"]:
        rows = [r for r in primary if r["regime"] == regime]
        assert len(rows) == 4
        decisions[regime] = all(r["bonferroni_family95"][0] > 0 and r["mean"] >= .01 for r in rows)
    report = dict(summary=tables, contrasts=comparisons, regime_financial_specific_gate=decisions,
                  financial_specific_gate_passed=any(decisions.values()),
                  equal_quality_cost_gate_established=False, full_backbone_scale_gate_established=False,
                  scope="Five paired training seeds, one new fixed data sample per modality; intervals conditional on samples and budget")
    (HERE/"analysis.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(dict(gates=decisions, primary_contrasts=primary), indent=2))


if __name__ == "__main__":
    main()
