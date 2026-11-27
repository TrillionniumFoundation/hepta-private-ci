"""Read-only re-audit of the frozen N256 multistep outputs without running solvers."""

import gzip
import hashlib
import json
from fractions import Fraction
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire


LANE_COUNTS = {"warm": 8, "coarse": 3, "cold": 3}
WARM_QUERIES = ("0", "1/1000", "1/50", "4/25", "1/5", "201/1000", "7/25", "9/25")
STATE_BLOCKS = (
    ("active", (5, 2, 255)),
    ("upper", (5, 3)),
    ("mass", (5, 2)),
    ("discounted_hit", (5, 2)),
    ("occupation", (5, 3)),
)
WIDTH = 2600
WIRE_LIMIT = 32 * 1024**2


def require_fp64(array, shape, name):
    if array.dtype != np.dtype("<f8") or array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{name}: expected finite little-endian FP64 with shape {shape}")
    return array


def load_values(path, count):
    with np.load(path, allow_pickle=False) as archive:
        if archive.files.count("values") != 1:
            raise ValueError(f"{path}: expected exactly one values member")
        return require_fp64(archive["values"], (count, WIDTH), str(path))


def capsule_row(envelope):
    blocks = {block.name: block.tensor for block in envelope.blocks}
    chunks = []
    for name, shape in STATE_BLOCKS:
        block = blocks.get(name)
        if block is None or block.dtype != "<f8" or block.shape != shape:
            raise ValueError(f"decoded state block: {name}")
        data = np.frombuffer(block.payload, dtype="<f8").reshape(shape)
        require_fp64(data, shape, name)
        chunks.append(block.payload)
    return b"".join(chunks)


def require_binding(values, index, envelope):
    if values[index].tobytes(order="C") != capsule_row(envelope):
        raise ValueError(f"capsule/NPZ byte mismatch at row {index}")


def load_reference(directory):
    record = json.loads((directory / "RESULT.json").read_text())
    if record.get("queries") != list(WARM_QUERIES) or record.get("shape") != [8, WIDTH]:
        raise ValueError(f"{directory}: unexpected BDF query roster or shape")
    return load_values(directory / "REFERENCE.npz", len(WARM_QUERIES))


def phase_and_initial(result, ordered_packet_ids):
    rows = result["remaining_phase"]
    if [item["identity"] for item in rows] != ordered_packet_ids:
        raise ValueError("remaining-phase roster differs from final verified capsule")
    totals = np.asarray([item["integrated_remaining_content"] for item in rows], dtype="<f8")
    initial = np.asarray(result["initial_total_probability_and_content"], dtype="<f8")
    require_fp64(totals, (len(ordered_packet_ids), 5), "remaining phase")
    require_fp64(initial, (5,), "initial total")
    return totals.sum(axis=0), initial


def review(directory):
    root = Path(__file__).resolve().parents[2]
    directory = Path(directory)
    roster_dir = root / "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001"
    roster = json.loads((roster_dir / "CAPSULES.json").read_text())
    expected_packets = [json.loads(line) for line in (roster_dir / "PACKET_ROSTER.jsonl").read_text().splitlines()]
    results = {lane: json.loads((directory / lane / "RESULT.json").read_text())
        for lane in ("warm", "coarse", "cold")}
    if len(roster) != sum(LANE_COUNTS.values()) or any(
        len(results[lane]["capsules"]) != count for lane, count in LANE_COUNTS.items()
    ):
        raise ValueError("unexpected complete-state capsule denominator")
    values = {
        lane: load_values(directory / lane / "STATES.npz", count)
        for lane, count in LANE_COUNTS.items()
    }
    final_packet_ids = None
    capsule_hashes, checked, base_count, reset_count, physics_count = {}, 0, 0, 0, 0
    capsule_index = 0
    for lane in ("warm", "coarse", "cold"):
        for index, record in enumerate(results[lane]["capsules"]):
            if record["path"] != f"capsule-{index}.bin.gz":
                raise ValueError("unexpected capsule path")
            with gzip.open(directory / lane / record["path"], "rb") as stream:
                payload = stream.read(WIRE_LIMIT + 1)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != record["sha256"] or len(payload) != record["raw_bytes"]:
                raise ValueError("raw state identity")
            envelope = wire.decode(payload, WIRE_LIMIT)
            require_binding(values[lane], index, envelope)
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
            if lane == "warm" and index == LANE_COUNTS["warm"] - 1:
                final_packet_ids = envelope.metadata["packet_order"]
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
    coarse_error = float(np.max(np.abs(values["warm"][[0, 4, 7]] - values["coarse"])))
    reference = {
        kind: load_reference(directory / f"reference_{kind}") for kind in ("coarse", "fine")
    }
    reference_error = float(np.max(np.abs(values["warm"] - reference["fine"])))
    reference_stability = float(np.max(np.abs(reference["coarse"] - reference["fine"])))
    if not np.isfinite([coarse_error, reference_error, reference_stability]).all():
        raise ValueError("nonfinite finite-model comparison")
    if coarse_error > 5e-10 or reference_error > 1e-8 or reference_stability > 1e-8:
        raise ValueError("new finite-model comparison gate")
    final = values["warm"][-1]
    active = final[:2550].reshape(5, 2, 255)
    upper = final[2550:2565].reshape(5, 3)
    phase, initial = phase_and_initial(results["warm"], final_packet_ids)
    balance = active.sum(axis=(1, 2)) + upper.sum(axis=1) + phase - initial
    require_fp64(balance, (5,), "computed balance")
    if float(np.max(np.abs(balance))) > 1e-9:
        raise ValueError("complete probability/signed-content balance")
    return {"status": "REAUDITED_FINITE_MULTISTEP_ARTIFACTS", "capsules": capsule_index,
        "all_candidate_rows_exactly_bound_to_capsules": True,
        "remaining_phase_roster_verified": True,
        "remaining_phase_values_source": "producer_report_not_reintegrated",
        "BDF_values_source": "producer_saved_reference_not_regenerated",
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
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
