"""Bind the one approved post-hoc diagnostic after observing the failed main run."""
import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact_io import identity, read, save, sha, verify_manifest


main_protocol = read(ROOT / "PROTOCOL_FROZEN.json")
verify_manifest(ROOT, main_protocol["source_files"])
verified = read(ROOT / "independent_verification/VERIFIED.json")
scientific = read(ROOT / "execution_r1/run/RESULTS.json")
if not verified["all_checks_pass"] or scientific["weight_efficacy_qualified"]:
    raise ValueError("this diagnostic is only the approved post-hoc explanation of the verified failed trial")
if not scientific["gates"]["23"]["E"]["accepted"]:
    raise ValueError("the approved diagnostic subject is the accepted fit23 E")
source_names = ["posthoc/diagnose.py", "posthoc/freeze_diagnostic.py", "artifact_io.py", "vendor/planning.py"]
input_names = ["PROTOCOL_FROZEN.json", "INPUT_MANIFEST.json", "independent_verification/VERIFIED.json",
    "execution_r1/PROCESS_RECEIPT.json", "execution_r1/run/RESULTS.json",
    "execution_r1/run/ALL_GATES_BEFORE_TEST.json", "execution_r1/run/fit_23_CANDIDATES.json.gz",
    "execution_r1/run/models/fit_23_C.json.gz", "execution_r1/run/models/fit_23_E.json.gz",
    "execution_r1/run/worlds/validation_23_ood.json.gz", "execution_r1/run/worlds/test_23_ood.json.gz",
    "execution_r1/run/validation_23_ood_RESULTS.json.gz", "execution_r1/run/test_23_ood_RESULTS.json.gz"]
protocol = dict(schema="hepta-value-edit-posthoc-first-divergence-and-performance-difference-v1",
    status="FROZEN_POSTHOC_BEFORE_DIAGNOSTIC_EXECUTION",
    frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    main_result_already_observed=True, confirmatory=False,
    approved_scope="One read-only diagnostic of all existing fit23 OOD16 validation and32 TEST worlds; no new seed, sample, parameter, threshold or qualification.",
    fit=23, domains=["ood"], validation_worlds=16, test_worlds=32, complete_worlds=48,
    source_files={name: identity(ROOT / name) for name in source_names},
    input_files={name: identity(ROOT / name) for name in input_names},
    source_law_binding="All main-protocol source hashes and all INPUT_MANIFEST files must remain unchanged before this run.",
    source_sha256=sha((ROOT / "posthoc/diagnose.py").read_bytes()),
    identity_tolerance=2e-13, sign_tolerance=1e-12,
    resource_caps=dict(worker_CPU_seconds=60, worker_wall_seconds=120, controller_wall_seconds=150, numeric_threads=1),
    identities=[
        "For each own/evaluator law separately: V_E(initial)-V_C(initial)=sum_s unnormalized_reach_E(s)*(Q_C(s,action_E)-V_C(s)); no training-occupancy normalization.",
        "Evaluator-law first common-prefix partition stops at the first action difference, summing reach_prefix(s)*(complete V_E(s)-complete V_C(s)).",
        "At fixed hidden representation, sum_i delta_margin_weight_i*h_i equals actual C-to-E head margin shift within declared F64 tolerance.",
        "Terminal-anchor score margin between selected E and C actions equals own one-step C advantage because the terminal decoder is protected."],
    interpretation="One-step follow-C counterfactual, complete edited-policy suffix effect, head/target mismatch and law-specific preference are separate quantities. These are fixed-world policy identities, not independent causal interventions on individual weights.",
    categories="Exclusive sum of evaluator-law performance difference: own_target_violation first; otherwise own_positive_evaluator_negative; otherwise other. Contributions use evaluator E reach. Counts are union changed-state counts across both law supports/common prefixes and are not independent samples or necessarily positive evaluator reach.",
    example_rule="Smallest-index TEST world attaining the minimum already-frozen E-minus-C expected utility among all32 existing fit23 OOD TEST worlds; all48 records remain available.",
    prohibition="No candidate edits, reseeding, sample replacement, gate changes, new confirmatory comparisons or diagnostic-result-driven retry.",
    failure="Preserve partial diagnostic outputs and complete process receipt; original failed scientific qualification remains unchanged.")
path = ROOT / "posthoc/PROTOCOL_FROZEN.json"
digest = save(path, protocol)
print(__import__("json").dumps(dict(path=str(path), sha256=digest, source_sha256=protocol["source_sha256"], complete_worlds=48), sort_keys=True))
