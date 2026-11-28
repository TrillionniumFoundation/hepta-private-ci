"""Prepare a new unlabeled affine-interface view of actual checkpoint weights."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from temporal_probe import previous

ROOT = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    out = ROOT/"blind_alias"
    out.mkdir(exist_ok=False)
    rng = np.random.Generator(np.random.PCG64(2026112807))
    packet = {"schema": "hepta.anonymous-affine-weight-view.v1", "known_mechanism_transfer": True,
        "task": {"goal": "select lower physical final quote", "shared_history_and_nonquote": True,
                 "equal_external_baseline": True, "final_tick_bridge_explicit": True,
                 "no_examples_or_labels_in_packet": True},
        "contract": {"signed_feature": "a_j + alpha_j*tanh(R_j + sum_k A_jk*z_k + d_j)",
            "alpha": "nonnegative physical coefficient, shared across choices for this task", "score": "head[1]-head[0], plus shared non-signed offsets",
            "history_and_recurrence_sign_gauge": "already transformed consistently with unit signs; shared across choices",
            "allowed": "Only quote-column affine weights may change; preserve each nonzero magnitude. Derived view biases must compensate the quote coordinate origin so native biases remain fixed.",
            "origin_compensation": "d_new[j] = d_old[j] - (A_new[j,q]-A_old[j,q])*quote_translation",
            "nonzero_price_scale": True, "abstain": "all usable signed-head contrasts zero, missing/ambiguous unit or coordinate binding, invalid task contract",
            "output_schema": {"schema": "hepta.anonymous-affine-edit.v1", "cases": "list of {case_id, status: EDIT|KEEP|ABSTAIN, affine_values: full 4x9 array, derived_bias_values: length4, explanation: string}"}},
        "cases": []}
    mapping = []
    old = previous()
    for seed, quote_scale in zip((47, 83, 137), (2., -.5, -4.), strict=True):
        state = old.read_checkpoint(seed)
        pi = rng.permutation(4)
        phi = rng.permutation(9)
        signs = rng.choice([-1., 1.], 4)
        scales = rng.choice([-.5, .5, -1., 1., -2., 2.], 9)
        shifts = rng.integers(-4, 5, 9).astype(float)/4
        q = int(np.where(phi == 7)[0][0])
        scales[q] = quote_scale
        if shifts[q] == 0:
            shifts[q] = .75
        units = ["u_"+bytes(rng.integers(0,256,4,dtype=np.uint8)).hex() for _ in range(4)]
        case_id = "case_"+bytes(rng.integers(0,256,5,dtype=np.uint8)).hex()
        matrix = signs[:, None]*state["body.input_mark.weight"][pi][:,phi].astype(float)/scales
        bias = signs*state["body.input_mark.bias"][pi].astype(float)-matrix@shifts
        canonical_signed = np.arange(2,20,5)
        head = state["body.readout.weight"][:,canonical_signed[pi]].astype(float)*signs
        order = rng.permutation(4)
        rows = [{"coordinate_id": "c_"+bytes(rng.integers(0,256,4,dtype=np.uint8)).hex(),
                 "role": "physical_quote" if original == 7 else "shared_context",
                 "representation": "z = scale * physical_value + translation", "scale": float(scales[k]), "translation": float(shifts[k])}
                for k,original in enumerate(phi)]
        packet["cases"].append({"case_id": case_id, "affine": {"tensor_id": "t_"+bytes(rng.integers(0,256,4,dtype=np.uint8)).hex(), "row_unit_ids": units, "column_coordinates": rows, "values": matrix.tolist(), "bias_values": bias.tolist()},
            "signed_readout": {"tensor_id": "t_"+bytes(rng.integers(0,256,4,dtype=np.uint8)).hex(), "head_order": [0,1], "column_unit_ids": [units[j] for j in order], "values": head[:,order].tolist()}})
        mapping.append({"case_id": case_id, "seed": seed, "unit_permutation": pi.tolist(), "feature_permutation": phi.tolist(), "unit_signs": signs.tolist(), "scales": scales.tolist(), "translations": shifts.tolist(), "quote_column": q,
                        "canonical_source_pt_sha256": old.CHECKPOINT_SHA[seed]})
    rng.shuffle(packet["cases"])
    path = out/"EDITOR_PACKET.json"
    path.write_text(json.dumps(packet, indent=2)+"\n")
    (out/"HOST_MAPPING.json").write_text(json.dumps(mapping, indent=2)+"\n")
    seal = {"schema": "hepta.alias-packet-seal.v1", "created_unix": time.time(),
            "protocol_sha256": sha((ROOT/"BLIND_ALIAS_PROTOCOL.md").read_bytes()),
            "packet_sha256": sha(path.read_bytes()), "host_mapping_sha256": sha((out/"HOST_MAPPING.json").read_bytes()),
            "source_sha256": sha(Path(__file__).read_bytes()), "new_task_data_generated": False, "editor_program_received": False}
    (out/"PACKET_SEAL.json").write_text(json.dumps(seal, indent=2)+"\n")
    print(json.dumps(seal))


if __name__ == "__main__":
    main()
