"""Isolated post-result precision proposal and fixed-reference verification.

The 14 frozen source files, original weights, original numerical comparisons,
and primary utility evidence remain unchanged. Production execution requires
publication of this source, its design, development proof and independent review.
"""

from datetime import datetime, timezone
from pathlib import Path
import argparse
import copy
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import time
import traceback
import types

import numpy as np
import torch

from .evaluate import evaluate, load_policy, validate_selection
from .models import RRPolicy
from .numerical_control import (BoundaryProbe, EVENT_TIME_TOLERANCE, compact_path,
                                compare_event_logs, evaluate_pair, weights_digest)
from .operators import frozen_control_boundary, numerical_control_boundary
from .prepare_data import load_data, sha
from .run_evaluation import DATASETS, validated_selection
from .train import atomic_json, check_disk, memory_snapshot


ROOT = Path(__file__).resolve().parent
SEEDS = (101,211,307,401,503)
REPLAYS = (0,1,2,3)
CANDIDATE = "rr_full_scalar_fp64_post_result"
PUBLICATION_FILES = ("precision_repair.py", "precision_repair_design.json",
    "precision_repair_development.json", "precision_audit/independent_repair_review.json")


def promoted_control_boundary(drift, cost, sigma=.4, discount=.4, refractory=.1):
    """Floating Tensor contract; device/broadcast/autograd preserved by casts.

    CPU float32/float64, mixed dtypes and zero-dimensional broadcasting are
    validated. This proposal does not qualify integer inputs or a CUDA runtime.
    """
    if not all(isinstance(value, torch.Tensor) and value.is_floating_point()
               for value in (drift, cost)):
        raise TypeError("Precision proposal requires floating Tensor drift and cost")
    result_dtype = torch.result_type(drift, cost)
    return frozen_control_boundary(drift.double(), cost.double(), sigma,
                                    discount, refractory).to(dtype=result_dtype)


def isolated_controls():
    original = RRPolicy.controls
    environment = dict(original.__globals__)
    environment["frozen_control_boundary"] = promoted_control_boundary
    result = types.FunctionType(original.__code__, environment, original.__name__,
                                original.__defaults__, original.__closure__)
    result.__kwdefaults__ = copy.copy(original.__kwdefaults__)
    changed = [name for name in environment
               if environment[name] is not original.__globals__[name]]
    if changed != ["frozen_control_boundary"] or result.__code__ is not original.__code__:
        raise AssertionError("More than the scalar precision function was changed")
    return result


class PrecisionRRPolicy(RRPolicy):
    controls = isolated_controls()


def promoted_policy(model):
    if type(model) is not RRPolicy or model.variant != "rr_full":
        raise TypeError("Only the frozen rr_full policy is eligible")
    before = weights_digest(model)
    candidate = copy.deepcopy(model)
    candidate.__class__ = PrecisionRRPolicy
    candidate.boundary_method = "closed_form"
    if weights_digest(candidate) != before:
        raise AssertionError("Precision wrapper changed a weight or buffer")
    return candidate.eval()


def design_identity():
    path = ROOT/"precision_repair_design.json"
    design = json.loads(path.read_text())
    expected = {"candidate": CANDIDATE, "source_sha256": sha(__file__),
        "training_seeds": list(SEEDS), "datasets": list(DATASETS),
        "latent_replays": list(REPLAYS), "event_time_tolerance": EVENT_TIME_TOLERANCE,
        "original_matrix_status_sha256": sha(ROOT/"results/numerical_matrix_status.json"),
        "original_matrix_report_sha256": sha(ROOT/"results/numerical_matrix_report.json"),
        "operator_diagnostic_sha256": sha(ROOT/"results/numerical_roundoff_operator_diagnostic.json"),
        "required_publication_files": list(PUBLICATION_FILES), "new_training_performed": False,
        "original_results_replaced": False, "production_cpu_affinity": [2]}
    if any(design.get(key) != value for key,value in expected.items()):
        raise ValueError("Precision proposal differs from its reviewable design")
    freeze = json.loads((ROOT/"pre_data_freeze.json").read_text())
    if any(sha(ROOT/name) != value for name,value in freeze["source_sha256"].items()):
        raise ValueError("An original frozen source changed")
    return design, sha(path)


def validate_publication(path):
    design, design_hash = design_identity()
    receipt = json.loads(Path(path).read_text())
    if (receipt.get("remote_bytes_verified") is not True or not receipt.get("repository")
            or not re.fullmatch(r"[0-9a-f]{40}", receipt.get("commit_sha", ""))):
        raise ValueError("A root-verified immutable repair publication is required")
    recorded = datetime.fromisoformat(receipt["recorded_at_utc"].replace("Z", "+00:00"))
    if recorded.tzinfo is None:
        raise ValueError("Publication timestamp must include its time zone")
    for name in PUBLICATION_FILES:
        content = (ROOT/name).read_bytes()
        entry = receipt.get("files", {}).get(name, {})
        blob = hashlib.sha1(f"blob {len(content)}\0".encode()+content).hexdigest()
        if (entry.get("sha256") != hashlib.sha256(content).hexdigest()
                or entry.get("git_blob_sha") != blob or not entry.get("repository_path")):
            raise ValueError("Published repair artifact bytes do not match: "+name)
    development = json.loads((ROOT/"precision_repair_development.json").read_text())
    review = json.loads((ROOT/"precision_audit/independent_repair_review.json").read_text())
    if (development.get("all_passed") is not True
            or development.get("source_sha256") != sha(__file__)
            or development.get("design_sha256") != design_hash
            or review.get("status") != "approved_for_isolated_repair_replay"
            or review.get("remaining_blockers") != []
            or review.get("source_sha256") != sha(__file__)
            or review.get("design_sha256") != design_hash
            or review.get("development_sha256") != sha(ROOT/"precision_repair_development.json")):
        raise ValueError("Development or independent repair review is not approved for these bytes")
    return {"candidate": CANDIDATE, "source_sha256": sha(__file__),
        "design_sha256": design_hash, "development_sha256": sha(ROOT/"precision_repair_development.json"),
        "review_sha256": sha(ROOT/"precision_audit/independent_repair_review.json"),
        "publication_receipt_sha256": sha(path), "publication": receipt,
        "remote_verification_scope": "Root verified immutable remote bytes. This local runner checks SHA256 and Git blob SHA1 against that receipt; it does not perform a network verification."}


def validate_development():
    from .models import make_policy
    from .prepare_data import make_arrays, paired_scenarios
    from .task import Scenario
    _, design_hash = design_identity()
    destination = ROOT/"precision_repair_development.json"
    if destination.exists():
        raise FileExistsError("Development proof is write-once")
    check_disk()
    torch.set_num_threads(1)
    fixtures = []
    configurations = ((torch.float32,torch.float32,False,False),
        (torch.float64,torch.float64,False,False),
        (torch.float32,torch.float64,False,False),
        (torch.float64,torch.float32,True,False),
        (torch.float32,torch.float64,False,True),
        (torch.float32,torch.float32,True,True))
    for adtype,cdtype,ascalar,cscalar in configurations:
        a = torch.tensor(.3 if ascalar else [[-.8],[.0],[.8]],dtype=adtype,requires_grad=True)
        c = torch.tensor(.5 if cscalar else [[.2,.4,.7,.98]],dtype=cdtype,requires_grad=True)
        original = frozen_control_boundary(a,c)
        proposal = promoted_control_boundary(a,c)
        reference = numerical_control_boundary(a.double(),c.double()).to(torch.result_type(a,c))
        gp = torch.autograd.grad(proposal.sum(), (a,c), retain_graph=True)
        gr = torch.autograd.grad(reference.sum(), (a,c))
        if proposal.shape != original.shape or proposal.dtype != original.dtype or proposal.device != original.device:
            raise AssertionError("Precision proposal changed output shape/dtype/device")
        value_error = float((proposal.double()-reference.double()).abs().max())
        gradient_errors = [float((x.double()-y.double()).abs().max()) for x,y in zip(gp,gr)]
        limits = [2e-6 if dtype == torch.float32 else 2e-10 for dtype in (adtype,cdtype)]
        if value_error > (2e-6 if proposal.dtype == torch.float32 else 2e-11):
            raise AssertionError("Precision proposal failed its independent root value fixture")
        if any(error>limit for error,limit in zip(gradient_errors,limits)):
            raise AssertionError("Precision proposal failed independent implicit derivatives")
        fixtures.append({"drift_dtype":str(adtype),"cost_dtype":str(cdtype),
            "drift_scalar":ascalar,"cost_scalar":cscalar,"output_shape":list(proposal.shape),
            "output_dtype":str(proposal.dtype),"maximum_value_error":value_error,
            "maximum_gradient_errors":gradient_errors,
            "value_bitwise_equal":torch.equal(proposal,reference),
            "gradient_bitwise_equal":[torch.equal(x,y) for x,y in zip(gp,gr)]})
    for a,c in ((torch.tensor(1),torch.tensor(2.)), (torch.tensor(1.),2.)):
        try:
            promoted_control_boundary(a,c)
        except TypeError:
            pass
        else:
            raise AssertionError("Unsupported non-floating-Tensor input was silently admitted")
    torch.manual_seed(901990)
    original = make_policy("rr_full")
    candidate = promoted_policy(original)
    scenes = [Scenario((1.2,.8,.4,.2),(1.,1.,3.,3.),3,2,1),
              Scenario((.3,1.3,.6,1.1),(.75,1.25,2.75,3.25),4,1,1,
                       shock_time=1.25,refill_time=2.75)]
    arrays = make_arrays(scenes)
    batch = evaluate_pair(candidate,scenes,oracle_values=arrays["oracle_utility"],episode_metadata=None,
        dataset="development",training_seed=0,latent_replay=0,latent_seed=901991,query_seed_base=901100)
    paired,metadata = paired_scenarios(901992,groups=1)
    arrays = make_arrays(paired)
    strict = evaluate_pair(candidate,paired,oracle_values=arrays["oracle_utility"],episode_metadata=metadata,
        dataset="paired",training_seed=0,latent_replay=1,latent_seed=901993,query_seed_base=901300)
    for result in (batch,strict):
        for field in ("rows_with_any_action_divergence","rows_with_event_divergence_beyond_tolerance",
                      "rows_with_different_event_counts","rows_with_different_delivered_pulses",
                      "maximum_absolute_expected_utility_difference","observation_calls_with_different_rng_states"):
            if result["summary"][field] != 0:
                raise AssertionError("Development dual-path control differs: "+field)
        if any(not step[flag] for step in result["step_comparisons"] for flag in
               ("same_indices_after_observation","same_count_matrix","same_rng_after_observation")):
            raise AssertionError("Development full step witnesses differ")
    if len({row["initial_state_sha256"] for row in strict["rows"]}) != 1:
        raise AssertionError("Strict paired pre-cue state matching failed")
    if weights_digest(original) != weights_digest(candidate):
        raise AssertionError("Development weights or buffers changed")
    report = {"schema":"rrsnn-v4-isolated-precision-development-1","all_passed":True,
        "created_at_utc":datetime.now(timezone.utc).isoformat(),"source_sha256":sha(__file__),
        "design_sha256":design_hash,"controls_code_object_identical":PrecisionRRPolicy.controls.__code__ is RRPolicy.controls.__code__,
        "changed_controls_global_bindings":["frozen_control_boundary"],"broadcast_dtype_fixtures":fixtures,
        "unsupported_input_rejections_checked":True,"production_checkpoint_loaded":False,
        "heldout_scenarios_loaded":False,"original_sources_unchanged":True,
        "same_weight_state_sha256":weights_digest(candidate),"normal_batch":batch,"strict_paired":strict,
        "scope":"Development only: fresh untrained seed901990, two declared scenarios and one four-condition group. Fresh Brent is executed here, permitting full per-step controls/index/RNG comparisons. These do not establish full-state equivalence for the later 60 fixed-reference replays."}
    design_identity()
    atomic_json(destination,report)
    check_disk()
    print(json.dumps({"development":str(destination),"sha256":sha(destination),
        "normal_batch":batch["summary"],"strict_paired":strict["summary"]}),flush=True)


def array_digest(value):
    value = np.asarray(value)
    return hashlib.sha256(str(value.dtype).encode()+str(value.shape).encode()+value.tobytes()).hexdigest()


def compare_with_fixed_brent(result, original):
    if result["latent_seed"] != original["latent_seed"] or len(result["rows"]) != len(original["rows"]):
        raise AssertionError("Repair changed actor seed or scenario coverage")
    rows = []
    identity_keys = ("scenario_index","scenario_digest","group","condition","initial_state_sha256",
                     "query_seeds","query_bits","oracle_expected_utility")
    for actual, reference in zip(result["rows"],original["rows"]):
        if any(actual[key] != reference[key] for key in identity_keys):
            raise AssertionError("Repair and fixed Brent do not share scenario, initial state, and queries")
        repaired,brent = compact_path(actual),reference["brent"]
        if [row["time"] for row in repaired["actions"]] != [row["time"] for row in brent["actions"]]:
            raise AssertionError("Repair changed task observation scheduling")
        events = compare_event_logs(brent["actual_internal_events"],repaired["actual_internal_events"])
        events["count_repair_minus_fixed_brent"] = events.pop("count_root_minus_lambert")
        rows.append({**{key:actual[key] for key in identity_keys},**events,
            "actions_equal":repaired["actions"]==brent["actions"],
            "delivered_pulses_equal":repaired["delivered"]==brent["delivered"],
            "per_neuron_counts_equal":repaired["internal_spikes_per_neuron"]==brent["internal_spikes_per_neuron"],
            "budget_and_renewals_equal":all(repaired[name]==brent[name] for name in ("budget_final","budget_spent","renewals")),
            "expected_utility_repair_minus_brent":repaired["expected_utility"]-brent["expected_utility"],
            "realized_utility_repair_minus_brent":(np.asarray(repaired["realized_query_utility"])-np.asarray(brent["realized_query_utility"])).tolist(),
            "repair":repaired})
    summary = {"episodes":len(rows),"all_resource_invariants_passed":result["all_resource_invariants_passed"],
        "same_initial_actor_seed_and_state_digests":True,
        "action_disagreement_rows":sum(not row["actions_equal"] for row in rows),
        "count_disagreement_rows":sum(not row["counts_equal"] for row in rows),
        "per_neuron_count_disagreement_rows":sum(not row["per_neuron_counts_equal"] for row in rows),
        "event_type_disagreement_rows":sum(not row["event_type_sequence_equal"] for row in rows),
        "event_time_tolerance_failure_rows":sum(not row["event_log_equal_with_time_tolerance"] for row in rows),
        "exact_event_log_disagreement_rows":sum(not row["exact_event_log_equal"] for row in rows),
        "delivered_pulse_disagreement_rows":sum(not row["delivered_pulses_equal"] for row in rows),
        "budget_disagreement_rows":sum(not row["budget_and_renewals_equal"] for row in rows),
        "maximum_expected_utility_difference":max(abs(row["expected_utility_repair_minus_brent"]) for row in rows),
        "maximum_realized_utility_difference":max(abs(value) for row in rows for value in row["realized_utility_repair_minus_brent"]),
        "maximum_type_aligned_event_time_difference":max((row["maximum_time_difference_if_type_aligned"]
            for row in rows if row["event_type_sequence_equal"]),default=None)}
    return {"summary":summary,"rows":rows}


def run_matrix(publication_path):
    if sorted(os.sched_getaffinity(0)) != [2]:
        raise ValueError("Precision repair is allocated CPU2 only")
    torch.set_num_threads(1)
    publication = validate_publication(publication_path)
    freeze,selection,selection_receipt = ROOT/"pre_data_freeze.json",ROOT/"selection.json",ROOT/"selection_publication.json"
    _,checkpoints,manifest,original_identity = validated_selection(freeze,selection,selection_receipt)
    old = json.loads((ROOT/"results/numerical_matrix_status.json").read_text())
    references = {item["path"]:item["sha256"] for run in old["completed"] for item in run["outputs"]}
    if old.get("all_completed") is not True or len(references) != 60:
        raise ValueError("Original numerical matrix must be complete and retained")
    identity = {**publication,"original_matrix_status_sha256":sha(ROOT/"results/numerical_matrix_status.json"),
                "original_selection_identity":original_identity,"cpu_affinity":[2]}
    status_path = ROOT/"results/precision_repair_matrix_status.json"
    lock = status_path.with_suffix(".lock").open("a")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    previous_attempts = []
    if status_path.exists():
        previous = json.loads(status_path.read_text())
        if previous["identity"] != identity:
            raise ValueError("Existing repair run has a different identity")
        archived = status_path.with_name(f"precision_repair_attempt_{time.time_ns()}.json")
        shutil.copy2(status_path,archived)
        previous_attempts = previous.get("preserved_prior_attempts",[])+[{"path":str(archived.relative_to(ROOT)),"sha256":sha(archived)}]
    begin = time.perf_counter()
    status = {"schema":"rrsnn-v4-isolated-precision-matrix-1","identity":identity,
        "started_at_utc":datetime.now(timezone.utc).isoformat(),"expected_comparison_files":60,
        "before_resources":memory_snapshot(),"preserved_prior_attempts":previous_attempts,
        "outputs":[],"errors":[],"all_completed":False,
        "scope":"Post-result engineering verification only. Original numerical failures, primary utility table, candidate conclusions and all frozen files remain unchanged."}
    atomic_json(status_path,status)
    try:
        for seed in SEEDS:
            check_disk()
            checkpoint = checkpoints["rr_full"][seed]
            selected = validate_selection(checkpoint,selection,freeze)
            base,blob = load_policy(checkpoint,selected["training_protocol_sha256"])
            candidate = promoted_policy(base)
            weight_hash = weights_digest(base)
            destination = checkpoint.parent/"precision_repair"
            destination.mkdir(exist_ok=True)
            for dataset in DATASETS:
                scenarios,arrays,metadata,_ = load_data(dataset,freeze)
                for replay in REPLAYS:
                    check_disk()
                    source = checkpoint.parent/"numerical_control"/f"evaluation_{dataset}_rep{replay}.json.gz"
                    source_name = str(source.relative_to(ROOT))
                    if references.get(source_name) != sha(source):
                        raise ValueError("Original fixed Brent reference changed")
                    with gzip.open(source,"rt",encoding="utf-8") as handle:
                        fixed = json.load(handle)
                    expected = {**original_identity,"controller_sha256":sha(ROOT/"numerical_control.py"),
                        "checkpoint_sha256":sha(checkpoint),"same_weight_state_sha256":weight_hash,
                        "variant":"rr_full","training_seed":seed,"dataset":dataset,"latent_replay":replay,
                        "source_files":next(item["files"] for item in manifest["splits"] if item["name"]==dataset),
                        "event_time_tolerance":EVENT_TIME_TOLERANCE,"new_training_performed":False}
                    if fixed["identity"] != expected:
                        raise ValueError("Fixed Brent reference differs from the full original identity")
                    local_identity = {**identity,"fixed_reference_path":source_name,"fixed_reference_sha256":sha(source),
                                      "original_reference_identity":expected,"same_weight_state_sha256":weight_hash}
                    path = destination/f"evaluation_{dataset}_rep{replay}.json.gz"
                    if path.exists():
                        with gzip.open(path,"rt",encoding="utf-8") as handle:
                            payload = json.load(handle)
                        if payload["identity"] != local_identity or len(payload["comparison"]["rows"]) != len(scenarios):
                            raise ValueError("Existing repair output identity or coverage differs")
                    else:
                        probe = BoundaryProbe(candidate).eval()
                        result = evaluate(probe,scenarios,oracle_values=arrays["oracle_utility"],episode_metadata=metadata,
                            dataset=dataset,training_seed=seed,latent_replay=replay,keep_trace=True)
                        comparison = compare_with_fixed_brent(result,fixed["comparison"])
                        if weights_digest(candidate) != weight_hash or weights_digest(base) != weight_hash:
                            raise AssertionError("Repair evaluation changed a parameter or buffer")
                        witnesses = [{"batch_serial":row["batch_serial"],"step":row["step"],
                            "rng_sha256":row["rng_sha256"],
                            **{field+"_sha256":array_digest(row[field]) for field in
                               ("time","observation","dt","mask","indices","trace","boundary","drift","logits","actual_counts")}}
                            for row in probe.records]
                        payload = {"schema":"rrsnn-v4-isolated-precision-fixed-reference-1","identity":local_identity,
                            "comparison":comparison,"repair_step_witnesses":witnesses,
                            "initial_actor_rng_sha256":result.get("initial_rng_sha256"),
                            "paired_initial_state_receipts":result.get("paired_initial_state_receipts"),
                            "event_time_tolerance":EVENT_TIME_TOLERANCE,"new_training_performed":False,
                            "timing":{"model_step_cpu_seconds":result["model_step_cpu_seconds"],
                                      "elapsed_seconds_including_task":result["elapsed_seconds_including_task"]},
                            "reference_scope":"Compare actual stored Brent spike types/times/counts, task actions/deliveries/budgets and utilities. The old reference lacks per-step full state and RNG digests; no 60-replay full-state/RNG equality is claimed. Complete two-path probes exist only in the separate development proof.",
                            "timing_scope":"Instrumented repair replay only; the old Brent timing is not rerun or compared as contemporaneous throughput."}
                        temporary = path.with_suffix(".gz.tmp")
                        with gzip.open(temporary,"wt",encoding="utf-8") as handle:
                            json.dump(payload,handle,allow_nan=False)
                        temporary.replace(path)
                    check_disk()
                    entry = {"path":str(path.relative_to(ROOT)),"sha256":sha(path),"training_seed":seed,
                             "dataset":dataset,"latent_replay":replay,"summary":payload["comparison"]["summary"]}
                    status["outputs"].append(entry)
                    atomic_json(status_path,status)
                    print(json.dumps({"repair_completed":len(status["outputs"]),**entry}),flush=True)
        if validate_publication(publication_path) != publication:
            raise AssertionError("Published repair identity changed during execution")
        validated_selection(freeze,selection,selection_receipt)
        status["all_completed"] = len(status["outputs"]) == 60
    except BaseException as error:
        status["errors"].append({"error":repr(error),"traceback":traceback.format_exc()})
        raise
    finally:
        status.update(completed_at_utc=datetime.now(timezone.utc).isoformat(),
                      elapsed_seconds=time.perf_counter()-begin,after_resources=memory_snapshot())
        atomic_json(status_path,status)
        lock.close()
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-development",action="store_true")
    parser.add_argument("--publication-receipt",type=Path)
    args = parser.parse_args()
    if args.validate_development:
        validate_development()
    elif args.publication_receipt:
        completed = run_matrix(args.publication_receipt)
        print(json.dumps({"all_completed":completed["all_completed"],"comparison_files":len(completed["outputs"])}))
    else:
        parser.error("Choose --validate-development or --publication-receipt")
