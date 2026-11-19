"""Read every saved state tensor; compare declared observations without solvers."""

import gzip
import hashlib
import json
from fractions import Fraction
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire


def review(directory):
    root = Path(__file__).resolve().parents[2]
    directory = Path(directory)
    roster_dir = root / "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001"
    roster = json.loads((roster_dir / "CAPSULES.json").read_text())
    expected_packets = [json.loads(line) for line in (roster_dir / "PACKET_ROSTER.jsonl").read_text().splitlines()]
    results = {lane: json.loads((directory / lane / "RESULT.json").read_text())
        for lane in ("warm", "coarse", "cold")}
    capsule_hashes, checked, base_count, reset_count, physics_count = {}, 0, 0, 0, 0
    capsule_index = 0
    for lane in ("warm", "coarse", "cold"):
        for index, record in enumerate(results[lane]["capsules"]):
            payload = gzip.decompress((directory / lane / record["path"]).read_bytes())
            digest = hashlib.sha256(payload).hexdigest()
            if digest != record["sha256"] or len(payload) != record["raw_bytes"]:
                raise ValueError("raw state identity")
            envelope = wire.decode(payload, 32*1024**2)
            counts = wire.coordinate_counts(envelope)
            if counts != record["coordinates"]:
                raise ValueError("actual complete-state coordinate denominator")
            for tensor in [b.tensor for b in envelope.blocks] + [getattr(p, key) for p in envelope.packets for key in ("alpha", "generator", "output")]:
                if not np.isfinite(np.frombuffer(tensor.payload, dtype="<f8")).all():
                    raise ValueError("nonfinite original coordinate")
                checked += len(tensor.payload) // 8
            expected = roster[capsule_index]
            if (lane, index, Fraction(envelope.metadata["time"]), len(envelope.packets)) != (
                    expected["lane"], expected["lane_order"], Fraction(*expected["time"]["fraction"]), expected["packets"]):
                raise ValueError("original time/packet topology")
            packets = {p.identity: p for p in envelope.packets}
            rows = [row for row in expected_packets if row["capsule_order"] == capsule_index]
            if envelope.metadata["packet_order"] != [row["source"] for row in rows]:
                raise ValueError("original numerical packet order")
            for row in rows:
                packet = packets[row["source"]]
                if (packet.generation, packet.origin, packet.target, packet.output.shape,
                        Fraction(packet.start), Fraction(packet.end)) != (
                        row["generation"], row["origin"], row["target"], (row["dimension"],),
                        Fraction(*row["start"]["fraction"]), Fraction(*row["end"]["fraction"])):
                    raise ValueError("complete packet metadata")
            base = counts["total"] - 512 - 255*len(packets)
            if base != expected["coordinate_count"]:
                raise ValueError("old denominator changed")
            base_count += base
            reset_count += 255*len(packets)
            physics_count += 512
            capsule_hashes[(lane, index)] = digest
            capsule_index += 1
    cold_exact = [capsule_hashes[("warm", i+5)] == capsule_hashes[("cold", i)] for i in range(3)]
    if not all(cold_exact):
        raise ValueError("fresh-process complete-state equality failed")
    values = {lane: np.load(directory / lane / "STATES.npz")["values"] for lane in results}
    coarse_error = float(np.max(np.abs(values["warm"][[0, 4, 7]] - values["coarse"])))
    reference = {kind: np.load(directory / f"reference_{kind}/REFERENCE.npz")["values"] for kind in ("coarse", "fine")}
    reference_error = float(np.max(np.abs(values["warm"] - reference["fine"])))
    reference_stability = float(np.max(np.abs(reference["coarse"] - reference["fine"])))
    if coarse_error > 5e-10 or reference_error > 1e-8 or reference_stability > 1e-8:
        raise ValueError("new finite-model comparison gate")
    final = values["warm"][-1]
    active = final[:2550].reshape(5, 2, 255)
    upper = final[2550:2565].reshape(5, 3)
    phase = np.asarray([item["integrated_remaining_content"] for item in results["warm"]["remaining_phase"]]).sum(axis=0)
    balance = active.sum(axis=(1, 2)) + upper.sum(axis=1) + phase - results["warm"]["initial_total_probability_and_content"]
    if float(np.max(np.abs(balance))) > 1e-9:
        raise ValueError("complete probability/signed-content balance")
    return {"status": "VERIFIED_FINITE_MULTISTEP_AND_COLD_STATE", "capsules": capsule_index,
        "every_saved_coordinate_checked": checked, "base_roster_coordinates": base_count,
        "additional_reset_coordinates": reset_count, "additional_physics_coordinates": physics_count,
        "fresh_process_full_state_byte_equal": cold_exact,
        "warm_coarse_all_2600_state_coordinate_max_abs": coarse_error,
        "independent_BDF_all_state_coordinate_max_abs": reference_error,
        "BDF_two_tolerance_max_abs": reference_stability,
        "complete_probability_and_signed_content_balance": balance.tolist(),
        "new_model_numeric_gates": {"semigroup_abs": 5e-10, "BDF_abs": 1e-8, "balance_abs": 1e-9},
        "original_sparse_bitwise_gate": "RED_UNCHANGED", "original_full_roster_admitted": False,
        "continuum_qualified": False, "autograd_qualified": False, "optimizer_steps": 0, "all_closed": False}


if __name__ == "__main__":
    import sys
    result = review(sys.argv[1])
    target = Path(sys.argv[1]) / "REVIEW.json"
    target.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(target.read_text())
