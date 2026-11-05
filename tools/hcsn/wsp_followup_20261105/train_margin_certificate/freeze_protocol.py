"""Freeze all sources and exact preexisting input identities without forwards."""
import argparse
import datetime
from pathlib import Path
from io_helpers import read, save, sha


parser=argparse.ArgumentParser()
for name in ("science","joint","inputs"):
    parser.add_argument("--"+name,type=Path,required=True)
args=parser.parse_args()
root=Path(__file__).parent
old=read(args.science/"PROTOCOL_FROZEN.json")
fits=[11,23,37,53,71]
files={"new":{},"science":{},"joint":{},"inputs":{}}
for path in sorted(root.glob("*.py")):
    files["new"][path.name]=sha(path.read_bytes())
for name in ("planning.py","run_experiment.py","PROTOCOL_FROZEN.json"):
    files["science"][name]=sha((args.science/name).read_bytes())
for path in sorted(args.joint.iterdir()):
    if path.suffix==".py" or path.name in ("joint_protocol.json","truth_transitions.npz","INPUT_ACQUISITION.json"):
        files["joint"][path.name]=sha(path.read_bytes())
expected={}
for fit in fits:
    candidate_name=f"execution_r1/run/fit_{fit}_CANDIDATES.json.gz"
    model_name=f"execution_r1/run/models/fit_{fit}_C.json.gz"
    for name in (candidate_name,model_name):
        files["science"][name]=sha((args.science/name).read_bytes())
    for name in (f"fit_{fit}/data/fit_{fit}_data.json",f"fit_{fit}/model_renewal/model.json"):
        files["inputs"][name]=sha((args.inputs/name).read_bytes())
    candidate=read(args.science/candidate_name)
    expected[str(fit)]={name:candidate[name] for name in ("H_sha256","Y_sha256","W_sha256","rows")}
    expected[str(fit)]["train_J_table_sha256"]=[row["own_bellman"]["table_sha256"] for row in candidate["training_worlds"]]
toy=read(root/"TOY_CHECK.json")
assert toy["passed"] and toy["certificate_source_sha256"]==files["new"]["certificate.py"]
protocol={
 "schema":"hepta.train-margin-certificate-protocol.v1",
 "status":"FROZEN_BEFORE_TRAIN_DIAGNOSTIC",
 "frozen_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "scope":"Post-scientific TRAIN representation/continuation-budget diagnostic; no new efficacy sample or candidate model",
 "fits":fits,"files":files,"expected":expected,
 "old_scientific_protocol_sha256":sha((args.science/"PROTOCOL_FROZEN.json").read_bytes()),
 "toy_check_sha256":sha((root/"TOY_CHECK.json").read_bytes()),
 "schedule_fields":["schema","deadline","initial_budget","target_tick","duration","drive","reliability","read_price","read_delay","prior_distance","latency_price","repair_price","failure_probability"],
 "reconstruction":{k:old["training"][k] for k in ("max_full_states_per_world","max_markov_states_per_world")},
 "selection":{
   "rows":"All original TRAIN full-state rows, in original world/enumeration order, including off-policy and sunk-charge aliases",
   "necessary_pairs":"Only rows with J first-max in WAIT/READ/REPAIR; compare against every other legal continuation, at most one",
   "margin":0,"no_positive_margin_search":True,
   "baseline":"exact binary64 C continuation rows, not rounded baseline forward scores",
   "radius_squared":"sum of exact rational squares of all 147 C continuation coefficients divided by 4",
   "strict_first_max_comparisons_relaxed_to_weak":True,
   "belief_and_terminal_constraints_omitted":"Necessary relaxation; infeasibility excludes fitting these J continuation choices, feasibility does not establish full argmax realization"
 },
 "exact_alias":{
   "key":"49 hidden binary64 bytes concatenated with complete six-bit legal mask, same fit",
   "test":"J first-max differs from the first row in the exact same feature/mask class",
   "retention":"All conflicting row-index pairs plus the first deterministic complete double-row witness per fit",
   "near_ties":"Exact rational J best-versus-runner-up gaps retained for both complete witness rows; no gap-based filtering",
   "qualification":"Only impossibility of simultaneously reproducing those labels by a deterministic fixed-representation four-output decoder; no utility-loss lower bound"
 },
 "feasible_precheck":{
   "construction":"Exact rational common coordinate mean of the three C continuation rows",
   "accept":"Exact sum of squared shifts <= declared true Frobenius radius squared",
   "consequence":"Weak pair system feasible for every hidden vector; skip numerical search; never claim first-max J realization; no candidate model saved"
 },
 "search":{
   "one_fixed_search_per_fit_unless_analytic_weak_feasibility_proved":True,
   "method":"L-BFGS-B over nonnegative y, numerical objective 0.5||A^T y||^2-b^T y",
   "initial_point":"all zero","per_fit_search_cpu_seconds":40,
   "options":{"maxiter":3000,"maxfun":12000,"maxls":40,"ftol":1e-15,"gtol":1e-10},
   "witness_selection":"Largest observed numerical (b^T y)/||A^T y||; zero numerical vector with positive b^T y has infinite score; first tie retained",
   "normalization":"One final binary64 division by largest component; only resulting nonnegative finite dyadics are used in the proof",
   "no_search_restarts_or_posterior_margin_changes":True,
   "failure":"Retain last best witness and all search failure/CPU records; no certificate means UNKNOWN unless analytic feasibility was proved"
 },
 "exact_certificate":{
   "formula":"y>=0, d=y^T b>0, d^2>R^2||A^T y||^2, all in Fraction; no approximate-zero dual constraints or LP-status certificates",
   "ideal_b":"-A*C with exact stored binary64 coefficients",
   "F64_relaxation_b":"-A*C-E_target-E_competitor",
   "F64_bound":"u=2^-53; gamma98=98u/(1-98u); S_j=sum_i|C_ji|+49*ceil(sqrt(R^2)); E_j=gamma98*S_j+98*2^-1074/(1-98u)",
   "guards":"Every hidden finite, |h_i|<=1, bias=1; uniform partial-sum bound <2^1000; finite stored center; positive d and strict squared separation required",
   "semantics":"Conditional on binary64 round-to-nearest, gradual underflow, separately rounded products and at most 48 additions in each 49-term dot; observed probes do not certify arbitrary hardware",
   "no_claim":"No proof about all beneficial policies, new representations, whole-network optimum, task utility, energy, production or unknown environment law"
 },
 "data_boundary":{
   "new_validation_or_test_files_accessed":False,"held_out_rows_used_or_scored":False,
   "archived_shared_fit_data_container_read_in_full":True,
   "legacy_loader_initializes_truth_law_then_discards_it":True,
   "targets":"Only original TRAIN schedules and checkpoint own-law J tables; environment truth not consulted"
 },
 "independent_verification":{
   "math":"Separately written Fraction vector accumulation, radius, roundoff and strict squared decision",
   "source":"Reexecute every saved nonzero-dual and first-alias witness state against frozen feature/own-law definitions; require byte-identical hidden and exact J table SHA",
   "scope":"Verify full producer reconstruction hashes against frozen originals; do not describe witness-only source reexecution as a second full H/Y/W regeneration"
 },
 "resources":{
   "producer":{"cpu_seconds":600,"wall_seconds":800},
   "verifier":{"cpu_seconds":290,"wall_seconds":390},
   "total_measured_pipeline_cpu_cap":900,"total_pipeline_wall_cap":1200,
   "address_space_bytes":2147483648,
   "all_fit_denominator":5,"all_partial_artifacts_retained":True,
   "encoded_blob_limit_exclusive":480000,"part_bytes":479000
 }
}
save(root/"PROTOCOL_FROZEN.json",protocol)
print(sha((root/"PROTOCOL_FROZEN.json").read_bytes()))
