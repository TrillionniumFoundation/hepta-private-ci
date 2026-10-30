"""Post-baseline, read-only sampling refinement of selected irregular encoders."""

import argparse
import json
from pathlib import Path
import time
import traceback

import numpy as np

from .common import HERE, ROOT, DATA, DATA_SHA, FACTORS, MODELS, SEEDS, oracle, refine, semantic_checks, sha, read, write, utc, verify


def register(output):
    if (HERE / "PROTOCOL.json").exists() or output.exists():
        raise FileExistsError("Preserve earlier protocols and diagnostics")
    parent = ROOT / "experiments/hcsn_distributional_v2"
    upstream_paths = (parent / "CONTENT002_PROTOCOL.json", parent / "results/lif_supplement001/PROTOCOL.json")
    sources, references = {}, {}
    for path in upstream_paths:
        references[str(path.relative_to(ROOT))] = sha(path)
        for name, expected in read(path)["source_files_sha256"].items():
            if Path(name).suffix == ".py":
                if name in sources and sources[name] != expected:
                    raise ValueError("Parent executable-source identities conflict")
                sources[name] = expected
    for path in sorted(HERE.glob("*.py")):
        sources[str(path.relative_to(ROOT))] = sha(path)
    for name in ("resource_accounting.py", "train_equivalence.py"):
        path = ROOT / "experiments/hcsn_risk_memory_v1" / name
        sources[str(path.relative_to(ROOT))] = sha(path)
    jobs = []
    for seed in SEEDS:
        for model in MODELS:
            folder = parent / "results" / ("lif_supplement001" if model == "lif_snn" else "content002") / "runs" / f"irregular__{model}__{seed}"
            selection = read(folder / "selection.json")
            checkpoint = folder / "selected.npz"
            if sha(checkpoint) != selection["selected_checkpoint_sha256"]:
                raise ValueError("Selected checkpoint SHA mismatch")
            summary = read(folder / "summary.json")
            config = summary["selected_model_config"]
            if config["input_dim"] != 64 or config["output_dim"] != 2 or config["width"] != 32 or config["depth"] != 1:
                raise ValueError("Unexpected original architecture")
            jobs.append(dict(model=model, seed=seed, checkpoint=str(checkpoint.relative_to(ROOT)),
                checkpoint_sha256=sha(checkpoint), original_predictions=str((folder / "test_predictions.npz").relative_to(ROOT)),
                original_predictions_sha256=sha(folder / "test_predictions.npz"), original_selected_step=selection["selected_step"],
                source_identity=str((folder / "IDENTITY.json").relative_to(ROOT)), config=config))
            for filename in ("selected.npz", "selection.json", "summary.json", "IDENTITY.json", "test_predictions.npz"):
                path = folder / filename
                references[str(path.relative_to(ROOT))] = sha(path)
    meta = DATA.with_suffix(".json")
    references[str(meta.relative_to(ROOT))] = sha(meta)
    review_directory = parent / "results/sixstage_20261030_sampling_semantic_review"
    review_path = review_directory / "RESULTS.json"
    review = read(review_path)
    if not review["passed"] or review["source_sha256"] != sha(HERE / "common.py") or review["neural_inference_run"]:
        raise ValueError("Independent train-only semantic review is missing or changed")
    for path in (review_path, review_directory / "common_source_snapshot.py", HERE / "README.md"):
        references[str(path.relative_to(ROOT))] = sha(path)
    if sha(DATA) != DATA_SHA:
        raise ValueError("Original data changed")
    preflight_start = time.process_time()
    with np.load(DATA, allow_pickle=False) as archive:
        train = {name: np.array(archive["train_" + name]) for name in ("x", "dt", "y")}
    semantic = semantic_checks(train["x"], train["dt"], train["y"])
    if not semantic["passed"]:
        raise ValueError("Train-only refinement/label checks failed")
    output.mkdir(parents=True, exist_ok=False)
    preflight_path = output / "TRAIN_SEMIGROUP_PREFLIGHT.json"
    write(preflight_path, dict(train_only=True, heldout_arrays_loaded=False, model_inference=False,
        source_sha256=sha(HERE / "common.py"), data_sha256=DATA_SHA, checks=semantic,
        nested_cpu_seconds=time.process_time()-preflight_start))
    references[str(preflight_path.relative_to(ROOT))] = sha(preflight_path)
    protocol = dict(schema="hcsn-sampling-refinement-post-baseline.v1", registered_utc=utc(),
        study_id="sampling_refinement001", source_files_sha256=sources, references_sha256=references,
        data=dict(path=str(DATA.relative_to(ROOT)), sha256=DATA_SHA, split="test", samples=512,
                  original_length=32, input_dim=64, output_dim=2, label_rate=0.2),
        jobs=jobs, factors=list(FACTORS), batch_size=8, threads=1, optimizer_steps=0,
        implementation="Original selected model sources and weights, no stable-projection substitution",
        transformations=dict(x="repeat each entire64-dimensional token k times",
            dt="divide each original float32 duration by binary k, then repeat k times",
            labels="Only the final position32*k-1 is supervised with the unchanged original final label",
            query="All32 segments including the final query marker are repeated; exact physical interval endpoints preserved"),
        semantic_gate="Require independent float64 leaky-integral/semigroup agreement within5e-12*(1+abs(state)), exact interval endpoints/total time and all512 original labels",
        independent_train_only_semantic_review=dict(path=str(review_path.relative_to(ROOT)), sha256=sha(review_path)),
        model_output_gate="finite logits; original HCSN probability finite/nonnegative and max mass error<=1e-4; any factor failures and partial predictions retained",
        reference_comparison="Compare new B8 k1 predictions/logits with original saved predictions, including disagreements; never substitute original batch-shape outputs for new k1",
        primary_diagnostics=["accuracy/CE at k1,2,4", "paired within-checkpoint accuracy change versus new B8 k1", "prediction-flip fraction versus new B8 k1"],
        statistics="Descriptive three initialization-seed means/SD; no hypothesis test, selection or population CI",
        probability_failures="A failed factor has no full-test quality score; raw valid prefix, failing coordinates and exception retained. Continue other factors/jobs unless process/resource failure.",
        scope="Post-baseline end-to-end sampling-representation robustness; original OOD simultaneously changed length and time horizon and remains untouched",
        not_claimed=["fixed-generator semigroup error of the network", "PDE timestep convergence", "invariance of internal drift/boundary/gates", "new training or checkpoint selection"],
        clock_caveat="Both classifier frontends use dt/32 and elapsed/32. Refinement changes embeddings and internal coefficients even though external held signal and interval endpoints are identical. Transformer also changes its within-interval positional samples.",
        resource=dict(workers=1, worker_budget_bytes=int(1.1*1024**3), shared_reserve_bytes=2*1024**3,
            scheduling="Separate root/math-authorized window; reserve memory-profile desired slots including future growth; all child CPU measured with wait4",
            estimate_only="5-15 CPU minutes and <1.1GiB peak forecast, not a measurement", energy_joules=None),
        publication_gate="Root public commit containing exact new protocol and freeze before any refinement model inference",
        old_reports_selection_weights_unchanged=True)
    verify(protocol)
    write(HERE / "PROTOCOL.json", protocol)
    write(HERE / "FREEZE.json", dict(schema="hcsn-sampling-refinement-freeze.v1", sealed_utc=utc(),
        protocol_sha256=sha(HERE / "PROTOCOL.json"), source_files_sha256=sources, references_sha256=references,
        no_new_refinement_model_inference=True, train_only_semantic_preflight_sha256=sha(preflight_path)))
    write(output / "REGISTRATION.json", dict(protocol_sha256=sha(HERE / "PROTOCOL.json"),
        freeze_sha256=sha(HERE / "FREEZE.json"), jobs=len(jobs), inference_runs=len(jobs)*len(FACTORS),
        no_new_refinement_model_inference=True))
    print(json.dumps(dict(registered=True, protocol_sha256=sha(HERE / "PROTOCOL.json"),
        freeze_sha256=sha(HERE / "FREEZE.json"), sources=len(sources), train_semigroup_passed=True)), flush=True)


def worker(output, model_name, seed):
    import torch
    from experiments.hcsn_distributional_v2.model import build_model, MatchedClassifier
    from experiments.hcsn_free_boundary_v1.training import load_weights

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    protocol_path, freeze_path = HERE / "PROTOCOL.json", HERE / "FREEZE.json"
    identities = dict(protocol_sha256=sha(protocol_path), freeze_sha256=sha(freeze_path))
    protocol = read(protocol_path)
    verify(protocol)
    seal = read(output / "PUBLIC_SEAL.json")
    if any(seal[key] != expected for key, expected in identities.items()):
        raise ValueError("Public seal identity differs")
    job = next(row for row in protocol["jobs"] if row["model"] == model_name and row["seed"] == seed)
    folder = output / "runs" / f"{model_name}__{seed}"
    folder.mkdir(parents=True, exist_ok=False)
    write(folder / "START.json", dict(job=job, identities=identities, utc=utc(), public_commit=seal["public_commit"],
        torch=torch.__version__, numpy=np.__version__, batch_size=8, optimizer_steps=0))
    with np.load(DATA, allow_pickle=False) as archive:
        test = {name: np.array(archive["test_" + name]) for name in ("x", "dt", "y")}
    if len(test["x"]) != 512:
        raise ValueError("Expected all512 original test examples")
    semantic = semantic_checks(test["x"], test["dt"], test["y"])
    write(folder / "SEMANTIC_CHECKS.json", semantic)
    if not semantic["passed"]:
        raise ValueError("Heldout label/semigroup checks failed before model inference")
    with np.load(ROOT / job["original_predictions"], allow_pickle=False) as archive:
        original = {name: np.array(archive[name]) for name in ("logits", "predictions", "labels", "sample_indices", "step_indices")}
    if not (np.array_equal(original["sample_indices"], np.arange(512)) and
            np.all(original["step_indices"] == 31) and np.array_equal(original["labels"], test["y"][:, -1])):
        raise ValueError("Original predictions have different supervision coordinates")
    factory = MatchedClassifier if model_name == "lif_snn" else build_model
    model = factory(model_name, 64, 2, 32, 1, seed)
    load_weights(ROOT / job["checkpoint"], model)
    model.eval()
    initial = {name: value.detach().clone() for name, value in model.state_dict().items()}
    results, base_predictions, base_logits = [], None, None
    for factor in FACTORS:
        factor_start = time.process_time()
        x, dt, y = refine(test["x"], test["dt"], test["y"], factor)
        chunks, mass_errors, minima = [], [], []
        failure = None
        try:
            with torch.no_grad():
                for start in range(0, 512, 8):
                    logits, aux = model(torch.from_numpy(x[start:start+8]), torch.from_numpy(dt[start:start+8]), return_aux=True)
                    if not bool(torch.isfinite(logits).all()):
                        raise FloatingPointError("Nonfinite final-query logits")
                    if "probability" in aux:
                        errors = torch.zeros(len(logits))
                        minimum = torch.ones(len(logits))
                        for layer in aux["layers"]:
                            p = layer["probability"]
                            if not bool(torch.isfinite(p).all()) or bool((p < 0).any()):
                                raise FloatingPointError("Invalid probability state")
                            errors = torch.maximum(errors, (p.sum(-1)-1).abs().flatten(1).max(1).values)
                            minimum = torch.minimum(minimum, p.flatten(1).min(1).values)
                        if float(errors.max()) > 1e-4:
                            raise FloatingPointError("Probability mass error exceeds original float32 gate")
                        mass_errors.append(errors.numpy().copy())
                        minima.append(minimum.numpy().copy())
                    chunks.append(logits.numpy().copy())
        except Exception as error:
            if isinstance(error, MemoryError) or "out of memory" in str(error).lower() or "can't allocate memory" in str(error).lower():
                raise
            failure = dict(error_type=type(error).__name__, error=str(error), failed_original_sample_start=start,
                failed_original_sample_stop=min(start+8, 512), refined_length=32*factor, traceback=traceback.format_exc())
        logits = np.concatenate(chunks) if chunks else np.empty((0, 2), dtype=np.float32)
        predictions = logits.argmax(-1)
        raw = dict(logits=logits, predictions=predictions, labels=y[:len(logits), -1],
            sample_indices=np.arange(len(logits)), original_step_indices=np.full(len(logits), 31),
            refined_step_indices=np.full(len(logits), 32*factor-1),
            original_total_time=test["dt"][:len(logits)].astype(np.float64).sum(1),
            refined_total_time=dt[:len(logits)].astype(np.float64).sum(1))
        if mass_errors:
            raw.update(maximum_probability_mass_error_per_sample=np.concatenate(mass_errors),
                       minimum_probability_per_sample=np.concatenate(minima))
        path = folder / f"factor_{factor}.npz"
        np.savez_compressed(path, **raw)
        completed = failure is None and len(logits) == 512
        row = dict(factor=factor, completed=completed, scored_samples=len(logits), failure=failure,
            raw_path=path.name, raw_sha256=sha(path), nested_cpu_seconds=time.process_time()-factor_start,
            accuracy=None, cross_entropy=None, prediction_flip_vs_B8_k1=None, accuracy_difference_vs_B8_k1=None,
            maximum_mass_error=float(np.max(np.concatenate(mass_errors))) if mass_errors else None,
            original_saved_comparison=None)
        if completed:
            labels = y[:, -1]
            row["accuracy"] = float(np.mean(predictions == labels))
            row["cross_entropy"] = float(np.mean(np.logaddexp(logits[:, 0].astype(np.float64), logits[:, 1].astype(np.float64))-logits[np.arange(512), labels]))
            if factor == 1:
                base_predictions, base_logits = predictions.copy(), logits.copy()
                row["original_saved_comparison"] = dict(
                    identical_predictions=bool(np.array_equal(predictions, original["predictions"])),
                    changed_predictions=int(np.count_nonzero(predictions != original["predictions"])),
                    maximum_absolute_logit_difference=float(np.max(np.abs(logits.astype(np.float64)-original["logits"].astype(np.float64)))),
                    allclose_atol_rtol_2e_5=bool(np.allclose(logits, original["logits"], atol=2e-5, rtol=2e-5)),
                    original_accuracy=float(np.mean(original["predictions"] == labels)),
                    new_B8_accuracy=row["accuracy"],
                    note="Batch-shape differences are retained; refinement comparisons always use this new B8 k1")
            if base_predictions is not None:
                row["prediction_flip_vs_B8_k1"] = float(np.mean(predictions != base_predictions))
                row["accuracy_difference_vs_B8_k1"] = row["accuracy"] - float(np.mean(base_predictions == labels))
        write(folder / f"factor_{factor}.json", row)
        results.append(row)
        print(json.dumps(dict(model=model_name, seed=seed, factor=factor, completed=completed, scored_samples=len(logits))), flush=True)
    unchanged = all(torch.equal(value, initial[name]) for name, value in model.state_dict().items())
    verify(protocol)
    if not unchanged or sha(protocol_path) != identities["protocol_sha256"] or sha(freeze_path) != identities["freeze_sha256"]:
        raise ValueError("Model or study identity changed")
    write(folder / "RESULT.json", dict(schema="hcsn-sampling-refinement-result.v1", job=job,
        factors=results, all_factors_completed=all(row["completed"] for row in results), identities=identities,
        parameters_unchanged=unchanged, semantic_checks_passed=True, optimizer_steps=0))


def analyze(output):
    protocol = read(HERE / "PROTOCOL.json")
    verify(protocol)
    jobs, rows = [], []
    for job in protocol["jobs"]:
        folder = output / "runs" / f"{job['model']}__{job['seed']}"
        result = read(folder / "RESULT.json")
        for factor in result["factors"]:
            if sha(folder / factor["raw_path"]) != factor["raw_sha256"]:
                raise ValueError("Prediction evidence changed")
            rows.append(dict(model=job["model"], seed=job["seed"], **factor))
        jobs.append(result)
    statistics = []
    for model in MODELS:
        for factor in FACTORS:
            selected = [row for row in rows if row["model"] == model and row["factor"] == factor and row["completed"]]
            metrics = {}
            for key in ("accuracy", "cross_entropy", "prediction_flip_vs_B8_k1", "accuracy_difference_vs_B8_k1"):
                values = [row[key] for row in selected if row[key] is not None]
                metrics[key] = dict(n=len(values), mean=float(np.mean(values)) if values else None,
                    sd=float(np.std(values, ddof=1)) if len(values)>1 else None)
            statistics.append(dict(model=model, factor=factor, completed_seeds=len(selected), metrics=metrics))
    summary = dict(schema="hcsn-sampling-refinement-summary.v1", protocol_sha256=sha(HERE / "PROTOCOL.json"),
        completed_jobs=len(jobs), attempted_factors=len(rows), completed_factors=sum(row["completed"] for row in rows),
        rows=rows, by_model_factor=statistics, all_checkpoint_parameters_unchanged=all(j["parameters_unchanged"] for j in jobs),
        all_semantic_checks_passed=all(j["semantic_checks_passed"] for j in jobs),
        scope=protocol["scope"], clock_caveat=protocol["clock_caveat"], statistics=protocol["statistics"])
    write(output / "SUMMARY.json", summary)
    lines = ["# Pure input-time refinement diagnostic", "",
        "Selected checkpoints and original reports remain unchanged. All comparisons below use the new B8 k1 baseline. "
        "Original saved predictions are compared separately, and any batch-shape sensitivity is retained.", "",
        "| Model | Factor | Complete seeds | Accuracy mean ± SD | Change vs B8 k1 | Prediction flips |",
        "|---|---:|---:|---:|---:|---:|"]
    for row in statistics:
        m=row["metrics"]; accuracy=m["accuracy"]
        def percent(value):
            return "NA" if value is None else f"{100*value:.3f}%"
        lines.append(f"| {row['model']} | {row['factor']} | {row['completed_seeds']} | "
            f"{percent(accuracy['mean'])} ± {percent(accuracy['sd'])} | {percent(m['accuracy_difference_vs_B8_k1']['mean'])} | "
            f"{percent(m['prediction_flip_vs_B8_k1']['mean'])} |")
    lines += ["", "## Limits", "", protocol["scope"] + ".", "", protocol["clock_caveat"], "",
        "The semigroup and label checks concern the independent rate0.2 leaky-integral oracle. "
        "They do not establish a semigroup for the learned encoder or a fixed-generator PDE convergence test. "
        "Only the last query is scored; repeated query markers do not add supervised samples. "
        "Three initialization seeds are descriptive replicates, not a population confidence interval.", "",
        "Raw per-example logits, labels, original/refined query coordinates, times and probability checks are retained. "
        "A factor that violates the original probability gate has no full-test accuracy; failures and valid prefixes remain in the report data."]
    (output / "REPORT.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(completed_jobs=len(jobs), attempted_factors=len(rows), completed_factors=summary["completed_factors"])), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "worker", "analyze"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(HERE / "results"):
        raise ValueError("New isolated results directory required")
    if args.action=="register": register(output)
    elif args.action=="worker": worker(output,args.model,args.seed)
    else: analyze(output)
