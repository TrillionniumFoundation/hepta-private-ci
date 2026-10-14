"""Consolidate an externally bound offline feature/Head producer, WITHOUT Encoder.

All original heldout rows remain evaluation-only. This reuses an already exposed
public cohort and is development evidence, not a new independent holdout study.
Existing offline Head format is reused with a DISTINCT cell-conditioned profile.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch

from experiments.shared_stem_cell import consolidation as c, execution as e, feature_replay as f
from experiments.shared_stem_cell.head_artifacts import _digest, _path, _read, export_head, load_head


def study(manifest_path, producer, report_sha256, output, *, partial=False, residual=False, ridge=False):
    if any(type(v) is not bool for v in (partial, residual, ridge)):
        raise e.InputError("exact partial-consolidation option required")
    raw = _read(manifest_path, f.MAX_INDEX)
    config = e.decode(raw)
    producer_raw = e.bound_file(producer / "report.json", _digest(report_sha256), f.MAX_INDEX)
    report = e.decode(producer_raw)
    if (config.get("schema") != "hepta.shared-stem-execution.v1"
            or e.sha(raw) != report["manifest_sha256"] or config.get("export_frozen_features") is not True):
        raise e.InputError("bound frozen-feature producer plan required")
    data_part = Path(config["dataset"]["path"])
    if data_part.is_absolute() or ".." in data_part.parts:
        raise e.InputError("original dataset must remain in its staged directory")
    data = _path(manifest_path.parent / data_part)
    cases, all_labels = e.dataset(data, config["dataset"]["sha256"], config["classes"],
                                config["cells"], config.get("temporal", False))
    receipt = report["frozen_features"]
    if receipt.get("relative_path") != "frozen-features":
        raise e.InputError("fixed producer feature location required")
    with e.measured() as reopening:
        x, archive = f.load_features(producer / "frozen-features", receipt["manifest_sha256"], cases, config,
                                     producer_source_sha256=report["source_sha256"])
        if (receipt.get("shape") != archive["shape"] or receipt.get("tensor_bytes") != archive["tensor_bytes"]
                or receipt.get("simulated_encoder") is not archive["simulated_encoder"]
                or report["encoding"]["simulated_encoder"] is not archive["simulated_encoder"]):
            raise e.InputError("producer/feature provenance mismatch")
        cell_ids = sorted({case.cell for case in cases})
        e.integer(len(cell_ids), 2, 64, "consolidation Cell count")
        training = report["training"]["gated"]
        if sorted(r["cell"] for r in training) != cell_ids:
            raise e.InputError("complete unique teacher cost inventory required")
        teachers, teacher_receipts = [], []
        for cell in cell_ids:
            row = next(r for r in training if r["cell"] == cell)
            item = row["offline_head_artifacts"]["learned"]
            bound = item["binding"]
            if (item["relative_path"] != f"cell-{cell}/learned"
                    or bound["logical_cell"] != str(cell) or bound["scope"] != cases[0].scope
                    or bound["dataset_sha256"] != config["dataset"]["sha256"]
                    or bound["stem_sha256"] != archive["binding"]["stem_sha256"]
                    or bound["feature_profile_sha256"] != archive["binding"]["feature_profile_sha256"]
                    or bound["generation"] != config.get("candidate_generation", 1)):
                raise e.InputError("teacher/feature binding differs")
            model = load_head(producer / "heads" / "gated" / item["relative_path"], item["manifest_sha256"], bound)
            if (e.parameters(model)["sha256"] != row["sha256"] or model.base.in_features != x.shape[1]
                    or model.base.out_features != config["classes"]):
                raise e.InputError("teacher trained parameter identity differs")
            teachers.append(model); teacher_receipts.append(item)
    teachers = tuple(teachers)
    routes = torch.tensor([cell_ids.index(case.cell) for case in cases], dtype=torch.long)
    folds = {split: [i for i, case in enumerate(cases) if case.split == split]
             for split in ("train", "calibration", "holdout", "retention")}
    output.mkdir(parents=True, exist_ok=False)
    origin = {"producer_report_sha256": report_sha256, "feature_manifest_sha256": receipt["manifest_sha256"],
        "logical_cells_in_one_hot_order": cell_ids, "teacher_receipts": teacher_receipts,
        "student_steps": config.get("steps", 40), "seed": config.get("seed", 17),
        "source_sha256": {name: e.sha((Path(__file__).parent / name).read_bytes())
                          for name in ("consolidation.py", "consolidation_study.py", "execution.py")},
        "independent_evaluation": False, "production_accepted": False}
    origin["group_retention_guard_source_sha256"] = e.sha((Path(__file__).parent /
        "consolidation_group_guard.py").read_bytes())
    if partial:
        origin["partial_policy_source_sha256"] = e.sha((Path(__file__).parent / "partial_consolidation.py").read_bytes())
    if residual:
        origin["residual_source_sha256"] = e.sha((Path(__file__).parent / "residual_consolidation.py").read_bytes())
    if ridge:
        origin["ridge_source_sha256"] = e.sha((Path(__file__).parent / "ridge_consolidation.py").read_bytes())
    e.write_once(output / "plan.json", origin)
    try:
        tr, cal = folds["train"], folds["calibration"]
        y = lambda ids: torch.tensor([all_labels[cases[i].case_id] for i in ids], dtype=torch.long)
        models, selection = c.fit_students(teachers, x[tr], routes[tr], y(tr), x[cal], routes[cal], y(cal),
                                           steps=origin["student_steps"], seed=origin["seed"])
        base = dict(teacher_receipts[0]["binding"])
        base.update(logical_cell="shared-cell-conditioned-candidate",
            feature_profile_sha256=e.sha(e.canonical([archive["binding"]["feature_profile_sha256"],
                                                      selection["route_profile"], cell_ids])),
            generation=base["generation"] + 1)
        exports = {}
        with e.measured() as export_cost:
            for name, model in models.items():
                b = {**base, "training_lineage_sha256": e.sha(e.canonical([origin, selection, name]))}
                exports[name] = {**export_head(output / "heads" / name, model, b), "binding": b}
                models[name] = load_head(output / "heads" / name, exports[name]["manifest_sha256"], b)
        if residual:
            from experiments.shared_stem_cell import residual_consolidation as rc
            residual_heads, residual_selection = rc.fit_residuals(teachers, models["supervised"],
                x[tr], routes[tr], y(tr), x[cal], routes[cal], y(cal),
                steps=origin["student_steps"], seed=origin["seed"])
            residual_exports = {}
            with e.measured() as residual_export_cost:
                for mode, heads in residual_heads.items():
                    loaded, residual_exports[mode] = [], []
                    for cell, head in enumerate(heads):
                        binding = {**teacher_receipts[cell]["binding"], "generation": base["generation"],
                            "logical_cell": f"{mode}-cell-{cell}",
                            "feature_profile_sha256": e.sha(e.canonical([archive["binding"]["feature_profile_sha256"],
                                mode, residual_selection["shared_identity"]])),
                            "training_lineage_sha256": e.sha(e.canonical([origin, residual_selection, mode, cell]))}
                        path = output / "residual-heads" / mode / f"cell-{cell}"
                        item = export_head(path, head, binding)
                        loaded.append(load_head(path, item["manifest_sha256"], binding))
                        residual_exports[mode].append({**item, "binding": binding})
                    residual_heads[mode] = tuple(loaded)
            residual_seal = e.write_once(output / "residual-selection.json",
                {"selection": residual_selection, "heads": residual_exports, "origin": origin})
            e.bound_file(output / "residual-selection.json", residual_seal, f.MAX_INDEX)
        if ridge:
            from experiments.shared_stem_cell import ridge_consolidation as rg, residual_consolidation as rc
            ridge_heads, ridge_selection = rg.fit_ridge(teachers, models["supervised"],
                x[tr], routes[tr], x[cal], routes[cal], y(cal))
            ridge_exports = {}
            with e.measured() as ridge_export_cost:
                for mode, heads in ridge_heads.items():
                    loaded, ridge_exports[mode] = [], []
                    for cell, head in enumerate(heads):
                        binding = {**teacher_receipts[cell]["binding"], "generation": base["generation"],
                            "logical_cell": f"ridge-{mode}-cell-{cell}",
                            "feature_profile_sha256": e.sha(e.canonical([archive["binding"]["feature_profile_sha256"],
                                "centered_logit_ridge_v1", mode, ridge_selection["shared_identity"]])),
                            "training_lineage_sha256": e.sha(e.canonical([origin, ridge_selection, mode, cell]))}
                        path = output / "ridge-heads" / mode / f"cell-{cell}"
                        item = export_head(path, head, binding)
                        loaded.append(load_head(path, item["manifest_sha256"], binding))
                        ridge_exports[mode].append({**item, "binding": binding})
                    ridge_heads[mode] = tuple(loaded)
            ridge_seal = e.write_once(output / "ridge-selection.json",
                {"selection": ridge_selection, "heads": ridge_exports, "origin": origin})
            e.bound_file(output / "ridge-selection.json", ridge_seal, f.MAX_INDEX)
        partial_result = None
        if partial:
            from experiments.shared_stem_cell import partial_consolidation as pc
            partial_selection = pc.select(selection, y(cal), routes[cal])
            policy = partial_selection["policy"]
            components = {k: models[policy["student"]] if k == "shared" else teachers[int(k[5:])]
                          for k in policy["components"]}
            bindings = {k: exports[policy["student"]]["binding"] if k == "shared"
                        else teacher_receipts[int(k[5:])]["binding"] for k in components}
            with e.measured() as partial_export:
                bundle_sha = pc.export(output / "partial-bundle", components, policy, bindings)
                components, loaded_policy = pc.reopen(output / "partial-bundle", bundle_sha)
            if loaded_policy != policy:
                raise e.InputError("partial policy changed on reopen")
            partial_seal = e.write_once(output / "partial-selection.json",
                {"selection": partial_selection, "bundle_sha256": bundle_sha})
            e.bound_file(output / "partial-selection.json", partial_seal, f.MAX_INDEX)
        seal = e.write_once(output / "selection.json", {"origin": origin, "selection": selection, "heads": exports})
        selected = e.decode(e.bound_file(output / "selection.json", seal, f.MAX_INDEX))
        if selected != {"origin": origin, "selection": selection, "heads": exports}:
            raise e.InputError("selection changed before inference")
        test = [i for i, case in enumerate(cases) if case.split in {"holdout", "retention"}]
        predicted = c.predict(teachers, models, selected["selection"], x[test], routes[test])
        if partial:
            partial_result = pc.predict(components, loaded_policy, x[test], routes[test])
            predicted["predictions"]["partial_selected"] = partial_result["probabilities"]
            predicted["partial_execution"] = partial_result["execution"]
            predicted["partial_selection_sha256"] = partial_seal
        if residual:
            residual_result = rc.predict(teachers, models["supervised"], residual_heads,
                                         residual_selection, x[test], routes[test])
            predicted["predictions"].update({k: residual_result["predictions"][k] for k in rc.MODES})
            predicted["predictions"]["residual_selected"] = residual_result["predictions"][residual_selection["selected"]]
            predicted["residual_execution"] = residual_result
            predicted["residual_selection_sha256"] = residual_seal
        if ridge:
            ridge_result = rc.predict(teachers, models["supervised"], ridge_heads, ridge_selection, x[test], routes[test])
            predicted["predictions"].update({f"ridge_{k}": ridge_result["predictions"][k] for k in rc.MODES})
            predicted["predictions"]["ridge_selected"] = ridge_result["predictions"][ridge_selection["selected"]]
            predicted["ridge_execution"] = ridge_result
            predicted["ridge_selection_sha256"] = ridge_seal
        payload = {"case_ids": [cases[i].case_id for i in test],
                   "input_digests": [cases[i].input_digest for i in test],
                   "routes": routes[test].tolist(), "selection_sha256": seal, **predicted}
        prediction_sha = e.write_once(output / "predictions.json", payload)
        saved = e.decode(e.bound_file(output / "predictions.json", prediction_sha, f.MAX_TENSOR))
        expected_arms = set(c.ARMS) | ({"partial_selected"} if partial else set())
        if residual:
            expected_arms |= {*rc.MODES, "residual_selected"}
        if ridge:
            expected_arms |= {*(f"ridge_{k}" for k in rc.MODES), "ridge_selected"}
        if set(saved["predictions"]) != expected_arms or saved["case_ids"] != payload["case_ids"]:
            raise e.InputError("complete consolidation predictions required")
        from experiments.shared_stem_cell import consolidation_group_guard
        group_audit = consolidation_group_guard.evaluate(saved["predictions"],
            [cases[i] for i in test], [all_labels[cases[i].case_id] for i in test])
        scores = {}
        for split in ("holdout", "retention"):
            ids = [j for j, i in enumerate(test) if cases[i].split == split]
            if ids:
                scores[split] = {k: c.score([v[j] for j in ids], y([test[j] for j in ids]),
                                           routes[[test[j] for j in ids]], len(cell_ids))
                                 for k,v in saved["predictions"].items()}
        # All source files remain bound after training; no selected Head is mutated.
        e.bound_file(data, config["dataset"]["sha256"])
        if _read(manifest_path, f.MAX_INDEX) != raw:
            raise e.InputError("producer plan changed during consolidation")
        f.load_features(producer / "frozen-features", receipt["manifest_sha256"], cases, config,
                        producer_source_sha256=report["source_sha256"])
        for model, item in zip(teachers, teacher_receipts):
            reloaded = load_head(producer / "heads/gated" / item["relative_path"], item["manifest_sha256"], item["binding"])
            if e.parameters(model) != e.parameters(reloaded):
                raise e.InputError("original teacher file changed")
        result = {"schema": "hepta.consolidation-executed.v1", "selection_sha256": seal,
            "predictions_sha256": prediction_sha, "scores": scores, "source_family_retention": group_audit,
            "selected": selection["selected"],
            "parameter_counts": selection["parameter_counts"], "producer_report_sha256": report_sha256,
            "features_and_teacher_reopen": reopening, "candidate_export_and_reopen": export_cost,
            "source_simulated_encoder": archive["simulated_encoder"], "encoder_calls": 0,
            "inherited_teacher_training": {"steps": sum(r["steps"] for r in training),
                "examples_processed": sum(r["examples_processed"] for r in training), "rerun": False},
            "student_training_steps": selection["executed_student_steps"],
            "candidate_only_parameter_reduction_not_peak_memory": True,
            "route_labels_shared_class_schema": True, "independent_evaluation": False,
            "new_holdout": False, "optimizer_resume": False, "generator_consolidation": False,
            "production_accepted": False}
        if partial:
            result["partial"] = {"selected": partial_selection["selected"], "policy": policy,
                "selection_sha256": partial_seal, "bundle_sha256": bundle_sha,
                "export_and_reopen": partial_export, "execution": partial_result["execution"],
                "additional_training_steps": 0, "production_accepted": False}
        if residual:
            result["residual"] = {"selected": residual_selection["selected"],
                "selection_sha256": residual_seal, "parameter_counts": residual_selection["parameter_counts"],
                "additional_optimizer_steps": residual_selection["executed_optimizer_steps"],
                "export_and_reopen": residual_export_cost, "execution": residual_result["inference_costs"],
                "retention_certified": False, "production_accepted": False}
        if ridge:
            result["ridge"] = {"selected": ridge_selection["selected"], "selection_sha256": ridge_seal,
                "parameter_counts": ridge_selection["parameter_counts"], "additional_optimizer_steps": 0,
                "svd_calls": ridge_selection["executed_svd_calls"], "rho": rg.RHO,
                "export_and_reopen": ridge_export_cost, "execution": ridge_result["inference_costs"],
                "same_objective_as_adamw_kl": False, "retention_certified": False, "production_accepted": False}
        e.write_once(output / "report.json", result)
        return result
    except Exception as error:
        e.write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error),
                                               "production_accepted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--residual", action="store_true")
    parser.add_argument("--ridge", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(2)
    study(args.manifest, args.producer, args.report_sha256, args.output, partial=args.partial, residual=args.residual, ridge=args.ridge)
