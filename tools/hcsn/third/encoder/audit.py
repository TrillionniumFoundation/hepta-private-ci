"""Read-only evidence audit added after freezing; it cannot select a model."""
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.special import logsumexp
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from next.full_kernel.tables import build_table


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    frozen = json.loads((HERE/"freeze.json").read_text())
    for name, digest in frozen["source_sha256"].items():
        assert sha(ROOT/name) == digest, name
    assert sha(HERE/"validation.json") == frozen["validation_sha256"]
    analysis = json.loads((HERE/"analysis.json").read_text())
    protocol = json.loads((HERE/"protocol.json").read_text())
    cache = Path("/tmp/hcsn-third-encoder-assets")
    datasets = {}
    checked = 0
    maximum_metric_error = 0.
    for dataset in protocol["datasets"]:
        manifest_path = HERE/(dataset+"_manifest.json")
        result_path = HERE/(dataset+"_results.json")
        manifest = json.loads(manifest_path.read_text())
        result = json.loads(result_path.read_text())
        assert result["complete"] and len(result["runs"]) == 50
        assert result["freeze_sha256"] == sha(HERE/"freeze.json") == manifest["freeze_sha256"]
        feature_path = cache/(dataset+"_features.npz")
        assert sha(feature_path) == result["features_sha256"] == manifest["features_sha256"]
        raw = np.load(feature_path)
        linear_path = HERE/"checkpoints"/dataset/"linear.npz"
        assert sha(linear_path) == result["linear_reference"]["checkpoint_sha256"]
        linear = dict(np.load(linear_path))
        for name, metrics in result["linear_reference"]["metrics"].items():
            logits = raw[name+"_x"][:, -1]@linear["coef"].T+linear["intercept"]
            assert float(np.mean(logits.argmax(1) == raw[name+"_y"])) == metrics["accuracy"]
        seen = set()
        new = {}
        for split, rows in manifest["selection"].items():
            current = {r["raw_sha256"] for r in rows}
            assert len(current) == len(rows) and not (current & seen)
            assert np.array_equal(raw[split+"_y"], [r["label"] for r in rows])
            seen.update(current)
            new[split] = current
        previous = json.loads((ROOT/"next/encoder"/(dataset+"_manifest.json")).read_text())
        old = {r["raw_sha256"] for rows in previous["selection"].values() for r in rows}
        old.update(previous["corrupted_input_sha256"])
        if dataset == "ag_news":
            sst = json.loads((ROOT/"encoder/feature_manifest.json").read_text())
            old.update(r["normalized_text_sha256"] for rows in sst["selection"].values() for r in rows)
        assert not (seen & old)
        assert np.array_equal(raw["test_y"], raw["corrupted_test_y"])
        unique_runs = set()
        for row in result["runs"]:
            key = (row["regime"], row["kind"], row["seed"])
            assert key not in unique_runs
            unique_runs.add(key)
            checkpoint = HERE/row["checkpoint_file"]
            prediction = HERE/row["prediction_file"]
            assert sha(checkpoint) == row["checkpoint_sha256"]
            assert sha(prediction) == row["prediction_sha256"]
            params = np.load(checkpoint)
            assert sum(a.size for a in params.values()) == row["trainable_parameters"]
            assert all(np.isfinite(a).all() for a in params.values())
            assert {str(a.dtype) for a in params.values()} == {"float32"}
            logits = np.load(prediction)
            for split in ("validation", "test", "corrupted_test"):
                value = logits[split].astype(np.float64)
                labels = raw[split+"_y"]
                assert np.isfinite(value).all() and value.shape[0] == len(labels)
                accuracy = float(np.mean(value.argmax(1) == labels))
                loss = float(np.mean(logsumexp(value, axis=1)-value[np.arange(len(labels)), labels]))
                errors = [abs(accuracy-row["metrics"][split]["accuracy"]), abs(loss-row["metrics"][split]["loss"])]
                maximum_metric_error = max(maximum_metric_error, *errors)
                assert max(errors) < 1e-12
            assert row["timing"]["steps"] == protocol["updates"]
            assert row["timing"]["warmup_optimizer_updates"] == 0
            best = min(row["history"], key=lambda h: h["validation"]["loss"])
            assert best["step"] == row["timing"]["best_step"]
            checked += 1
        contrasts = [c for c in analysis["contrasts"] if c["dataset"] == dataset and c["primary_family"]]
        for contrast in contrasts:
            d = []
            for seed in protocol["training_seeds"]:
                pair = {}
                for kind in ("full_hx", "ordinary_c1"):
                    row = next(r for r in result["runs"] if (r["regime"], r["kind"], r["seed"]) == (contrast["regime"], kind, seed))
                    logits = np.load(HERE/row["prediction_file"])[contrast["split"]]
                    pair[kind] = float(np.mean(logits.argmax(1) == raw[contrast["split"]+"_y"]))
                d.append(pair["full_hx"]-pair["ordinary_c1"])
            d = np.asarray(d)
            half = t.ppf(1-.05/16, 4)*d.std(ddof=1)/np.sqrt(5)
            assert np.allclose(contrast["bonferroni_family95"], [d.mean()-half, d.mean()+half], atol=1e-14)
        datasets[dataset] = dict(runs=len(unique_runs), historical_excluded=len(old), new_clean_examples=len(seen),
            manifest_sha256=sha(manifest_path), result_sha256=sha(result_path),
            feature_sha256=sha(feature_path), linear_sha256=sha(linear_path),
            preparation_wall_seconds=manifest["encoder_total_seconds"]+manifest["projection_seconds"],
            head_run_cpu_seconds=result["total_head_cpu_seconds"], head_run_wall_seconds=result["total_head_wall_seconds"],
            linear_fit_and_evaluation_cpu_seconds=result["linear_reference"]["fit_and_evaluation_cpu_seconds"])
    stored = dict(np.load(ROOT/"next/full_kernel/baseline_table.npz"))
    times = []
    for _ in range(3):
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        rebuilt = build_table()
        times.append(dict(wall_seconds=time.perf_counter()-start_wall, cpu_seconds=time.process_time()-start_cpu))
    differences = {k: float(np.max(np.abs(rebuilt[k]-stored[k]))) for k in stored}
    report = dict(passed=True, checked_runs=checked, maximum_recomputed_metric_error=maximum_metric_error,
                  datasets=datasets, source_freeze_sha256=sha(HERE/"freeze.json"),
                  analysis_sha256=sha(HERE/"analysis.json"),
                  kernel_cost=dict(source_numeric_float64_bytes=sum(a.nbytes for a in stored.values()),
                                   runtime_numeric_float32_table_bytes=sum(a.astype(np.float32).nbytes for a in stored.values()),
                                   compressed_file_bytes=(ROOT/"next/full_kernel/baseline_table.npz").stat().st_size,
                                   offline_build_measurements=times, rebuilt_source_max_differences=differences,
                                   original_result_field="fixed_operator_bytes records source numeric float64 table, not executable size or measured process memory"),
                  scope="Independent saved-logit/label, checkpoint, split, freeze and cost-accounting audit; no model selection or extra training",
                  cost_limits="Head-run totals omit startup, model loading, feature preparation and separate numerical/development work; preparation is wall time, not CPU or energy")
    (HERE/"audit.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
