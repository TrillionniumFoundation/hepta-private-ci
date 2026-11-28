"""Source-pinned semantic inventory of actual SmallHCSN checkpoint tensors.

This is a read-only structural audit. Source contracts are explicit assertions
derived from the pinned evaluator, not a claim of automatic program analysis.
No forwards, gradients, candidate choices or final test generation occur here.
"""
import hashlib
import json
from pathlib import Path
import struct

import numpy as np

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent/"runtime_trace_evidence/source_frozen"
if not SOURCE.is_dir():
    SOURCE = ROOT.parent/"runtime_source_frozen"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    raw = path.read_bytes()
    n = struct.unpack("<Q", raw[:8])[0]
    h = json.loads(raw[8:8+n])
    tensors = {}
    for name, d in h.items():
        if name == "__metadata__":
            continue
        start, end = d["data_offsets"]
        data = raw[8+n+start:8+n+end]
        dtype = "<f4" if d["dtype"] == "F32" else "<f8"
        values = np.frombuffer(data, dtype=dtype).reshape(d["shape"])
        tensors[name] = {"shape": d["shape"], "dtype": d["dtype"], "scalars": values.size,
                         "file_offset": 8+n+start, "byte_length": len(data),
                         "sha256": sha(data), "min": float(values.min()), "max": float(values.max())}
    return raw, h, tensors


def main():
    out = ROOT/"semantic_inventory"
    out.mkdir(exist_ok=False)
    source_manifest = json.loads((SOURCE/"SOURCE_MANIFEST.json").read_text())
    source_pins = []
    for item in source_manifest["files"]:
        if item["path"].endswith(("model.rs", "physics.rs", "bound_io.rs", "trace.rs")):
            assert sha((SOURCE/item["path"]).read_bytes()) == item["sha256"]
            source_pins.append(item)
    buffers = {"body.fixed_boundary", "body.reset_absolute", "body.synaptic_mask"}
    contracts = {
        "body.raw_cost": {"kind": "registered_parameter", "equation": "0.15 + 0.02*tanh(raw_cost + 0.15*drive)", "effect": "local physical QVI and reward cost at even ticks", "active_scalars_original": 8},
        "body.raw_boundary": {"kind": "registered_parameter", "effect": "inactive under fixed qvi profile; no evaluator read", "active_scalars_original": 0, "inactive_scalars_original": 8},
        "body.fixed_boundary": {"kind": "protected_buffer", "effect": "initial boundary and centering origin; not an independently learned threshold"},
        "body.reset_absolute": {"kind": "protected_buffer", "effect": "absolute reset coordinate used by QVI, initial deposit and refractory return"},
        "body.synaptic_mask": {"kind": "protected_buffer", "effect": "disables receiver-to-sender edges; only first eight columns consumed in boundary mode"},
        "body.input_drive.weight": {"kind": "registered_parameter", "effect": "raw inputs to four sender physical controls at ticks 0,2,4", "active_scalars_original": 36},
        "body.input_drive.bias": {"kind": "registered_parameter", "effect": "sender physical-control bias", "active_scalars_original": 4},
        "body.input_mark.weight": {"kind": "registered_parameter", "effect": "sender signed-mark state, with no original receiver score path", "active_scalars_original": 0, "inactive_scalars_original": 36, "bridge_effective_scalars": 36},
        "body.input_mark.bias": {"kind": "registered_parameter", "effect": "sender mark bias; disconnected from original receiver score", "active_scalars_original": 0, "inactive_scalars_original": 4, "bridge_effective_scalars": 4},
        "body.recurrent.weight": {"kind": "registered_parameter", "effect": "previous centered boundaries; 128 zero-channel words plus 16 masked first-channel words are inactive", "active_scalars_original": 48, "inactive_scalars_original": 144},
        "body.readout.weight": {"kind": "registered_parameter", "effect": "two shared linear heads on 4 receivers x 5 features", "active_scalars_original": 40},
        "body.readout.bias": {"kind": "registered_parameter", "effect": "shared per-choice score offset; cancels in exact-arithmetic choice margin, apart from floating-point evaluation effects", "active_scalars_original": 2}
    }
    parents = []
    for seed in (47, 83, 137):
        raw, header, tensors = read(ROOT/f"late_results/{seed}/parent{seed}.safetensors")
        assert set(tensors) == set(contracts)
        for name, tensor in tensors.items():
            tensor.update(contracts[name])
        count = sum(x["scalars"] for name, x in tensors.items() if name not in buffers)
        assert count == 330
        n = struct.unpack("<Q", raw[:8])[0]
        mask_start = header["body.synaptic_mask"]["data_offsets"][0]
        mask = np.frombuffer(raw, dtype="<f4", offset=8+n+mask_start, count=192).reshape(8, 24)
        assert int(np.count_nonzero(mask[:, :8])) == 48
        assert np.array_equal(mask[:4, 4:8], np.zeros((4, 4), dtype=np.float32))
        parents.append({"seed": seed, "artifact_sha256": sha(raw),
            "source_pt_sha256": header["__metadata__"]["source_checkpoint_sha256"],
            "registered_parameter_scalars": count, "buffer_scalars": 208,
            "trainable_flags_at_checkpoint_save_recoverable": False,
            "original_graph_structurally_inactive_parameter_scalars": 192,
            "original_graph_potentially_score_connected_parameter_scalars": 138,
            "potential_connection_is_not_identifiability_or_nonzero_effect": True,
            "tensors": tensors})
    modules = [
        {"name": "state_representation", "implementation": "Population p[10], q[10], boundary plus cached physical operators, independently for 8 neurons", "checkpoint_state_tensor": None,
         "p_semantics": "6 spatial masses + 3 refractory phase masses + unused zero state", "q_semantics": "signed marked mass with |q_i|<=p_i; not Bayesian belief", "messages": "only previous centered boundary, not complete p/q", "endpoint_scope": "fixed six-tick reinitialized batch; no live persistent state in this evaluator",
         "repair_available": "explicit graph/clock/state-contract change; weight edit cannot bypass absent path", "abstain": ["requested target requires unobserved history", "unknown initial population or live step phase"]},
        {"name": "first_passage_and_reset", "implementation": "killed semigroup first-hit probability, full reset generator and conservative boundary remap", "actual_weight_controls": ["body.input_drive.weight", "body.input_drive.bias", "body.recurrent.weight", "body.raw_cost"],
         "protected_buffers": ["body.reset_absolute", "body.fixed_boundary"], "learned_reset_head": False,
         "reset_delay": {"kind": "Erlang", "stages": 3, "mean": 0.2, "stage_rate": 15.0},
         "repair_status": "analytic operators preserved, not repaired by tested four-coordinate program", "abstain": ["reset buffer edit not permitted by scope", "deposit outside supported interior cell hull", "mass/positivity/first-hit-versus-event-count invariant fails"]},
        {"name": "call_put", "implementation": "two alternative input choices share one body and a two-logit classifier", "named_call_put_tensors": [], "call_put_valuation_operator": False,
         "semantic_warning": "two choices or two logits do not establish separate Call/Put first-passage channels", "repair_status": "unsupported by this checkpoint", "abstain": ["requires distinct directional option event laws or calibrated financial payoff not present in schema"]},
        {"name": "belief", "implementation": None, "bayesian_posterior_tensor": None, "observation_likelihood": None,
         "available_state": "analytic reset-diffusion probability; it is not a learned latent-market belief", "repair_status": "missing state/observation contract, not a located bad weight", "abstain": ["target requires latent regime posterior not encoded by inputs/state"]},
        {"name": "continuation_q", "implementation": "V=(rho I-G)^(-1)r; feature=sum(p_next*V)", "discount_rate": 0.3,
         "reward": "0.8*(boundary+spatial_center)-0.25 in active cells, minus local intervention cost*event intensity", "learned_continuation_q_tensor": None,
         "global_task_bellman_objective": False, "repair_status": "preserved local analytic continuation; not a learned action-value repair", "abstain": ["request treats local physical reward as future trading return", "requested action/state/budget not represented", "proposed Bellman bound assumes an unestablished discount contraction"]},
        {"name": "ndu_value_control", "implementation_in_checkpoint": None, "learned_ndu_tensor": None,
         "available_runtime_role": "external declared goal/risk/cost guard on a finite set of evaluated actions", "global_neural_optimum_established": False,
         "repair_status": "planner semantic contract required, no NDU checkpoint head to edit", "abstain": ["unconditional retention loses any protected correct decision", "task route is absent or ambiguous", "cost/risk metric not bound to this evaluation", "only surrogate improved while endpoint regressed"]}
    ]
    timing = {"condition": "original fixed six-tick boundary-only graph, external baseline held fixed", "tick_zero_based": True,
        "physical_updates": [0, 2, 4], "old_boundary_messages": True,
        "raw_input_to_final_receiver_probability_features": {"0": True, "1": False, "2": True, "3": False, "4": False, "5": False},
        "raw_input_to_final_receiver_signed_event": {"0": True, "1": False, "2": True, "3": False, "4": True, "5": False},
        "bridge_exception": "explicit final-tick tied mark connects tick5 to receiver signed event only; changes function class",
        "evidence": ["temporal_results/RESULT.json", "graph_rollback_results/RESULT.json"]}
    gates = [
        {"id": "bind_complete_function", "requires": ["exact parameter artifact", "graph profile", "request route", "evaluator source/binary identity", "input digest", "initial state and tick phase"], "failure": "ABSTAIN"},
        {"id": "late_quote_task", "requires": ["horizon 6", "price coordinate 7 in normalized positive-scale units", "same nonprice features and history across choices", "equal external baseline", "finite distinct prices"], "failure": "ABSTAIN"},
        {"id": "late_quote_reachability", "requires": ["declared final-tick bridge", "live signed-head contrast", "nonzero final mark sensitivity and resolved F32 margin"], "failure": "ABSTAIN_OR_UNREACHABLE"},
        {"id": "scope", "requires": ["only body.input_mark.weight indices 7,16,25,34 may differ", "all other bytes and original header identical"], "failure": "REJECT"},
        {"id": "prospective_parity", "requires": ["complete native vs reduced parity before any fitting if a reduced objective is used"], "failure": "DO_NOT_START_FIT", "historical_run_deviation": "PROTOCOL_DEVIATION_01.md"},
        {"id": "real_endpoint", "requires": ["full native goal evaluation", "physical invariants", "historical regression gate or explicit exact scoped route"], "failure": "REJECT_AND_RESTORE"},
        {"id": "rollback", "requires": ["inverse bytes exact", "graph and route restored", "same input and initial/live phase", "complete features/heads/scores match original"], "failure": "DO_NOT_REPORT_RESTORED"},
        {"id": "goal_stopping", "requires": ["compare KEEP among finite actions", "if existing graph already meets declared goal, avoid unnecessary parameter edits"], "failure": "NO_GLOBAL_OPTIMALITY_CLAIM"}
    ]
    result = {"schema": "hepta.actual-smallhcsn-semantic-inventory.v1", "read_only": True, "new_model_calls": 0, "new_fits": 0,
        "source_pins": source_pins, "source_manifest_sha256": sha((SOURCE/"SOURCE_MANIFEST.json").read_bytes()),
        "source_analysis_method": "human/agent-read explicit control-flow contract plus exact tensor/layout checks; not general automatic circuit discovery",
        "parents": parents, "modules": modules, "temporal_reachability": timing, "required_semantic_gates": gates,
        "scope_contracts": {"original_profile_readout": ["body.readout.weight"], "production_sender_candidate": ["body.input_drive.weight", "body.input_drive.bias"], "research_late_quote": {"body.input_mark.weight": [7,16,25,34]}},
        "unsupported_claims": ["repair of unseen pocket4 trader weights", "learned Belief/Continuation-Q/NDU head found here", "two classes imply Call/Put event channels", "all time horizons or live phases covered", "globally optimal neural edit", "future market return improvement"]}
    (out/"INVENTORY.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"status": "PASS", "parents": len(parents), "registered_parameters_each": 330,
                      "buffers_each": 208, "modules": len(modules), "gates": len(gates),
                      "new_model_calls": 0, "new_fits": 0, "inventory_sha256": sha((out/"INVENTORY.json").read_bytes())}))


if __name__ == "__main__":
    main()
