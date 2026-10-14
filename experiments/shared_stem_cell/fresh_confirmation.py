"""Fresh public-text confirmation of a PREVIOUSLY selected ridge candidate.

No training, new model choice, label-driven sampling, or production activation.
Old exact/normalized text is excluded. Confirmation and evaluation predictions
are sealed together before any new labels; only confirmation labels choose bank
versus the already frozen candidate. IID/source-family independence is unverified.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch

from experiments.shared_stem_cell import consolidation as c, execution as e
from experiments.shared_stem_cell import residual_consolidation as rc
from experiments.shared_stem_cell import head_artifacts as h
from experiments.shared_stem_cell.retention_confirmation import paired_confirmation

MODEL_REVISION = "abc32620dd4f6ab06f5fbe905dc25f310618e09f"
DATA_REVISION = "eb185aade064a813bc0b7f42de02595523103ca4"
PER_PHASE = 512


def normalized(text):
    return e.sha(" ".join(text.casefold().split()).encode())


def cohort(texts, excluded, *, per_phase=PER_PHASE):
    """Text column ONLY; retain exact sizes, normalized dedup and old exclusions."""
    e.integer(per_phase, 2, 4096, "confirmation phase size")
    if per_phase % 2 or not isinstance(excluded, list) or not all(isinstance(v,str) for v in excluded):
        raise e.InputError("even phase size and original text exclusions required")
    seen = {normalized(v) for v in excluded}
    candidates = []
    for index,text in enumerate(texts):
        if index >= 16384:
            raise e.InputError("bounded public text column required")
        if isinstance(text,str) and 0 < len(text.encode()) <= 768:
            fingerprint = e.sha(text.encode())
            candidates.append((e.sha(("hepta-confirmation-v1:"+fingerprint).encode()),index,text,fingerprint))
    selected = []
    for _,index,text,fingerprint in sorted(candidates):
        key = normalized(text)
        if key in seen:
            continue
        seen.add(key)
        position = len(selected)
        selected.append({"case_id": f"ag-news:test:{index}", "source_index": index,
            "text": text, "text_sha256": fingerprint, "normalized_sha256": key,
            "cell": position % 2,
            "split": "confirmation" if position < per_phase else "evaluation"})
        if len(selected) == 2*per_phase:
            return selected
    raise e.InputError("insufficient fresh eligible records; never shrink the cohort")


def load_panel(study, consolidation, producer_sha, consolidation_sha):
    """Reload the existing teacher/shared/ridge contracts, anchored outside them."""
    read = lambda p,s: e.decode(e.bound_file(p,h._digest(s),16*1024**2))
    producer = read(study / "execution/report.json",producer_sha)
    config = read(study / "manifest.json",producer["manifest_sha256"])
    acquisition = e.decode(h._read(study / "acquisition.json",65536))
    if (config["model"]["model_id"] != "jhu-clsp/mmBERT-small"
            or config["model"]["revision"] != MODEL_REVISION
            or acquisition["dataset_id"] != "fancyzhx/ag_news"
            or acquisition["dataset_revision"] != DATA_REVISION
            or config["cells"] != 2 or config["classes"] != 4
            or config["dataset"]["path"] != "dataset.jsonl" or config["model"]["path"] != "model"
            or config.get("temporal") is not False):
        raise e.InputError("fixed qualified public model/data/profile required")
    original,cases_labels = e.dataset(study / "dataset.jsonl",config["dataset"]["sha256"],4,2,False)
    del cases_labels
    result = read(consolidation / "report.json",consolidation_sha)
    selected = read(consolidation / "selection.json",result["selection_sha256"])
    ridge = read(consolidation / "ridge-selection.json",result["ridge"]["selection_sha256"])
    origin,receipt = selected["origin"],ridge["selection"]
    if (origin != ridge["origin"] or origin["producer_report_sha256"] != producer_sha
            or result["producer_report_sha256"] != producer_sha
            or origin["logical_cells_in_one_hot_order"] != [0,1]
            or receipt.get("fitting_profile") != "centered_logit_ridge_v1"
            or result["ridge"]["selected"] != receipt["selected"]):
        raise e.InputError("producer/candidate origin or frozen selection drift")
    training = sorted(producer["training"]["gated"],key=lambda v:v["cell"])
    teacher_items = [v["offline_head_artifacts"]["learned"] for v in training]
    if (teacher_items != origin["teacher_receipts"] or [v["cell"] for v in training] != [0,1]
            or any(item["relative_path"] != f"cell-{i}/learned" for i,item in enumerate(teacher_items))):
        raise e.InputError("original teacher identity mismatch")
    entries = [(study / "execution/heads/gated" / item["relative_path"],item) for item in teacher_items]
    entries.append((consolidation / "heads/supervised",selected["heads"]["supervised"]))
    for mode in rc.MODES:
        if len(ridge["heads"][mode]) != 2:
            raise e.InputError("complete ridge Cell inventory required")
        entries.extend((consolidation / "ridge-heads" / mode / f"cell-{i}",item)
                       for i,item in enumerate(ridge["heads"][mode]))
    # Inspect every named allocation BEFORE loading the first component.
    total = 0
    for path,item in entries:
        manifest = read(path / "manifest.json",item["manifest_sha256"])
        binding = h._binding(item["binding"])
        if (manifest["binding"] != binding or binding["dataset_sha256"] != config["dataset"]["sha256"]
                or binding["stem_sha256"] != e.sha(e.canonical(config["model"]))
                or binding["scope"] != original[0].scope):
            raise e.InputError("candidate scope/Stem/source mismatch")
        total += 4*h._shape_count(manifest["architecture"])
    if total > 64*1024**2:
        raise e.InputError("confirmation panel allocation budget")
    models = [h.load_head(path,item["manifest_sha256"],item["binding"]) for path,item in entries]
    teachers,shared = tuple(models[:2]),models[2]
    fitted = {mode: tuple(models[3+2*i:5+2*i]) for i,mode in enumerate(rc.MODES)}
    if (c.bank_identity(teachers)[2] != receipt["teacher_identities"]
            or e.parameters(shared) != receipt["shared_identity"]
            or {k:[e.parameters(m) for m in v] for k,v in fitted.items()} != receipt["head_identities"]):
        raise e.InputError("loaded panel differs from frozen candidate identities")
    lock = {"producer_report_sha256": producer_sha, "consolidation_report_sha256": consolidation_sha,
        "ridge_selection_sha256": result["ridge"]["selection_sha256"], "selected": receipt["selected"],
        "parameter_counts": receipt["parameter_counts"], "component_manifests": [item["manifest_sha256"] for _,item in entries],
        "source_simulated_encoder": producer["encoding"]["simulated_encoder"],
        "scope": original[0].scope, "model_revision": MODEL_REVISION, "dataset_revision": DATA_REVISION,
        "profile": receipt["profile"], "loaded_parameter_bytes": total,
        "source_sha256": {name:e.sha((Path(__file__).parent/name).read_bytes())
                            for name in ("fresh_confirmation.py","retention_confirmation.py")}}
    return (teachers,shared,fitted,receipt),config,original,lock


def evaluate_sealed(output, prediction_sha, candidate_lock, rows, label_at):
    """No fitting or alternative-candidate selection; evaluation labels enter LAST."""
    payload = e.decode(e.bound_file(output / "predictions.json",prediction_sha,16*1024**2))
    if (not rows or len(rows) > 8192 or len({r["source_index"] for r in rows}) != len(rows)
            or set(r["split"] for r in rows) != {"confirmation","evaluation"}
            or payload["candidate_lock_sha256"] != e.sha(e.canonical(candidate_lock))
            or payload["cohort_sha256"] != e.sha(e.canonical(rows))
            or payload["case_ids"] != [r["case_id"] for r in rows]):
        raise e.InputError("confirmation prediction order mismatch")
    e.bound_file(output / "candidate-lock.json",payload["candidate_lock_sha256"])
    e.bound_file(output / "cohort.json",payload["cohort_sha256"])
    names = {"bank","shared",*rc.MODES}
    if set(payload["predictions"]) != names:
        raise e.InputError("missing frozen panel predictions")
    probabilities = {}
    for name,values in payload["predictions"].items():
        p = torch.tensor(values,dtype=torch.float64)
        if (p.shape != (len(rows),4) or not bool(torch.isfinite(p).all())
                or bool(((p<0)|(p>1)).any()) or not torch.allclose(p.sum(-1),torch.ones(len(p),dtype=p.dtype),atol=1e-5,rtol=0)):
            raise e.InputError("complete finite candidate probabilities required")
        probabilities[name] = p
    proposed = candidate_lock["selected"]
    if proposed not in names:
        raise e.InputError("unknown original candidate")
    indices = [i for i,r in enumerate(rows) if r["split"] == "confirmation"]
    y_confirm = [e.integer(label_at(rows[i]["source_index"]),0,3,"confirmation label") for i in indices]
    routes = [rows[i]["cell"] for i in indices]
    bound = paired_confirmation(probabilities["bank"][indices].argmax(-1).tolist(),
        probabilities[proposed][indices].argmax(-1).tolist(),y_confirm,routes,cells=2,classes=4)
    smaller = candidate_lock["parameter_counts"][proposed] < candidate_lock["parameter_counts"]["bank"]
    chosen = proposed if smaller and bound["supported_under_iid"] else "bank"
    decision = {"proposed":proposed,"chosen":chosen,"bound":bound,"strictly_smaller":smaller,
        "predictions_sha256":prediction_sha,"candidate_lock_sha256":e.sha(e.canonical(candidate_lock)),
        "confirmation_ids":[rows[i]["case_id"] for i in indices],"confirmation_labels":y_confirm,
        "production_accepted":False,"new_model_selected_on_confirmation":False}
    decision_sha = e.write_once(output / "confirmation.json",decision)
    if e.decode(e.bound_file(output / "confirmation.json",decision_sha)) != decision:
        raise e.InputError("confirmation changed before evaluation")
    test = [i for i,r in enumerate(rows) if r["split"] == "evaluation"]
    y_test = [e.integer(label_at(rows[i]["source_index"]),0,3,"evaluation label") for i in test]
    tr = torch.tensor([rows[i]["cell"] for i in test],dtype=torch.long)
    scores = {k:c.score(p[test].tolist(),torch.tensor(y_test),tr,2) for k,p in probabilities.items()}
    return {"confirmation_sha256":decision_sha,"proposed":proposed,"chosen":chosen,
        "scores":scores,"chosen_score":scores[chosen],"evaluation_labels":y_test,
        "evaluation_ids":[rows[i]["case_id"] for i in test],"assumptions_verified":False,
        "retention_certified":False,"production_accepted":False}


def run(study, consolidation, producer_sha, consolidation_sha, output):
    from datasets import load_dataset
    output.mkdir(parents=True,exist_ok=False)
    try:
        with e.measured() as reload_cost:
            panel,config,old,lock = load_panel(study,consolidation,producer_sha,consolidation_sha)
        lock.update({"phase_size":PER_PHASE,"alpha":0.05,"allowed_excess_error":0.0,
            "exclusion":"all original producer rows, exact plus casefold/whitespace normalized",
            "cohort_order":"SHA256(hepta-confirmation-v1:raw-text-SHA256)",
            "route":"position modulo 2, continuing the public smoke's alternating Cell assignment",
            "new_training_steps":0,"independent_source_families_verified":False})
        e.write_once(output / "candidate-lock.json",lock)
        with e.measured() as acquisition_cost:
            source = load_dataset("fancyzhx/ag_news",revision=DATA_REVISION,split="test",
                                  cache_dir=str(study / "dataset-cache"))
            rows = cohort(source["text"],[case.text for case in old],per_phase=PER_PHASE)
        cohort_sha = e.write_once(output / "cohort.json",rows)
        scope = lock["scope"]
        cases = tuple(e.Case(r["case_id"],r["case_id"],r["split"],None,r["cell"],scope,r["text"]) for r in rows)
        with e.measured() as load_cost:
            encoder = e.LocalEncoder(study / "model",config["model"],config["maximum_tokens"])
        x,encoding_cost = e.encode_cases(encoder,cases,batch_size=config["batch_size"])
        routes = torch.tensor([r["cell"] for r in rows],dtype=torch.long)
        if (encoder.identity != e.sha(e.canonical(config["model"]))
                or bool(encoder.simulated) != lock["source_simulated_encoder"]):
            raise e.InputError("confirmation encoder identity/provenance mismatch")
        predicted = rc.predict(*panel,x,routes)
        encoder.close()
        _,_,_,relocked = load_panel(study,consolidation,producer_sha,consolidation_sha)
        if any(lock[k] != value for k,value in relocked.items()):
            raise e.InputError("source candidate changed during confirmation")
        payload = {"case_ids":[r["case_id"] for r in rows],"cohort_sha256":cohort_sha,
            "candidate_lock_sha256":e.sha(e.canonical(lock)),**predicted}
        seal = e.write_once(output / "predictions.json",payload)
        # First access to source answers is inside this post-seal evaluator.
        expected_text = {r["source_index"]:r["text"] for r in rows}
        def answer(index):
            record = source[index]
            if record["text"] != expected_text[index]:
                raise e.InputError("public source changed before answer access")
            return int(record["label"])
        with e.measured() as evaluation_cost:
            result = evaluate_sealed(output,seal,lock,rows,answer)
        result.update({"schema":"hepta.fresh-confirmation-executed.v1","cohort_sha256":cohort_sha,
            "predictions_sha256":seal,"acquisition":acquisition_cost,"candidate_reload":reload_cost,
            "model_load":load_cost,"encoding":encoding_cost,"feature_sha256":e.tensor_digest(x),
            "confidence_and_scoring":evaluation_cost,
            "extra_optimizer_steps":0,"new_by_exact_content_only":True,"pretraining_clean":False})
        e.write_once(output / "report.json",result)
        return result
    except Exception as error:
        e.write_once(output / "failure.json",{"error":type(error).__name__,"message":str(error),"production_accepted":False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--consolidation",type=Path,required=True)
    parser.add_argument("--producer-sha256",required=True)
    parser.add_argument("--consolidation-sha256",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.study,args.consolidation,args.producer_sha256,args.consolidation_sha256,args.output)
