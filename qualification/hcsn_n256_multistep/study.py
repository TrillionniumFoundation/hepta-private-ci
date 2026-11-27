"""One frozen lane per fresh, externally limited interpreter."""

import argparse
import json
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n256_engineering import candidate as primitive
from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent import adapter
from qualification.hcsn_n256_multistep import flow, storage


def inputs(root):
    hashes, metadata, phase, arrays = primitive.load_inputs(
        *(root / adapter.RELATIVE[key] for key in ("metadata", "state", "phase", "npz_b64")))
    if primitive.digest(primitive.canonical(hashes)) != flow.INPUT_BUNDLE_SHA256:
        raise ValueError("authentic study input identity")
    spatial, lower, upper, reset = primitive.spatial_operator(metadata, arrays["nodes.npy"][1])
    state, pending = flow._initial_state(metadata, phase, arrays, primitive, flow.INPUT_BUNDLE_SHA256, reset, np)
    physics = {"metadata": metadata, "nodes": arrays["nodes.npy"][1], "reset": reset}
    return state, pending, physics, spatial, lower, upper


def phase_total(capsule, counts):
    modules = flow._numeric_modules()
    rows = []
    for packet in capsule.packets:
        matrix = flow._csr(packet.operator, modules[1][0])
        _, value = flow._action(matrix, np.asarray(packet.alpha).reshape(5, packet.dimension),
            np.asarray(packet.output)[:, None], packet.end - packet.start, 0., modules, counts)
        rows.append({"identity": packet.source, "integrated_remaining_content": value[:, 0].tolist()})
    return rows


def run(lane, root, directory):
    directory.mkdir()
    if lane == "controls":
        from qualification.hcsn_n256_multistep.controls import run as controls
        return controls()
    if lane.startswith("reference"):
        from qualification.hcsn_n256_multistep.reference import run as reference
        authentic = adapter.load_authentic_input(root)
        metadata = json.loads((root / adapter.RELATIVE["metadata"]).read_text())
        rtol = 2e-10 if lane == "reference_coarse" else 2e-12
        values, records, raw = reference(authentic, metadata, rtol, flow.WARM)
        np.savez_compressed(directory / "REFERENCE.npz", values=values, **raw)
        return {"rtol": rtol, "atol": rtol * 1e-3, "segments": records,
            "queries": list(map(str, flow.WARM)), "shape": list(values.shape),
            "packet_actions": 0, "authentic_input_loads": 1, "optimizer_steps": 0}
    if lane == "cold":
        saved, state, pending, physics = storage.load(directory.parent / "warm/capsule-5.bin.gz")
        spatial, lower, upper, interpolated = primitive.spatial_operator(physics["metadata"], physics["nodes"])
        if tuple(interpolated) != physics["reset"]:
            raise ValueError("restored physics reset law")
        start, queries, input_loads = saved.time, flow.COLD, 0
    else:
        state, pending, physics, spatial, lower, upper = inputs(root)
        start, queries, input_loads = flow.F(0), flow.WARM if lane == "warm" else flow.COARSE, 1
    initial_total = None
    if lane == "warm":
        initial_total = state.active.sum(axis=(1, 2)) + state.upper.sum(axis=1)
        initial_total += sum(np.asarray(packet.alpha) * float(packet.end - packet.start) for packet in pending)
    counts = flow.Counts()
    capsules, _, _ = flow._run_lane(lane, queries, state, pending, start, primitive,
        spatial, lower, upper, physics["reset"], flow.INPUT_BUNDLE_SHA256,
        flow._numeric_modules(), counts)
    records = [storage.save(capsule, physics, directory / f"capsule-{i}.bin.gz")
        for i, capsule in enumerate(capsules)]
    np.savez_compressed(directory / "STATES.npz", values=np.asarray([capsule.state for capsule in capsules]))
    phase_counts = flow.Counts()
    phase = phase_total(capsules[-1], phase_counts) if lane == "warm" else []
    return {"lane": lane, "capsules": records, "dynamic_segments": counts.segments,
        "exponential_actions": counts.expm_actions, "actions": counts.actions,
        "phase_integral_actions": phase_counts.actions, "remaining_phase": phase,
        "initial_total_probability_and_content": None if initial_total is None else initial_total.tolist(),
        "authentic_input_loads": input_loads, "optimizer_steps": 0,
        "old_sparse_bitwise_gate": "RED_UNCHANGED", "largegrid_qualification": False,
        "full_roster_original_admission": False, "all_closed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lane", choices=("controls", "warm", "coarse", "cold", "reference_coarse", "reference_fine"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = run(args.lane, root, args.output / args.lane)
    (args.output / args.lane / "RESULT.json").write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"lane": args.lane, "status": "COMPLETED", "optimizer_steps": 0}))


if __name__ == "__main__":
    main()
