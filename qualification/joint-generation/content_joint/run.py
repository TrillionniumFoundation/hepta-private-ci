"""One independently frozen six-model-per-family TRAIN portfolio. No test API."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback

import numpy as np
from PIL import Image

from content_joint.adam4 import Adam4, setup_work as adam4_work
from content_joint.evidence import Evidence
from content_joint.native_model import KEYS, Native12
from content_joint.objectives import IndependentObjective, NativeObjective
from content_joint.observe import evaluate, save_arrays
from content_joint.service import execute
from content_joint.sources import row_sources
from content_joint.work import evidence_work, native_step_work
from data import DecodedObserver
from independent.accounting import WorkLedger
from independent.learning import CONTENT_PARAMETERS, step_work
from independent.native_adam import NativeAdam, setup_work as adam6_work
from independent.run import cpu_clock, write_json
from model import JointModel


ROOT = Path(__file__).resolve().parents[1]
PRIOR = ROOT / "runs/content-control-train-r2-20261023"
PROBE = ROOT / "runs/content-reconcile-probe-v1-20261023"
UNIT = ROOT / "runs/content-joint-unit-v1-20261023"
FLOW_UNIT = ROOT / "runs/content-joint-flow-unit-v1-20261023"
FAMILIES, SEEDS = ("S", "H", "A", "N"), (11, 23, 47)
CHECKPOINTS = (1, 128, 256, 512)
CAP, CPU_CAP = 12_000_000_000, 10.
TAIL_UNITS, TAIL_CPU = 500_000_000, 2.
PROGRESS = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity():
    sources = list(ROOT.glob("*.py")) + list((ROOT / "independent").glob("*.py"))
    sources += list((ROOT / "content_reconcile").glob("*.py"))
    sources += list((ROOT / "content_joint").glob("*.py"))
    sources += [ROOT / "content_joint/adam4.c", ROOT / "content_joint/PROTOCOL.md",
                ROOT / "content_joint/CALLS.json", ROOT / "content_joint/train_profile.json"]
    inputs = [PRIOR / "build.json", PRIOR / "train-result.json", PRIOR / "train-inputs.npz",
              PRIOR / "build/libjoint.so", PROBE / "analysis.json",
              PROBE / "evidence/audit-result.json", UNIT / "hand-ledger.json",
              UNIT / "adam4/compile.json", UNIT / "adam4/libsemantic4.so",
              Path(str(UNIT) + ".execution.json"), Path(str(UNIT) + ".console.txt")]
    inputs += [FLOW_UNIT / "hand-ledger.json", Path(str(FLOW_UNIT) + ".execution.json"),
               Path(str(FLOW_UNIT) + ".console.txt")]
    for seed in SEEDS:
        inputs += [PRIOR / f"base-{seed}.npz", PROBE / f"R-{seed}.npz"]
        inputs += [PRIOR / f"{f}-{seed}-0.01/model.npz" for f in ("S", "H", "A")]
    return dict(sources={str(p.relative_to(ROOT)): sha(p) for p in sorted(sources)},
                inputs={str(p.relative_to(ROOT)): sha(p) for p in sorted(inputs)})


def call_plan():
    slots, calls = [], []
    for si, seed in enumerate(SEEDS):
        recipes = ("independent", "native") if si % 2 == 0 else ("native", "independent")
        for ri, recipe in enumerate(recipes):
            round_index = 2 * si + ri
            families = FAMILIES[round_index % 4:] + FAMILIES[:round_index % 4]
            slots += [dict(ordinal=len(slots) + j, family=f, recipe=recipe, seed=seed,
                           rng_seed=seed + 10000) for j, f in enumerate(families)]
        for fi, family in enumerate(FAMILIES[si % 4:] + FAMILIES[:si % 4]):
            profiles = (("independent", "KEEP"), ("independent", "log2"), ("native", "native"))
            if (si + fi) % 2:
                profiles = profiles[::-1]
            for recipe, profile in profiles:
                pi = ("KEEP", "log2", "native").index(profile)
                calls.append(dict(ordinal=len(calls), family=family, recipe=recipe,
                    seed=seed, profile=profile, rows=64,
                    sampler_seed=1_800_000 + FAMILIES.index(family) * 100_000 + seed * 10 + pi))
    return dict(slots=slots, service_calls=calls, models_per_family=6,
        new_actual_service_calls_per_family=9, new_actual_service_requests_per_family=576,
        total_new_service_calls=36, total_new_service_requests=2304,
        service_cohort="64 np.linspace indices from existing768 inner TRAIN rows",
        initial_forward_calls_shared=6, historical_S_forward_calls_shared=3,
        final_forward_calls_per_family=6, quality_rows_per_call=768,
        native_zero_controls_shared=3, native_full_Q_audits_shared=3,
        native_full_Q_audits_per_family=3,
        intermediate_checkpoint_updates=list(CHECKPOINTS),
        intermediate_rows="128 fit+128 inner; eight complete physical sources each",
        aliases_add_calls=0, inherited_old_calibration_requests=64)


def clone(base):
    model = JointModel.__new__(JointModel)
    model.dimensions = tuple(base.dimensions)
    model.params = {key: value.copy() for key, value in base.params.items()}
    model._moments, model.updates = {}, 0
    return model


def link(source, target):
    try:
        os.link(source, target)
    except OSError:
        target.write_bytes(Path(source).read_bytes())


def build(out, frozen_path):
    frozen = json.loads(Path(frozen_path).read_text())
    if identity() != frozen["identity"]:
        raise ValueError("source/input freeze mismatch")
    plan = json.loads((ROOT / "content_joint/CALLS.json").read_text())
    if plan != call_plan():
        raise ValueError("call/slot identity changed")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    PROGRESS.update(out=str(out), phase="common", slots=[], service=[])
    old = json.loads((PRIOR / "build.json").read_text())
    unit = json.loads(Path(str(UNIT) + ".execution.json").read_text())
    hand = json.loads((UNIT / "hand-ledger.json").read_text())
    flow_unit = json.loads(Path(str(FLOW_UNIT) + ".execution.json").read_text())
    flow_hand = json.loads((FLOW_UNIT / "hand-ledger.json").read_text())
    compiled = json.loads((UNIT / "adam4/compile.json").read_text())
    if unit["exit_code"] or flow_unit["exit_code"] or compiled["exit_code"]:
        raise RuntimeError("numerical preflight failed")
    if (compiled["source_sha256"] != sha(ROOT / "content_joint/adam4.c")
            or compiled["library_sha256"] != sha(UNIT / "adam4/libsemantic4.so")
            or old["compiler"]["library_sha256"] != sha(PRIOR / "build/libjoint.so")):
        raise RuntimeError("optimizer binary/source provenance mismatch")
    shared = WorkLedger("shared-native-portfolio", CAP)
    shared.record("inherited_base_preparation", units=old["shared_ledger"]["consumed_units"],
                  inherited_base_content_updates=1500, inherited_decoder_updates=900)
    shared.record("hand_numeric_preparation", units=hand["consumed_units"])
    shared.record("hand_flow_preparation", units=flow_hand["consumed_units"])
    PROGRESS["shared"] = shared
    Image.preinit()  # Required PNG plugin setup; no dummy output.
    with np.load(PRIOR / "train-inputs.npz", allow_pickle=False) as data:
        fit_x, fit_y = data["fit_full"].copy(), data["fit_labels"].copy()
        inner_x, inner_y = data["inner_full"].copy(), data["inner_labels"].copy()
    profile = json.loads((ROOT / "content_joint/train_profile.json").read_text())
    fit_sources, inner_sources, physical = row_sources(profile, old, shared)
    write_json(out / "source-map.json", dict(fit_rows=fit_sources, inner_rows=inner_sources,
        physical_sources=physical, note="TRAIN source metadata/order reconstructed; noisy input bytes reused unchanged"))
    bases, observers, zero = {}, {}, {}
    for seed in SEEDS:
        base = JointModel.load(PRIOR / f"base-{seed}.npz")
        bases[seed] = base
        with np.load(PROBE / f"R-{seed}.npz", allow_pickle=False) as r:
            text, image, distances, reward = [r[key].copy() for key in ("text_sem", "image_sem", "distances", "reward")]
        if not np.array_equal(text, np.arange(12)) or not np.array_equal(image, np.arange(12)):
            raise RuntimeError("actual decoder semantic identity no longer holds")
        if np.min(np.partition(distances, 1, axis=1)[:, 1] - distances.min(1)) <= 1 / 255:
            raise RuntimeError("actual uint8 semantic margin no longer certified")
        observers[seed] = DecodedObserver((text, image, None, distances), reward)
        for family in ("S", "H", "A"):
            reference = JointModel.load(PRIOR / f"{family}-{seed}-0.01/model.npz")
            if any(not np.array_equal(reference.params[k], base.params[k]) for k in ("decoder", "decoder_bias")):
                raise RuntimeError("R provenance and fixed base decoder differ")
            if family == "S":
                strong = reference
        shared.charge_kernel("decoder_provenance", "frozen_R_semantic_checks",
            compare_ops=24 + 3 * 2496 + 12 * 12 + 12, scalar_ops=12, sort_items=144)
        link(PRIOR / f"base-{seed}.npz", out / f"initial-independent-{seed}.npz")
        native = Native12(base)
        shared.charge_kernel("native_initialization", "sum_base_heads", scalar_ops=396)
        native.save(out / f"initial-native-{seed}.npz")
        shared.record("initial_export", model_bytes=(out / f"initial-native-{seed}.npz").stat().st_size,
                      hardlinked_base_bytes=(out / f"initial-independent-{seed}.npz").stat().st_size)
        zero[seed] = {}
        for recipe, model in (("independent", base), ("native", native)):
            arrays, summary = evaluate(model, recipe, inner_x, inner_y, inner_sources,
                shared, observers[seed], full_audit=True, stage="zero_update_observation")
            save_arrays(out / f"zero-{recipe}-{seed}.npz", arrays, shared, "zero_update_observation")
            zero[seed][recipe] = summary
            if recipe == "independent":
                original = arrays
            else:
                conditional = original["p"] * original["q"]
                conditional /= conditional.sum(1, keepdims=True)
                shared.charge_kernel("native_initialization", "conditioned_law_check",
                    scalar_ops=24 * len(inner_y), div_ops=12 * len(inner_y), compare_ops=12 * len(inner_y))
                if not np.allclose(arrays["s"], conditional, rtol=1e-12, atol=1e-12):
                    raise RuntimeError("native zero law is not conditioned independent law")
        arrays, summary = evaluate(strong, "independent", inner_x, inner_y, inner_sources,
            shared, observers[seed], full_audit=False, stage="historical_S_observation")
        save_arrays(out / f"historical-S-{seed}.npz", arrays, shared, "historical_S_observation")
        write_json(out / f"historical-S-{seed}.json", summary)
    write_json(out / "zero-summary.json", zero)
    write_json(out / "historical-reference-costs.json", dict(
        original_dense={f: dict(CPU=old["costs"][f]["complete_cpu"],
            units=old["ledgers"][f]["consumed_units"]) for f in ("S", "H", "A")},
        e7de_repaired=json.loads((PROBE / "evidence/audit-result.json").read_text())["costs"],
        historical_N="parent reference not available in this isolated branch; no claim of comparison",
        scope="historical benchmarks, never free selectable candidates in the new portfolio"))
    (out / "build").mkdir()
    link(UNIT / "adam4/libsemantic4.so", out / "build/libsemantic4.so")
    link(PRIOR / "build/libjoint.so", out / "build/libjoint.so")
    diagnostic_x = np.concatenate((fit_x[:128], inner_x[:128]))
    diagnostic_y = np.concatenate((fit_y[:128], inner_y[:128]))
    diagnostic_sources = fit_sources[:128] + inner_sources[:128]
    np.savez_compressed(out / "diagnostic-rows.npz", fit_indices=np.arange(128),
                        inner_indices=np.arange(128), source_ids=np.asarray(diagnostic_sources),
                        labels=diagnostic_y)
    actual_common_CPU = cpu_clock()
    preflight_CPU = unit["complete_preflight_CPU"] + flow_unit["complete_preflight_CPU"]
    common_CPU = old["common_cpu"] + preflight_CPU + actual_common_CPU
    if common_CPU + TAIL_CPU >= CPU_CAP or shared.consumed_units + TAIL_UNITS >= CAP:
        raise RuntimeError("no affordable paired training allowance")
    quota_CPU = (CPU_CAP - common_CPU - TAIL_CPU) / 6
    quota_units = (CAP - shared.consumed_units - TAIL_UNITS) // 6
    ledgers, costs, objects, summaries = {}, {}, {}, {}
    for family in FAMILIES:
        ledger = WorkLedger(family, CAP)
        ledger.attribute_shared(shared)
        ledgers[family], costs[family], summaries[family] = ledger, dict(active_CPU=0., initialization_CPU=0.), {}
    PROGRESS.update(ledgers=ledgers, costs=costs, common_CPU=common_CPU, quota_CPU=quota_CPU,
                    quota_units=quota_units, phase="training")
    for slot in plan["slots"]:
        family, recipe, seed = slot["family"], slot["recipe"], slot["seed"]
        begin, ledger = cpu_clock(), ledgers[family]
        slot_initial_units = ledger.consumed_units
        folder = out / f"{family}-{recipe}-{seed}"
        folder.mkdir()
        model = clone(bases[seed]) if recipe == "independent" else Native12(bases[seed])
        keys = CONTENT_PARAMETERS if recipe == "independent" else KEYS
        if recipe == "native":
            ledger.charge_kernel("native_initialization", "sum_base_heads", scalar_ops=396)
        ledger.charge_kernel(recipe + "_optimizer_setup", "finite_state_binding",
            **(adam6_work(model) if recipe == "independent" else adam4_work(model)))
        optimizer = (NativeAdam(model, out / "build/libjoint.so") if recipe == "independent"
                     else Adam4(model, out / "build/libsemantic4.so"))
        evidence = Evidence(model, keys, optimizer, ledger)
        objective_type = IndependentObjective if recipe == "independent" else NativeObjective
        objective = objective_type(family, model, observers[seed].reward, evidence, ledger)
        init_CPU = cpu_clock() - begin
        costs[family]["initialization_CPU"] += init_CPU
        ledger.record(recipe + "_initialization", copied_parameter_bytes=sum(v.nbytes for v in model.params.values()))
        initialization_units = ledger.consumed_units
        inventory = step_work(model.dimensions, family, 64) if recipe == "independent" else native_step_work(family, 64)
        base_step_units = ledger.estimate_kernel(**inventory)
        elements = sum(model.params[key].size for key in keys)
        trace_units = ledger.estimate_kernel(**evidence_work(elements)) + (5 if recipe == "independent" else 0)
        rng = np.random.default_rng(slot["rng_seed"])
        losses, ce, utility, checkpoints = [], [], [], []
        train_begin, unit_begin = cpu_clock(), ledger.consumed_units
        PROGRESS.update(current_slot=slot, model=model, evidence=evidence, folder=str(folder))
        while True:
            next_step = len(losses) + 1
            checkpoint = next_step in CHECKPOINTS
            extra_units = 25_600_000 if checkpoint else 0
            needed = base_step_units + trace_units + (elements if next_step == 1 else 0) + extra_units
            if ledger.consumed_units - unit_begin + needed > quota_units:
                stop = "slot_unit_preflight"
                break
            if cpu_clock() - train_begin >= quota_CPU - (.10 if checkpoint else .01):
                stop = "slot_CPU_preflight"
                break
            index = rng.integers(len(fit_y), size=64)
            loss = objective.step(model, fit_x[index], fit_y[index], .01, ledger=ledger)
            losses.append(loss)
            ce.append(objective.last["ce"])
            utility.append(np.nan if objective.last["utility"] is None else objective.last["utility"])
            if checkpoint:
                witness_begin_units = ledger.consumed_units
                arrays, values = evaluate(model, recipe, diagnostic_x, diagnostic_y,
                    diagnostic_sources, ledger, observers[seed], full_audit=False, stage="fixed_checkpoint")
                arrays["training_batch_indices"] = index
                arrays["diagnostic_partition"] = np.asarray(["fit"] * 128 + ["inner"] * 128)
                arrays["training_batch_labels"] = fit_y[index]
                arrays["training_batch_sources"] = np.asarray([fit_sources[i] for i in index])
                for key in ("p", "q", "s"):
                    if key in objective.last:
                        arrays["training_batch_" + key] = objective.last[key]
                arrays.update({"parameter/" + k: model.params[k].copy() for k in keys})
                arrays.update({"gradient/" + k: evidence.last[k].copy() for k in keys})
                arrays.update({"Adam_clock/" + k: np.asarray(model._moments[k][2]) for k in keys})
                save_arrays(folder / f"checkpoint-{next_step}.npz", arrays, ledger, "fixed_checkpoint")
                if ledger.consumed_units - witness_begin_units > extra_units:
                    raise RuntimeError("fixed checkpoint exceeds declared admission envelope")
                checkpoints.append(dict(update=next_step, values=values,
                    CPU=cpu_clock() - train_begin, units=ledger.consumed_units - unit_begin))
        if not losses:
            raise RuntimeError("no affordable useful update for " + folder.name)
        train_CPU, train_units = cpu_clock() - train_begin, ledger.consumed_units - unit_begin
        model.save(folder / "model.npz")
        ledger.record("export", model_bytes=(folder / "model.npz").stat().st_size)
        evidence.save(folder / "gradient-updates.npz", model, losses, ce, utility)
        row = dict(slot, updates=len(losses), stop=stop, training_CPU=train_CPU,
            training_units_including_checkpoints=train_units, initialization_ledger_end=initialization_units,
            initialization_CPU=init_CPU, initialization_units=initialization_units - slot_initial_units,
            per_step_kernel_units=base_step_units, checkpoints=checkpoints, digest=model.digest(),
            clocks={key: model._moments[key][2] for key in keys})
        if model.updates != len(losses) or any(v != len(losses) for v in row["clocks"].values()):
            raise RuntimeError("actual parameter clocks do not match real complete updates")
        write_json(folder / "candidate.json", row)
        PROGRESS["slots"].append(row)
        objects[family, recipe, seed] = model
        costs[family]["active_CPU"] += cpu_clock() - begin
        if common_CPU + costs[family]["active_CPU"] > CPU_CAP:
            raise RuntimeError(family + " complete CPU cap exceeded during slots")
    PROGRESS["phase"] = "final_observation"
    for seed in SEEDS:
        for family in FAMILIES[SEEDS.index(seed):] + FAMILIES[:SEEDS.index(seed)]:
            begin, ledger = cpu_clock(), ledgers[family]
            for recipe in ("independent", "native"):
                model, folder = objects[family, recipe, seed], out / f"{family}-{recipe}-{seed}"
                if ledger.remaining_units < 100_000_000:
                    raise RuntimeError("final observation admission failed")
                arrays, values = evaluate(model, recipe, inner_x, inner_y, inner_sources,
                    ledger, observers[seed], full_audit=True, stage="final_observation")
                save_arrays(folder / "quality.npz", arrays, ledger, "final_observation")
                restored = (JointModel.load(folder / "model.npz") if recipe == "independent"
                            else Native12.load(folder / "model.npz"))
                if restored.digest() != model.digest():
                    raise RuntimeError("model export/reload digest differs")
                if any(not np.array_equal(model.params[k], bases[seed].params[k]) for k in ("decoder", "decoder_bias")):
                    raise RuntimeError("decoder changed")
                summaries[family][f"{recipe}-{seed}"] = values
            costs[family]["active_CPU"] += cpu_clock() - begin
    PROGRESS["phase"] = "service"
    service_indices = np.linspace(0, len(inner_y) - 1, 64, dtype=int)
    for call in plan["service_calls"]:
        family, recipe, seed = call["family"], call["recipe"], call["seed"]
        begin, ledger = cpu_clock(), ledgers[family]
        if ledger.remaining_units < 64 * 2 * 19236:
            raise RuntimeError("real-service admission failed")
        receipt, elapsed = execute(objects[family, recipe, seed], recipe, call["profile"],
            inner_x[service_indices], inner_y[service_indices],
            [inner_sources[i] for i in service_indices], call["sampler_seed"],
            out / f"service-{family}-{recipe}-{seed}-{call['profile']}.json")
        ledger.record("service", units=receipt["work_units"], actual_service_calls=1,
                      actual_service_requests=64, actual_model_image_renders=64)
        PROGRESS["service"].append(dict(call, total_CPU_ns=elapsed, units=receipt["work_units"]))
        costs[family]["active_CPU"] += cpu_clock() - begin
    actual_before_receipt = cpu_clock()
    scheduler = max(0., actual_before_receipt - actual_common_CPU - sum(c["active_CPU"] for c in costs.values()))
    for family in FAMILIES:
        costs[family].update(inherited_base_CPU=old["common_cpu"],
            new_unit_preflight_CPU=preflight_CPU, actual_new_common_CPU=actual_common_CPU,
            scheduler_CPU=scheduler, complete_CPU=common_CPU + costs[family]["active_CPU"] + scheduler,
            complete_units=ledgers[family].consumed_units)
        if costs[family]["complete_CPU"] > CPU_CAP:
            raise RuntimeError(family + " complete CPU cap exceeded")
    write_json(out / "quality-summary.json", summaries)
    write_json(out / "service-summary.json", PROGRESS["service"])
    result = dict(exit_code=0, formal_data_opened=False, source_commit=frozen["source_commit"],
        identity=frozen["identity"], plan=plan, costs=costs,
        ledgers={f: l.snapshot() for f, l in ledgers.items()}, shared_ledger=shared.snapshot(),
        inherited_shared_ledger=old["shared_ledger"], inherited_unit_hand_ledger=hand,
        inherited_flow_hand_ledger=flow_hand,
        inherited_old_shared_CPU=old["common_cpu"], inherited_old_independent_compile_CPU=old["compiler"]["cpu_seconds"],
        new_native_compile=compiled, unit_preflight=unit, flow_preflight=flow_unit,
        common_CPU=common_CPU, quota_CPU=quota_CPU, quota_units=quota_units,
        slot_results=PROGRESS["slots"], actual_new_build_CPU_before_receipt=actual_before_receipt,
        architecture_cost_scope="same six-model portfolio per family; no best-all-budget static claim",
        administrative_tail="final lossless summaries/receipt retained by outer launcher, no training credit",
        old_e7de_ledgers_unchanged=True)
    write_json(out / "build.json", result)
    PROGRESS["phase"] = "complete"
    return result


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "freeze", "run"):
        p = sub.add_parser(command)
        p.add_argument("--out", type=Path, required=True)
        if command == "run":
            p.add_argument("--freeze", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        write_json(args.out, call_plan())
    elif args.command == "freeze":
        write_json(args.out, dict(identity=identity(), source_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip()))
    else:
        try:
            result = build(args.out, args.freeze)
            print(json.dumps(dict(exit_code=0, costs=result["costs"]), sort_keys=True))
        except BaseException:
            args.out.mkdir(parents=True, exist_ok=True)
            if "model" in PROGRESS:
                model, folder = PROGRESS["model"], Path(PROGRESS["folder"])
                model.save(folder / "partial-model.npz")
                if PROGRESS["evidence"].first is not None:
                    arrays = {"moment1/" + key: v[0] for key, v in model._moments.items()}
                    arrays.update({"moment2/" + key: v[1] for key, v in model._moments.items()})
                    np.savez_compressed(folder / "partial-moments.npz", **arrays)
            write_json(args.out / "failure.json", dict(error=traceback.format_exc(), phase=PROGRESS.get("phase"),
                slots=PROGRESS.get("slots"), service=PROGRESS.get("service"),
                costs=PROGRESS.get("costs"), actual_CPU=cpu_clock(),
                ledgers={f: l.snapshot() for f, l in PROGRESS.get("ledgers", {}).items()},
                shared=PROGRESS["shared"].snapshot() if "shared" in PROGRESS else None))
            raise


if __name__ == "__main__":
    main()
