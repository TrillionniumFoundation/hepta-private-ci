"""Prepare the prospective five-seed campaign; confirmation is a separate stage."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from ..native_task_bridge_20261031 import reference
from ..task_value_factorial_20261030.task import ContentAdapter, calibrate, save
from .training import fit, loss_gradient, parameter_hash, teacher_data

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
UPSTREAM = HERE.parent/"task_value_factorial_20261030"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def packed(path, value):
    with Path(path).open("xb") as stream:
        stream.write(gzip.compress(json.dumps(value, allow_nan=False, separators=(",", ":")).encode(), mtime=0))


def protocol():
    old = json.loads((UPSTREAM/"PROTOCOL.json").read_text())
    keys = ("deadlines", "read_budgets", "packet_reliabilities", "packet_prices", "step_durations",
            "packet_length", "multiplier", "latency_price", "ood")
    return dict({k:old[k] for k in keys}, schema="hepta.task.policy.confirmation.v2", date="2026-10-31",
        inherited_frozen_commit="8fef2abec58dc0b40287de1e656f9042371979b5",
        scientific_scope="Real file/model actions on bounded synthetic two-job tasks; ordinary bounded planner and learned residual; no analytic-cell or production/energy claim",
        seeds=[73031,73037,73043,73049,73057], data_seed_base=487103100,
        calibration_packets=128, train_environments=1024, validation_environments=256,
        counterfactual_seeds="seed*10000+101 TRAIN; seed*10000+102 VAL; seed*10000+103 optimizer",
        optimizer=dict(mode="q_mse", width=64, updates=6000, batch=256, learning_rate=.001,
                       adam_betas=[.9,.999], adam_epsilon=1e-8, gradient_clip=2., l2=1e-7),
        candidate_updates=[0,100,300,1000,6000], numeric_contract=reference.NUMERIC_CONTRACT,
        checkpoint_selection="Minimum Q24 deployed validation teacher regret among updates 100/300/1000/6000; ties prefer earlier. Update zero and overall minimum retained. If nonzero does not strictly improve zero, learned admission fails. Float64 selection is diagnostic only.",
        policies=["exact_teacher","one_read","nonzero_residual"], test_sessions=128, ood_sessions=128,
        primary_contrasts=["test:nonzero_residual-one_read", "ood:nonzero_residual-one_read"],
        uncertainty="Five paired seed means; two-sided 95% Student-t intervals (df=4); two-sided p values, Holm over the two primary utility contrasts. Sessions are not independent training replications.",
        quality_metric="correct_jobs/2 per session; unsubmitted jobs count as not correct; completed/2, wrong/2 and conditional submitted accuracy reported separately",
        quality_noninferiority_margin=.02,
        quality_gate="Two-sided 95% paired seed-t lower bound for correct_jobs/2 difference exceeds -0.02 in both splits",
        amortization_sessions=[128,1000,10000], cpu_prices_utility_per_second=[0.,.1,1.,10.],
        primary_cpu_price=1., primary_amortization_sessions=1000,
        cost_scope="Real owner CPU includes metadata, priors, feature construction, model math, actual file reads/content inference, terminal scoring. Policy JSON model load and measured raw-row serialization charged separately. Residual-only preparation includes full TRAIN/VAL teacher-label generation, all optimizer candidates, Q24 selection, diagnostics and artifact serialization; common calibration/startup reported separately. Post-execution teacher diagnostics are experiment overhead, not deployed policy compute.",
        cpu_price_scope="Prespecified research accounting utility per host CPU-second, not a measured production monetary/energy price; Bellman uses task time only, CPU enters post-execution admission",
        admission="All five nonzero choices improve zero on VAL; both primary utility lower bounds positive and both Holm-adjusted p<0.05; quality NI both splits; both full CPU-adjusted lower bounds positive at 1.0 CPU-price/H=1000. Native/prod admission is external and main_activation remains false here.",
        failure_policy="Abort and preserve every failed attempt; no silent row dropping, replacement seed or confirmation-driven retuning",
        freeze_rule="No test/ood cohort generation before externally verified remote source/protocol/model freeze receipt; confirm validates every prepared byte and current source hash before generating cohorts")


def source_files():
    paths = list(HERE.glob("*.py"))+[HERE/"README.md", Path(reference.__file__),
        UPSTREAM/"task.py", UPSTREAM/"PROTOCOL.json", UPSTREAM/"UPSTREAM_FILES.json"]
    paths += [ROOT/r["path"] for r in json.loads((UPSTREAM/"UPSTREAM_FILES.json").read_text())["files"]]
    return sorted(set(paths))


def coverage(data):
    counts = {}
    for row in data["rows"]:
        counts[row["origin"]] = counts.get(row["origin"],0)+1
    raw = np.asarray([r["features"] for r in data["rows"]])
    return dict(environments=len(data["environments"]), states=len(data["rows"]), origins=counts,
        feature_min=raw.min(0).tolist(), feature_max=raw.max(0).tolist(),
        zero_prior_regret_fraction=float(np.mean([r["prior_regret"] <= 1e-12 for r in data["rows"]])))


def choose_q24(checkpoint, receipt, validation):
    wall, cpu = time.perf_counter(), time.process_time()
    records = []
    for candidate in receipt["candidates"]:
        model = dict(checkpoint, weights={k:np.asarray(v,float) for k,v in candidate["weights"].items()})
        actions, regrets = [], []
        for row in validation["rows"]:
            action, _, _ = reference.infer(model, row["features"], row["prior"], row["feasible"])
            teacher = np.asarray(row["teacher"])
            regrets.append(float(np.max(teacher[np.asarray(row["feasible"],bool)])-teacher[action]))
            actions.append(action)
        records.append(dict(update=candidate["update"], q24_validation_regret=float(np.mean(regrets)),
            float64_validation_regret=candidate["validation_regret"], actions=actions, regrets=regrets,
            parameter_sha256=candidate["parameter_sha256"]))
    best = min(records, key=lambda r:(r["q24_validation_regret"],r["update"]))
    nonzero = min((r for r in records if r["update"]), key=lambda r:(r["q24_validation_regret"],r["update"]))
    zero = next(r for r in records if r["update"] == 0)
    selected = {}
    for label, update in (("overall",best["update"]),("nonzero",nonzero["update"]),("update6000",6000)):
        candidate = next(r for r in receipt["candidates"] if r["update"] == update)
        selected[label] = dict(checkpoint, weights=candidate["weights"], selected_update=update,
            selection_numeric_contract=reference.NUMERIC_CONTRACT)
    return selected, dict(candidates=records, overall_update=best["update"], nonzero_update=nonzero["update"],
        zero_q24_regret=zero["q24_validation_regret"], nonzero_q24_regret=nonzero["q24_validation_regret"],
        nonzero_improves_zero=nonzero["q24_validation_regret"] < zero["q24_validation_regret"],
        original_float64_selected_update=receipt["selected_update"],
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)


def selected_diagnostics(checkpoint, train):
    raw = np.asarray([r["features"] for r in train["rows"]])
    x = np.clip((raw-checkpoint["norm"]["mean"])/checkpoint["norm"]["scale"],-8.,8.)
    target = np.asarray([r["teacher"] for r in train["rows"]])-np.asarray([r["prior"] for r in train["rows"]])
    mask = np.asarray([r["feasible"] for r in train["rows"]],bool)
    weight = 1+4*(np.asarray([r["prior_regret"] for r in train["rows"]]) > 1e-8)
    loss, gradient = loss_gradient({k:np.asarray(v,float) for k,v in checkpoint["weights"].items()},x,target,mask,weight,"q_mse",1e-7)
    norm = float(np.sqrt(sum(float(np.square(g).sum()) for g in gradient.values())))
    return dict(full_train_loss=loss, full_train_gradient_norm=norm, gradient_tolerance=1e-5,
                stationary_at_declared_tolerance=norm <= 1e-5,
                termination="Fixed 6000-update training budget and prespecified candidate selection; no global convergence claim")


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    spec = protocol()
    save(out/"PROTOCOL.json", spec)
    sources = {str(p.relative_to(ROOT)):sha(p) for p in source_files()}
    packed(out/"SOURCE_SNAPSHOT.json.gz", dict(sha256=sources,
        text={str(p.relative_to(ROOT)):p.read_text() for p in source_files() if p.suffix in (".py",".json",".md")}))
    summaries = []
    for seed in spec["seeds"]:
        folder = out/f"seed{seed}"
        folder.mkdir()
        begin, begin_cpu = time.perf_counter(), time.process_time()
        adapter = ContentAdapter()
        confusion, calibration = calibrate(adapter, folder, seed, spec["calibration_packets"], spec)
        packed(folder/"CALIBRATION.json.gz", calibration)
        train = teacher_data(seed*10000+101, spec["train_environments"], spec, confusion)
        validation = teacher_data(seed*10000+102, spec["validation_environments"], spec, confusion)
        packed(folder/"TEACHER_DATA.json.gz", dict(train=train, validation=validation, confusion=confusion.tolist()))
        checkpoint, receipt = fit(train, validation, seed*10000+103, **{k:spec["optimizer"][k] for k in ("mode","width","updates","batch")})
        packed(folder/"FLOAT64_TRAINING_RECEIPT.json.gz", receipt)
        selected, selection = choose_q24(checkpoint, receipt, validation)
        packed(folder/"Q24_SELECTION.json.gz", selection)
        selected_gradient = selected_diagnostics(selected["nonzero"], train)
        save(folder/"SELECTED_TRAIN_DIAGNOSTICS.json", selected_gradient)
        models = {}
        for label, model in selected.items():
            path = folder/f"model_{label}.json"
            save(path, model)
            models[label] = dict(path=str(path.relative_to(out)), sha256=sha(path),
                deployment_digest=reference.deployment_digest(sha(path)), update=model["selected_update"],
                parameter_sha256=parameter_hash(model["weights"]))
        common_cpu = adapter.setup["load_cpu_seconds"]+calibration["cpu_seconds"]
        common_wall = adapter.setup["load_wall_seconds"]+calibration["wall_seconds"]
        report = dict(seed=seed, models=models, adapter_setup=adapter.setup,
            confusion=confusion.tolist(), train_coverage=coverage(train), validation_coverage=coverage(validation),
            zero_q24_regret=selection["zero_q24_regret"], nonzero_q24_regret=selection["nonzero_q24_regret"],
            nonzero_improves_zero=selection["nonzero_improves_zero"],
            optimizer_termination=receipt["termination"],
            selected_float64_gradient_norm=receipt["selected_full_train_gradient_norm"],
            selected_nonzero_diagnostics=selected_gradient,
            stages=dict(calibration_cpu=calibration["cpu_seconds"], train_teacher_cpu=train["cpu_seconds"],
                        validation_teacher_cpu=validation["cpu_seconds"], fitting_cpu=receipt["cpu_seconds"],
                        q24_selection_cpu=selection["cpu_seconds"]),
            total_prepare_cpu_seconds=time.process_time()-begin_cpu,
            total_prepare_wall_seconds=time.perf_counter()-begin,
            common_prepare_cpu_seconds=common_cpu, common_prepare_wall_seconds=common_wall,
            timing_scope="Per-seed outer timer through model/receipt/data serialization and coverage; final seed summary and global manifest excluded")
        report["residual_incremental_prepare_cpu_seconds"] = report["total_prepare_cpu_seconds"]-common_cpu
        save(folder/"PREPARE_SEED.json", report)
        summaries.append(report)
        print(json.dumps({k:report[k] for k in ("seed","zero_q24_regret","nonzero_q24_regret","nonzero_improves_zero","total_prepare_cpu_seconds")}), flush=True)
    save(out/"PREPARE_SUMMARY.json", dict(protocol_sha256=sha(out/"PROTOCOL.json"), seeds=summaries,
        total_cpu_seconds=time.process_time()-cpu, total_wall_seconds=time.perf_counter()-wall,
        python=platform.python_version(), numpy=np.__version__, confirmation_generated=False))
    files = {str(p.relative_to(out)):sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    manifest = dict(schema="hepta.task.prepared.v2", files=files, source_sha256=sources,
                    protocol_sha256=sha(out/"PROTOCOL.json"), confirmation_generated=False)
    save(out/"PREPARED_MANIFEST.json", manifest)
    print(json.dumps(dict(prepared=str(out), manifest_sha256=sha(out/"PREPARED_MANIFEST.json"))), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="stage", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--out", type=Path, required=True)
    confirm_parser = sub.add_parser("confirm")
    confirm_parser.add_argument("--prepared", type=Path, required=True)
    confirm_parser.add_argument("--out", type=Path, required=True)
    confirm_parser.add_argument("--freeze-receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.out)
    else:
        from .confirmation import confirm
        confirm(args.prepared, args.out, args.freeze_receipt)
