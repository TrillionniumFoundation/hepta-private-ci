"""Apply frozen solver outputs with the strict native FP64 checkpoint compiler."""
import copy
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import time
import run_experiment as study

ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument("--source",type=Path,default=ROOT/"attempt002")
parser.add_argument("--output",type=Path,default=ROOT/"attempt003")
args=parser.parse_args()
SOURCE=args.source
OUT=args.output
OUT.mkdir(exist_ok=False)
started=time.perf_counter()
report=json.loads((SOURCE/"results.json").read_text())
original=study.tensor(report["original"])
checkpoint=json.loads((SOURCE/"checkpoint.before.json").read_text())
before=(SOURCE/"checkpoint.before.json").read_bytes()
before_sha=hashlib.sha256(before).hexdigest()
receiver=study.tensor(checkpoint["theta_B"])
receiver_b=study.optimal_boundary(receiver)
baseline_y,_=study.starts(report["validation_initials"],original)
baseline=[study.features(y,receiver,receiver_b) for y in baseline_y]
changed_count=0
replayed_panels=0
exact_budget_checks=0
compiler_seconds=0.0
for label,group in report["anchor_sets"].items():
    folder=OUT/label
    folder.mkdir()
    for name in ("linear_problem.json","native_problem.txt"):
        shutil.copyfile(SOURCE/label/name,folder/name)
    old_anchor_y,_=study.starts(group["anchors"],original)
    old_anchor_features=[study.features(y,receiver,receiver_b)[0] for y in old_anchor_y]
    for arm,record in group["arms"].items():
        delta=record["delta"][:]
        if arm=="READOUT_NATIVE_BOUNDED_LS":
            delta[1:]=record["solver"]["native"]["delta"]
        clipped=[min(.1,max(-.1,v)) for v in delta]
        payload="HEPTA_QVI_COMPILE_V1 4\n"+" ".join(map(repr,[.1,*report["original"],*clipped]))+"\n"
        begin=time.perf_counter()
        compiled=study.native(payload)
        elapsed=time.perf_counter()-begin
        compiler_seconds+=elapsed
        chosen=study.tensor(compiled["parameters"])
        changed=chosen.tolist()!=record["chosen"]
        for parent,child,upper in zip(report["original"],compiled["parameters"],compiled["exact_delta_outward_upper"]):
            exact=abs(Fraction.from_float(child)-Fraction.from_float(parent))
            assert exact<=Fraction.from_float(.1)
            assert exact<=Fraction.from_float(upper)
            exact_budget_checks+=1
        candidate=copy.deepcopy(checkpoint)
        candidate["theta_A"][-1]=float(chosen[0])
        candidate["receiver_offset"]=float(chosen[1])
        candidate["projection"]=chosen[2:].tolist()
        path=folder/(arm+".candidate.json")
        study.write_json(path,candidate)
        recovered=json.loads(path.read_text())
        assert recovered==candidate
        recovered["theta_A"][-1]=checkpoint["theta_A"][-1]
        recovered["receiver_offset"]=checkpoint["receiver_offset"]
        recovered["projection"]=checkpoint["projection"]
        assert recovered==checkpoint
        record["serialization_compile"]={"raw_planned_delta":delta,"box_clipped_delta":clipped,
            "compiler":compiled,"compiler_seconds":elapsed,"numeric_candidate_changed":changed,
            "all_actual_fp64_deltas_within_original_box":True,
            "forward_validation":"reexecuted" if changed else "reused_identical_candidate_source_receipt",
            "source_receipt_sha256":hashlib.sha256((SOURCE/label/(arm+".receipt.json")).read_bytes()).hexdigest()}
        if changed:
            changed_count+=1
            begin=time.perf_counter()
            anchor_y,b=study.starts(group["anchors"],chosen)
            fit=[study.features(y,receiver,receiver_b)[0] for y in anchor_y]
            held_y,_=study.starts(report["validation_initials"],chosen)
            held=[study.features(y,receiver,receiver_b) for y in held_y]
            changes=[float((new[0]-old[0]).abs().max()) for new,old in zip(held,baseline)]
            record.update(chosen=chosen.tolist(),delta=(chosen-original).tolist(),boundary=float(b),
                boundary_error=abs(float(b)-report["target_boundary"]),
                fit_receiver_start_max=float((anchor_y-old_anchor_y).abs().max()),
                fit_49_max=max(float((new-old).abs().max()) for new,old in zip(fit,old_anchor_features)),
                held_49_max=max(changes),held_49_rms=float(study.np.sqrt(study.np.mean(study.np.square(changes)))),
                retention_midpoint_max=max(changes[:257]),extrapolation_midpoint_max=max(changes[257:]),
                held_receiver_start=held_y.tolist(),held_terminal_phase=[v[1] for v in held],
                held_49_max_by_initial=changes,fit_receiver_start=anchor_y.tolist(),
                serialization_forward_seconds=time.perf_counter()-begin)
            replayed_panels+=len(group["anchors"])+len(report["validation_initials"])
        record["budget_pass"]=True
        record["fit_pass"]=record["boundary_error"]<=1e-7 and record["fit_49_max"]<=1e-7
        record["full_validation_pass"]=record["fit_pass"] and record["held_49_max"]<=1e-7
        allowed=arm!="READOUT_NATIVE_BOUNDED_LS" or record["solver"]["native"]["status"]=="FitFeasibleNeedsFullValidation"
        staged=bool(record["fit_pass"] and allowed and arm!="KEEP")
        live=folder/(arm+".live.json")
        live.write_bytes(before)
        if staged:
            live.write_bytes(path.read_bytes())
            assert json.loads(live.read_text())==candidate
            if not record["full_validation_pass"]:
                live.write_bytes(before)
        after=hashlib.sha256(live.read_bytes()).hexdigest()
        if not (record["full_validation_pass"] and staged):
            assert after==before_sha
        record["transaction"]={"staged":staged,"committed":bool(record["full_validation_pass"] and staged),
            "rolled_back":bool(staged and not record["full_validation_pass"]),"no_edit_rejected":bool(not staged),
            "before_sha256":before_sha,"after_sha256":after,
            "candidate_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
        study.write_json(folder/(arm+".receipt.json"),record)
    print(json.dumps({"anchors":label,"corrected_native_delta":group["arms"]["READOUT_NATIVE_BOUNDED_LS"]["delta"]}),flush=True)
report["serialization_replay"]={"source_result_sha256":hashlib.sha256((SOURCE/"results.json").read_bytes()).hexdigest(),
    "correction_spec_sha256":hashlib.sha256((ROOT/"serialization_correction.json").read_bytes()).hexdigest(),
    "optimizer_calls":0,"changed_candidates":changed_count,"reexecuted_forward_panels":replayed_panels,
    "unchanged_candidate_receipts_reused":30-changed_count,"exact_rational_parameter_checks":exact_budget_checks,
    "compiler_total_seconds":compiler_seconds,"wall_seconds":time.perf_counter()-started,
    "original_solver_timings_are_from_attempt002":True}
shutil.copyfile(SOURCE/"checkpoint.before.json",OUT/"checkpoint.before.json")
shutil.copyfile(SOURCE/"protocol.json",OUT/"protocol.json")
study.write_json(OUT/"results.json",report)
print(json.dumps(report["serialization_replay"],indent=2))
