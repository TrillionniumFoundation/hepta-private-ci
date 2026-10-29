"""Source-bound A1/A2 train, development, freeze and one-shot confirmation CLI."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import time

import numpy as np
import scipy

from .diagnostics import meta_check, physical_check
from .meta import exact_inner_baseline, fit_meta, make_meta_examples, meta_objective
from .training import PARAMETER_BOUNDS, fit_joint, make_contexts, objective


PACKAGE = Path(__file__).resolve().parent
PROTOCOL = PACKAGE/"ADAPTIVE_PROTOCOL.json"
CONFIRMATION_REGISTRY = PACKAGE/"evidence"/"confirmation_registry"
SOURCE_FILES = ("__init__.py","gradients.py","training.py","meta.py","diagnostics.py",
                "adaptive_study.py","ADAPTIVE_PROTOCOL.json","CONTRACT.md","requirements.txt",
                "tests/test_gradients.py","tests/test_training.py","tests/test_meta.py",
                "tests/test_study.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as handle:
        json.dump(value,handle,indent=2,sort_keys=True,allow_nan=False)
        handle.write("\n")


def identity():
    return {"source_sha256":{name:digest(PACKAGE/name) for name in SOURCE_FILES},
            "runtime":{"python":platform.python_version(),"numpy":np.__version__,"scipy":scipy.__version__}}


def protocol():
    data = json.loads(PROTOCOL.read_text())
    for section,key in (("physical_training","bounds"),("gradient_and_meta_study","shape_bounds")):
        if not np.array_equal(data[section][key],PARAMETER_BOUNDS):
            raise ValueError("Registered bounds disagree with the implemented optimizer")
        if data[section]["maximum_backtracking_attempts"] != 16:
            raise ValueError("Registered line-search budget disagrees with the optimizer")
    return data


def tree_contract(data):
    config = data["gradient_and_meta_study"]
    return {"physical_parameters":config["physical_parameters"],"inner_steps":config["inner_steps"],
            "inner_learning_rate":config["inner_learning_rate"],"initial_weight":config["inner_weight_initial"],
            "weight_bounds":config["inner_weight_bounds"]}


def contexts(data, split):
    config = data["physical_training"]
    return make_contexts(config["seeds"][split],config["context_count_per_split"],
                         configuration=config["context_generation"])


def examples(data, split):
    config = data["gradient_and_meta_study"]
    return make_meta_examples(config["seeds"][split],config["example_count_per_split"],
                              configuration=config["example_generation"])


def data_binding(rows, split, seed):
    content = [asdict(row) for row in rows]
    canonical = json.dumps(content,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return {"split":split,"seed":seed,"sha256":hashlib.sha256(canonical).hexdigest(),"contexts":content}


def load_checkpoint(path):
    saved = json.loads(Path(path).read_text())
    if saved.get("schema") != "hepta.first-passage.adaptive.checkpoint.v1" or saved["source_identity"] != identity():
        raise ValueError("Checkpoint source/protocol/runtime identity mismatch")
    if saved["study_id"] != protocol()["study_id"]:
        raise ValueError("Checkpoint study identity mismatch")
    return saved


def train(output):
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    data,source = protocol(),identity()
    registration = {"study_id":data["study_id"],"source_identity":source,
                    "registered_at":datetime.now(timezone.utc).isoformat(),"confirmation_opened":False}
    write_new(output/"registration.json",registration)
    try:
        physical_config,meta_config = data["physical_training"],data["gradient_and_meta_study"]
        physical_data,inner,outer = contexts(data,"train"),examples(data,"inner"),examples(data,"outer_train")
        print("Training physical mu, sigma and cancellation rate",flush=True)
        physical = fit_joint(physical_data,initial=physical_config["initial"],steps=physical_config["steps"],
                             learning_rate=physical_config["learning_rate"])
        print("Training SG shape with the complete hard-event tree hypergradient",flush=True)
        meta = fit_meta(inner,outer,initial=meta_config["initial_shape_parameters"],steps=meta_config["outer_steps"],
                        learning_rate=meta_config["outer_learning_rate"],**tree_contract(data))
        checks = {"physical_initial":physical_check(physical["initial"],physical_data),
                  "physical_final":physical_check(physical["final"],physical_data),
                  "meta_initial":meta_check(meta["initial"],inner,outer,tree_contract(data)),
                  "meta_final":meta_check(meta["final"],inner,outer,tree_contract(data))}
        if any(check["maximum_absolute_error"] > 5e-6 for check in checks.values()):
            raise ArithmeticError("Whole-objective gradient qualification failed")
        if identity() != source:
            raise ValueError("Registered sources changed during training")
        saved = {"schema":"hepta.first-passage.adaptive.checkpoint.v1","study_id":data["study_id"],
                 "source_identity":source,"registration_sha256":digest(output/"registration.json"),
                 "physical_training":physical,"meta_training":meta,"gradient_checks":checks,
                 "training_data":{
                     "physical":data_binding(physical_data,"train",physical_config["seeds"]["train"]),
                     "inner":data_binding(inner,"inner",meta_config["seeds"]["inner"]),
                     "outer":data_binding(outer,"outer_train",meta_config["seeds"]["outer_train"])},
                 "confirmation_opened":False,"training_complete":True}
        write_new(output/"checkpoint.json",saved)
    except Exception as error:
        write_new(output/"failure.json",{"error_type":type(error).__name__,"error":str(error)})
        raise
    return {"checkpoint":str(output/"checkpoint.json"),"physical_loss":physical["train_final"],
            "meta_loss":meta["outer_train_final"],"confirmation_opened":False}


def evaluate(saved, split):
    data = protocol()
    started = time.perf_counter()
    physical_data,inner,outer = contexts(data,split),examples(data,"inner"),examples(data,split)
    initial,final = saved["physical_training"]["initial"],saved["physical_training"]["final"]
    physical_initial = objective(initial,physical_data,derivatives=0)[0]
    physical_final = objective(final,physical_data,derivatives=0)[0]
    config = tree_contract(data)
    exact = exact_inner_baseline(inner,outer,**config)
    fixed = meta_objective(saved["meta_training"]["initial"],inner,outer,derivatives=False,**config)
    learned = meta_objective(saved["meta_training"]["final"],inner,outer,derivatives=False,**config)
    return {"schema":"hepta.first-passage.adaptive.evaluation.v1","study_id":data["study_id"],"split":split,
            "source_identity":saved["source_identity"],"physical":{"initial_parameters":initial,"final_parameters":final,
                "initial_expected_loss":physical_initial,"final_expected_loss":physical_final,
                "loss_reduction":physical_initial-physical_final,"kernel_evaluations":2*len(physical_data)},
            "meta":{"exact_expected":exact,"biased_sg":fixed.receipt(),"meta_sg":learned.receipt(),
                    "meta_minus_fixed_expected_loss":learned.objective-fixed.objective,
                    "meta_minus_exact_expected_loss":learned.objective-exact["objective"]},
            "data":{"physical":data_binding(physical_data,split,data["physical_training"]["seeds"][split]),
                    "outer":data_binding(outer,split,data["gradient_and_meta_study"]["seeds"][split])},
            "elapsed_seconds":time.perf_counter()-started,
            "interpretation":"Finite known-law mechanism diagnostic; no population superiority inference."}


def develop(checkpoint, output):
    saved = load_checkpoint(checkpoint)
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    result = evaluate(saved,"development")
    result["checkpoint_sha256"] = digest(checkpoint)
    write_new(output/"development.json",result)
    return {"development":str(output/"development.json"),"confirmation_opened":False}


def freeze(checkpoint, development, output):
    saved = load_checkpoint(checkpoint)
    developed = json.loads(Path(development).read_text())
    if (developed.get("split") != "development" or developed["checkpoint_sha256"] != digest(checkpoint)
            or developed["source_identity"] != identity()):
        raise ValueError("Development evidence does not bind the selected checkpoint")
    result = {"schema":"hepta.first-passage.adaptive.freeze.v1","study_id":saved["study_id"],
              "source_identity":identity(),"checkpoint_sha256":digest(checkpoint),
              "development_sha256":digest(development),"physical_parameters":saved["physical_training"]["final"],
              "shape_parameters":saved["meta_training"]["final"],"confirmation_opened":False}
    write_new(output,result)
    return {"freeze":str(output),"sha256":digest(output),"confirmation_opened":False}


def confirm(checkpoint, frozen, output):
    saved = load_checkpoint(checkpoint)
    freeze_data = json.loads(Path(frozen).read_text())
    if (freeze_data.get("schema") != "hepta.first-passage.adaptive.freeze.v1"
            or freeze_data["source_identity"] != identity() or freeze_data["study_id"] != saved["study_id"]
            or freeze_data["checkpoint_sha256"] != digest(checkpoint)
            or freeze_data["physical_parameters"] != saved["physical_training"]["final"]
            or freeze_data["shape_parameters"] != saved["meta_training"]["final"]):
        raise ValueError("Confirmation source/model/protocol freeze mismatch")
    study_id = saved["study_id"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",study_id):
        raise ValueError("Study identifier is not a safe registry key")
    marker = CONFIRMATION_REGISTRY/f"{study_id}.json"
    if marker.exists():
        raise FileExistsError("This study's confirmation has already been opened")
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    # An exclusive, study-keyed workspace registry remains on failure and also
    # rejects a copied freeze at another path. This is trusted-runner protection,
    # not an external service capable of detecting arbitrary workspace copies.
    write_new(marker,{"study_id":saved["study_id"],"freeze_sha256":digest(frozen),
                      "opened_at":datetime.now(timezone.utc).isoformat(),"output":str(output),
                      "scope":"A1/A2 adaptive gradient and meta study"})
    try:
        result = evaluate(saved,"confirmation")
        result["checkpoint_sha256"],result["freeze_sha256"] = digest(checkpoint),digest(frozen)
        result["confirmation_opened"] = True
        write_new(output/"confirmation.json",result)
    except Exception as error:
        write_new(output/"failure.json",{"error_type":type(error).__name__,"error":str(error)})
        raise
    return {"confirmation":str(output/"confirmation.json"),"confirmation_opened":True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action",required=True)
    for name in ("train","develop","freeze","confirm"):
        action = actions.add_parser(name)
        action.add_argument("--output",required=True)
        if name != "train":
            action.add_argument("--checkpoint",required=True)
        if name == "freeze":
            action.add_argument("--development",required=True)
        if name == "confirm":
            action.add_argument("--freeze",required=True)
    args = parser.parse_args()
    if args.action == "train":
        result = train(args.output)
    elif args.action == "develop":
        result = develop(args.checkpoint,args.output)
    elif args.action == "freeze":
        result = freeze(args.checkpoint,args.development,args.output)
    else:
        result = confirm(args.checkpoint,args.freeze,args.output)
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
