"""Verify retained evidence and recompute statistics without reopening research.

This entry point never calls train/confirm, creates random task contexts, runs
native owners, or executes new rollouts. It reads frozen inputs and existing raw
outputs. Both favorable and unfavorable scientific gates are valid if the
recomputed result agrees with the saved evidence.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import tarfile

import numpy as np

from .retain_evidence import check, restore, safe_name, safe_path, sha_file
from .gradients import outcome_law
from .threshold_policies import ordinary_thresholds
from .threshold_statistics import summarize
from .thresholds import ThresholdContext, renewal_value


PACKAGE = Path(__file__).resolve().parent
ADAPTIVE_CHECKPOINT = "evidence/train_20261029_v2/checkpoint.json"
THRESHOLD_CHECKPOINT = "evidence/threshold_train_20261029_v2/checkpoint.json"
ADAPTIVE_CONFIRMATION = "evidence/confirmation_20261029_v1/confirmation.json"
THRESHOLD_CONFIRMATION = "evidence/threshold_confirmation_20261029_v1/confirmation.json"


def read_json(path):
    return json.loads(Path(path).read_text())


def consistent(actual, expected, label="evidence"):
    """Structural equality with tight floating tolerance; bool results are exact."""
    if isinstance(expected,bool):
        valid = isinstance(actual,bool) and actual == expected
    elif isinstance(expected,(int,float)):
        valid = (not isinstance(actual,bool) and isinstance(actual,(int,float))
                 and math.isfinite(actual) and math.isfinite(expected)
                 and math.isclose(actual,expected,rel_tol=2e-12,abs_tol=2e-12))
    elif isinstance(expected,dict):
        valid = isinstance(actual,dict) and actual.keys() == expected.keys()
        if valid:
            for key in expected:
                consistent(actual[key],expected[key],f"{label}.{key}")
    elif isinstance(expected,list):
        valid = isinstance(actual,list) and len(actual) == len(expected)
        if valid:
            for index,(left,right) in enumerate(zip(actual,expected)):
                consistent(left,right,f"{label}[{index}]")
    else:
        valid = actual == expected
    if not valid:
        raise ValueError(f"Inconsistent {label}")


def verify_sources(package, identity):
    bound = identity.get("source_sha256",identity.get("sha256"))
    if not isinstance(bound,dict) or not bound:
        raise ValueError("Missing frozen source hashes")
    result = {}
    for name,expected in bound.items():
        base = package.parents[1] if name.startswith("experiments/") else package
        path = safe_path(base,name)
        actual = sha_file(path)
        if actual != expected:
            raise ValueError(f"Frozen source digest mismatch: {name}")
        result[str(path)] = actual
    return result


def verify_hash(path, expected):
    if sha_file(path) != expected:
        raise ValueError(f"Evidence digest mismatch: {path}")


def verify_binding(binding):
    encoded = json.dumps(binding["contexts"],sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest() != binding["sha256"]:
        raise ValueError("Serialized context identity mismatch")


def _saved_outer_loss(weight, contexts, physical):
    total = 0.0
    for row in contexts:
        law = outcome_law(row["distance"]-row["feature"]*weight,
                          physical[0]+row["drift_offset"],physical[1],physical[2],
                          row["horizon"],derivatives=0)
        total += 1.0-float(law.probability[row["target"]])
    return total/len(contexts)


def verify_raw_records(records, config):
    count,repeats = config["contexts_per_fit_seed"]["confirmation"],config["rollouts_per_context"]
    expected = [(fit,index) for fit in config["fit_seeds"] for index in range(count)]
    if [(row["fit_seed"],row["context_index"]) for row in records] != expected:
        raise ValueError("Raw context identities/count/order disagree with registration")
    for row in records:
        stratum = config["strata"][row["context_index"] % len(config["strata"])]
        if row["stratum"] != stratum or row["context"]["stratum"] != stratum:
            raise ValueError("Raw stratum assignment disagrees with registration")
        if set(row["arms"]) != set(config["arms"]):
            raise ValueError("Missing or additional raw comparison arm")
        for arm in config["arms"]:
            raw = row["arms"][arm]
            utility = np.asarray(raw["utility"],dtype=float)
            hits = np.asarray(raw["hits"])
            if (utility.shape != (repeats,) or not np.isfinite(utility).all()
                    or hits.shape != (repeats,) or not np.isfinite(hits).all()
                    or np.any(hits < 0) or np.any(hits > row["context"]["budget"])
                    or np.any(hits != np.floor(hits)) or len(raw["last_hit_time"]) != repeats
                    or sum(raw["terminal_counts"].values()) != repeats):
                raise ValueError("Raw rollout contract violation")
            consistent(float(utility.mean()),raw["mean_utility"],"raw utility mean")
    return summarize(records,config)


def _native_archive(folder, manifest_name):
    manifest = read_json(folder/manifest_name)
    archive = safe_path(folder,manifest["archive"])
    verify_hash(archive,manifest["archive_sha256"])
    if archive.stat().st_size != manifest["archive_bytes"]:
        raise ValueError("Native raw archive size mismatch")
    expected = {safe_name(row["path"]):row for row in manifest["files"]}
    if len(expected) != len(manifest["files"]):
        raise ValueError("Duplicate native raw manifest path")
    seen = set()
    with tarfile.open(archive,"r|gz") as tar:
        for member in tar:
            name = safe_name(member.name)
            if (name not in expected or name in seen or member.type != tarfile.REGTYPE
                    or member.linkname or member.size != expected[name]["bytes"]):
                raise ValueError("Unsafe or inconsistent native raw archive member")
            seen.add(name)
            digest = hashlib.sha256()
            with tar.extractfile(member) as handle:
                for block in iter(lambda:handle.read(1024*1024),b""):
                    digest.update(block)
            if digest.hexdigest() != expected[name]["sha256"]:
                raise ValueError("Native raw file digest mismatch")
    if seen != set(expected):
        raise ValueError("Native archive omitted registered files")
    return {"archive_sha256":manifest["archive_sha256"],"raw_files_verified":len(seen)}


def verify(package=PACKAGE, *, restore_missing=False):
    package = Path(package).resolve()
    manifest = package/"evidence/retained/manifest.json"
    if restore_missing:
        restore(package,manifest)
    transport = check(package,manifest,include_restored=True)
    protocol = read_json(package/"ADAPTIVE_PROTOCOL.json")
    scientific = read_json(package/"evidence/SCIENTIFIC_FREEZE.json")
    if scientific["study_id"] != protocol["study_id"]:
        raise ValueError("Scientific freeze study identity mismatch")
    for name,expected in {**scientific["component_freezes"],**scientific["reviews"]}.items():
        verify_hash(safe_path(package,name),expected)
    sources = {}
    specifications = [
        ("evidence/ADAPTIVE_FREEZE.json",ADAPTIVE_CHECKPOINT,ADAPTIVE_CONFIRMATION),
        ("evidence/THRESHOLD_FREEZE.json",THRESHOLD_CHECKPOINT,THRESHOLD_CONFIRMATION),
    ]
    components = []
    for frozen_name,checkpoint_name,confirmation_name in specifications:
        frozen = read_json(package/frozen_name)
        checkpoint = read_json(package/checkpoint_name)
        confirmation = read_json(package/confirmation_name)
        verify_hash(package/checkpoint_name,frozen["checkpoint_sha256"])
        verify_hash(package/checkpoint_name,confirmation["checkpoint_sha256"])
        verify_hash(package/frozen_name,confirmation["freeze_sha256"])
        consistent(checkpoint["source_identity"],frozen["source_identity"],"checkpoint source identity")
        consistent(confirmation["source_identity"],frozen["source_identity"],"confirmation source identity")
        for artifact in (frozen,checkpoint,confirmation):
            if artifact["study_id"] != protocol["study_id"]:
                raise ValueError("Component study identity mismatch")
        if not confirmation["confirmation_opened"]:
            raise ValueError("Selected artifact is not a completed confirmation")
        sources.update(verify_sources(package,frozen["source_identity"]))
        components.append((frozen,checkpoint,confirmation))
    for registry,frozen_name in (("confirmation_registry","ADAPTIVE_FREEZE.json"),
                                 ("threshold_confirmation_registry","THRESHOLD_FREEZE.json")):
        marker = read_json(package/"evidence"/registry/f"{protocol['study_id']}.json")
        if marker["study_id"] != protocol["study_id"]:
            raise ValueError("Confirmation registry study identity mismatch")
        verify_hash(package/"evidence"/frozen_name,marker["freeze_sha256"])

    adaptive_freeze,adaptive_model,adaptive = components[0]
    verify_hash(package/"evidence/development_20261029_v2/development.json",adaptive_freeze["development_sha256"])
    consistent(adaptive_model["physical_training"]["final"],adaptive_freeze["physical_parameters"],"physical model")
    consistent(adaptive_model["meta_training"]["final"],adaptive_freeze["shape_parameters"],"shape model")
    consistent(adaptive["physical"]["final_parameters"],adaptive_freeze["physical_parameters"],"confirmed physical model")
    for binding in list(adaptive_model["training_data"].values())+list(adaptive["data"].values()):
        verify_binding(binding)
    for stage in ("initial","final"):
        parameters = adaptive["physical"][f"{stage}_parameters"]
        rows = adaptive["data"]["physical"]["contexts"]
        losses = [float(outcome_law(row["distance"],parameters[0]+row["drift_offset"],
                       parameters[1],parameters[2],row["horizon"],derivatives=0).probability
                       @ np.asarray(row["costs"])) for row in rows]
        consistent(float(np.mean(losses)),adaptive["physical"][f"{stage}_expected_loss"],"physical expected loss")
    physical = protocol["gradient_and_meta_study"]["physical_parameters"]
    outer_contexts = adaptive["data"]["outer"]["contexts"]
    exact = adaptive["meta"]["exact_expected"]
    consistent(_saved_outer_loss(exact["final_weight"],outer_contexts,physical),exact["objective"],"exact-baseline saved outer loss")
    for arm in ("biased_sg","meta_sg"):
        tree = adaptive["meta"][arm]
        leaves = tree["leaf_records"]
        if len(leaves) != tree["leaves"] or len({tuple(row["outcome_path"]) for row in leaves}) != len(leaves):
            raise ValueError("Missing or duplicate retained meta trajectory")
        consistent(sum(row["probability"] for row in leaves),1.0,"meta trajectory mass")
        consistent(sum(row["probability"]*row["outer_expected_loss"] for row in leaves),tree["objective"],"meta expected hard loss")
        for leaf in leaves:
            consistent(_saved_outer_loss(leaf["weight"],outer_contexts,physical),
                       leaf["outer_expected_loss"],"saved meta leaf outer loss")

    threshold_freeze,threshold_model,threshold = components[1]
    consistent(threshold_freeze["configuration"],protocol["threshold_study"],"threshold registration")
    raw_folder = package/Path(THRESHOLD_CONFIRMATION).parent
    for name,digest in threshold["raw_evidence_sha256"].items():
        verify_hash(safe_path(raw_folder,name),digest)
    with gzip.open(raw_folder/"rollouts.jsonl.gz","rt",encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    statistics = verify_raw_records(records,protocol["threshold_study"])
    consistent(statistics,threshold["statistics"],"recomputed raw statistics")
    for fit in threshold_model["fits"]:
        rows = [row for row in records if row["fit_seed"] == fit["fit_seed"]]
        contexts = [ThresholdContext(**row["context"]) for row in rows]
        ordinary = ordinary_thresholds(fit["ordinary"],contexts,protocol["threshold_study"]["threshold_bounds"])
        for row,prediction in zip(rows,ordinary):
            consistent(float(prediction),row["arms"]["ordinary_context_threshold"]["threshold"],"frozen ordinary inference")
            consistent(fit["fixed"]["threshold"],row["arms"]["fixed_threshold"]["threshold"],"frozen fixed threshold")
        for arm in protocol["threshold_study"]["arms"]:
            values = renewal_value([row["arms"][arm]["threshold"] for row in rows],contexts)
            consistent(values.tolist(),[row["arms"][arm]["analytic_value"] for row in rows],"saved-action analytic values")
    for receipt in threshold["seed_receipts"]:
        verify_binding(receipt["confirmation_data"])
        actual = [row["context"] for row in records if row["fit_seed"] == receipt["fit_seed"]]
        consistent(actual,receipt["confirmation_data"]["contexts"],"raw context binding")
    planner_count = 0
    with gzip.open(raw_folder/"planner_searches.jsonl.gz","rt",encoding="utf-8") as handle:
        for line in handle:
            planner = json.loads(line)
            if planner_count >= len(records):
                raise ValueError("Additional planner search in raw evidence")
            row = records[planner_count]
            if (planner["fit_seed"],planner["context_index"]) != (row["fit_seed"],row["context_index"]):
                raise ValueError("Planner and rollout context identities differ")
            search = planner["search"]
            candidates = list(zip(search["grid_thresholds"],search["grid_values"]))
            candidates += [(item["threshold"],item["value"]) for item in search["local_searches"]]
            selected = max(candidates+[(0.,0.)],key=lambda pair:pair[1])
            consistent(selected[0],row["arms"]["value_threshold"]["threshold"],"selected planner threshold")
            consistent(selected[1],planner["analytic_value"],"selected planner search value")
            consistent(planner["analytic_value"],row["arms"]["value_threshold"]["analytic_value"],"reported planner value")
            planner_count += 1
    if planner_count != len(records):
        raise ValueError("Missing raw planner searches")

    native = {name:_native_archive(package/"evidence"/name,"MANIFEST.json")
              for name in ("native_v1","native_v2","native_v3")}
    credit_folder = package/"evidence/credit_execution_20261029_v1"
    native["credit_execution_20261029_v1"] = _native_archive(credit_folder,"ARCHIVE_MANIFEST.json")
    credit_freeze = read_json(credit_folder/"SOURCE_FREEZE.json")
    sources.update(verify_sources(package,credit_freeze["source_identity"]))
    verify_hash(credit_folder/"SOURCE_FREEZE.json",read_json(credit_folder/"ARCHIVE_MANIFEST.json")["source_freeze_sha256"])
    # No source modification is tolerated during this verification either.
    for path,digest in sources.items():
        verify_hash(Path(path),digest)
    return {"schema":"hepta.first-passage.adaptive.evidence-verification.v1","status":"verified",
            "study_id":protocol["study_id"],"transport":transport,"frozen_source_files_verified":len(sources),
            "threshold_contexts":len(records),"planner_searches":planner_count,
            "primary_gate":statistics["primary_gate"],"cross_stratum_gate":statistics["cross_stratum_gate"],
            "native_raw_archives":native,"confirmation_reopened":False,"models_retrained":False,
            "gate_policy":"Any scientific outcome is accepted when source, raw evidence and recomputed results agree."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root",default=str(PACKAGE))
    parser.add_argument("--restore",action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.package_root,restore_missing=args.restore),indent=2,sort_keys=True))


if __name__ == "__main__":
    main()
