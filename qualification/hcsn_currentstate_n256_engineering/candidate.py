"""Hash-bound N256 sparse-operator topology and resource pre-admission.

This module consumes the exact new-export-only N256 inputs and the independently
published symbolic roster. It never propagates state and never calls expm.
"""

import base64
import io
import json
import zipfile
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path

from qualification.hcsn_currentstate_n128_engineering import candidate as n128


N128_PRIMITIVE_SOURCE_SHA256 = (
    "0152e168cd3c5581517522b972276f6317c907eb740a09adb5219a9e820a09ad"
)
if n128.digest(Path(n128.__file__).read_bytes()) != N128_PRIMITIVE_SOURCE_SHA256:
    raise ValueError("pinned primitive source mismatch")

CSR = n128.CSR
Template = n128.Template
canonical = n128.canonical
digest = n128.digest
read_npy = n128.read_npy
source_identity = n128.source_identity

EXPECTED_INPUTS = {
    "metadata": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "state": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "phase": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "npz_b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "npz": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
}
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
INPUT_BUNDLE_IDENTITY = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
INTERIOR = 255
CHANNELS = 5
WARM = tuple(F(value) for value in ("0", ".001", ".02", ".16", ".2", ".201", ".28", ".36"))
COARSE = (F(0), F(1, 5), F(9, 25))
COLD = (F(201, 1000), F(7, 25), F(9, 25))


def load_inputs(metadata_path, state_path, phase_path, npz_b64_path):
    paths = {
        "metadata": Path(metadata_path),
        "state": Path(state_path),
        "phase": Path(phase_path),
        "npz_b64": Path(npz_b64_path),
    }
    hashes = {name: digest(path.read_bytes()) for name, path in paths.items()}
    decoded = base64.b64decode(paths["npz_b64"].read_text().strip(), validate=True)
    hashes["npz"] = digest(decoded)
    if hashes != EXPECTED_INPUTS:
        raise ValueError("authentic N256 input hash mismatch")
    metadata = json.loads(paths["metadata"].read_text())
    state = json.loads(paths["state"].read_text())
    phase = json.loads(paths["phase"].read_text())
    if (
        metadata["identity"] != "hcsn-n256-new-export-20261112-c06d-attempt001"
        or state["identity"] != metadata["identity"]
        or phase["identity"] != metadata["identity"]
        or metadata["historical_N256_export_present"] is not False
        or metadata["dynamic_execution_allowed"] is not False
        or state["intervals"] != 256
        or phase["packet_count"] != 8
    ):
        raise ValueError("authentic N256 metadata mismatch")
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        if set(archive.namelist()) != {"active.npy", "content.npy", "nodes.npy"}:
            raise ValueError("N256 NPZ member set")
        arrays = {name: read_npy(archive.read(name)) for name in archive.namelist()}
    if (
        arrays["active.npy"][0] != (257,)
        or arrays["content.npy"][0] != (257, 4)
        or arrays["nodes.npy"][0] != (257,)
    ):
        raise ValueError("N256 array shape")
    if (
        [float(value).hex() for value in arrays["nodes.npy"][1]]
        != state["nodes_fp64_hex"]
        or [float(value).hex() for value in arrays["active.npy"][1]]
        != state["active_probability_fp64_hex"]
        or [float(value).hex() for value in arrays["content.npy"][1]]
        != state["signed_content_fp64_hex_row_major"]
    ):
        raise ValueError("N256 state readback")
    return hashes, metadata, phase, arrays


def spatial_operator(metadata, nodes):
    mu, sigma = metadata["physics"]["mu"], metadata["physics"]["sigma"]
    gaps = [right - left for left, right in zip(nodes, nodes[1:])]
    rows = [dict() for _ in range(INTERIOR)]
    lower = [0.0] * INTERIOR
    upper = [0.0] * INTERIOR
    for index in range(INTERIOR):
        left, right = gaps[index], gaps[index + 1]
        down = (sigma**2 - mu * right) / (left * (left + right))
        up = (sigma**2 + mu * left) / (right * (left + right))
        rows[index][index] = -(down + up)
        if index:
            rows[index][index - 1] = down
        else:
            lower[index] = down
        if index + 1 < INTERIOR:
            rows[index][index + 1] = up
        else:
            upper[index] = up
    reset_position = metadata["reset_distance"]
    right = next(index for index, value in enumerate(nodes) if value > reset_position)
    left = right - 1
    fraction = (reset_position - nodes[left]) / (nodes[right] - nodes[left])
    reset = [0.0] * INTERIOR
    for full_index, weight in ((left, 1 - fraction), (right, fraction)):
        if not 1 <= full_index <= INTERIOR:
            raise ValueError("reset is not interior")
        reset[full_index - 1] = weight
    return CSR.from_rows(rows), tuple(lower), tuple(upper), tuple(reset)


def block_operator(parents, spatial, lower, reset):
    dimension = INTERIOR + sum(parent.dimension for parent in parents)
    rows = [dict() for _ in range(dimension)]
    offset = 0
    for parent in parents:
        for row in range(parent.dimension):
            for index in range(
                parent.operator.indptr[row], parent.operator.indptr[row + 1]
            ):
                rows[offset + row][offset + parent.operator.indices[index]] = (
                    parent.operator.data[index]
                )
            if parent.output[row] != 0:
                for node, weight in enumerate(reset):
                    if weight != 0:
                        rows[offset + row][dimension - INTERIOR + node] = (
                            parent.output[row] * weight
                        )
        offset += parent.dimension
    for row in range(INTERIOR):
        for index in range(spatial.indptr[row], spatial.indptr[row + 1]):
            rows[offset + row][offset + spatial.indices[index]] = spatial.data[index]
    output = (0.0,) * (dimension - INTERIOR) + lower
    return CSR.from_rows(rows), output


def roster_records(roster_dir):
    roster_dir = Path(roster_dir)
    summary = json.loads((roster_dir / "SUMMARY.json").read_text())
    if (
        summary["coordinate_identity_sha256"] != ROSTER_IDENTITY
        or summary["input_bundle_sha256"] != INPUT_BUNDLE_IDENTITY
        or summary["fp64_coordinate_denominator"] != 18_225_028
        or summary["largest_capsule_coordinates"] != 3_444_164
        or summary["historical_N256_export_present"] is not False
        or summary["new_export_only"] is not True
    ):
        raise ValueError("#6294 N256 roster identity")
    packets = [
        json.loads(line)
        for line in (roster_dir / "PACKET_ROSTER.jsonl").read_text().splitlines()
    ]
    capsules = json.loads((roster_dir / "CAPSULES.json").read_text())
    events = [
        json.loads(line)
        for line in (roster_dir / "EVENTS.jsonl").read_text().splitlines()
    ]
    return summary, packets, capsules, events


def build_graph(metadata_path, state_path, phase_path, npz_b64_path, roster_dir):
    hashes, metadata, phase, arrays = load_inputs(
        metadata_path, state_path, phase_path, npz_b64_path
    )
    summary, published, capsules, events = roster_records(roster_dir)
    nodes = arrays["nodes.npy"][1]
    spatial, lower, upper, reset = spatial_operator(metadata, nodes)
    zero = CSR.from_rows(({},))
    bundle = digest(canonical(hashes))
    if bundle != INPUT_BUNDLE_IDENTITY:
        raise ValueError("N256 input bundle identity")
    initial = []
    for item in phase["packets"]:
        start, end = F(item["start"]), F(item["end"])
        source = source_identity(bundle, item["identity"], start, end, 1, 0, ())
        initial.append(Template(source, 1, start, end, 1, 0, zero, (1.0,), ()))

    emitted = []
    capsule_rows = []
    event_rows = []

    def lane(name, queries, start=None):
        time, pending = (F(0), tuple(initial)) if start is None else start
        for lane_order, query in enumerate(queries):
            while time < query:
                left = time
                boundaries = [query, left + F(1, 5)]
                for packet in pending:
                    boundaries.extend((packet.start, packet.end))
                right = min(value for value in boundaries if value > left)
                releasing = tuple(packet for packet in pending if packet.start == left)
                retained = [
                    replace(packet, start=right)
                    if packet.start == left and packet.end > right
                    else packet
                    for packet in pending
                    if packet.start != left or packet.end > right
                ]
                for origin, target in ((1, 2), (2, 3)):
                    if origin == 2 and left < F(1, 5):
                        continue
                    parents = tuple(
                        packet for packet in releasing if packet.target == origin
                    )
                    operator, output = block_operator(
                        parents, spatial, lower, reset
                    )
                    source = source_identity(
                        bundle,
                        "lower-flux",
                        left,
                        right,
                        target,
                        origin,
                        [packet.source for packet in parents],
                    )
                    packet = Template(
                        source,
                        target,
                        left + F(1, 5),
                        right + F(1, 5),
                        target,
                        origin,
                        operator,
                        output,
                        tuple(parent.source for parent in parents),
                    )
                    retained.append(packet)
                    emitted.append(packet)
                pending = tuple(retained)
                time = right
                event_rows.append((name, left, right, len(releasing), len(pending)))
            capsule_rows.append((name, lane_order, time, pending))
        return time, pending

    saved = None
    time, pending = F(0), tuple(initial)
    for query in WARM:
        time, pending = lane("warm", (query,), (time, pending))
        if query == COLD[0]:
            saved = (time, pending)
    lane("coarse", COARSE)
    if saved is None:
        raise ValueError("cold source capsule")
    lane("cold", COLD, saved)

    counters = {"warm": 0, "coarse": 0, "cold": 0}
    normalized = []
    for name, _, time, pending in capsule_rows:
        normalized.append((name, counters[name], time, pending))
        counters[name] += 1
    capsule_rows = normalized
    if len(capsule_rows) != 14 or len(event_rows) != 45:
        raise ValueError("N256 candidate event count")

    published_by_capsule = {}
    for record in published:
        published_by_capsule.setdefault(record["capsule_order"], []).append(record)
    conceptual = 0
    for order, ((lane_name, lane_order, time, pending), capsule) in enumerate(
        zip(capsule_rows, capsules)
    ):
        if (
            lane_name,
            lane_order,
            [time.numerator, time.denominator],
            len(pending),
        ) != (
            capsule["lane"],
            capsule["lane_order"],
            capsule["time"]["fraction"],
            capsule["packets"],
        ):
            raise ValueError("N256 candidate capsule roster mismatch")
        records = published_by_capsule[order]
        if len(records) != len(pending):
            raise ValueError("N256 candidate packet count")
        for packet, record in zip(pending, records):
            actual = (
                packet.source,
                packet.generation,
                packet.dimension,
                packet.target,
                packet.origin,
                [packet.start.numerator, packet.start.denominator],
                [packet.end.numerator, packet.end.denominator],
            )
            expected = (
                record["source"],
                record["generation"],
                record["dimension"],
                record["target"],
                record["origin"],
                record["start"]["fraction"],
                record["end"]["fraction"],
            )
            if actual != expected:
                raise ValueError("N256 candidate packet roster mismatch")
        count = (
            10 * INTERIOR
            + 50
            + sum(packet.dimension**2 + 6 * packet.dimension for packet in pending)
        )
        if count != capsule["coordinate_count"]:
            raise ValueError("N256 candidate denominator mismatch")
        conceptual += count

    event_expected = [
        (
            event["lane"],
            F(*event["left"]["fraction"]),
            F(*event["right"]["fraction"]),
            event["releasing"],
            event["pending_after"],
        )
        for event in events
        if event["kind"] == "transition"
    ]
    if event_rows != event_expected:
        raise ValueError("N256 candidate transition roster mismatch")
    if conceptual != summary["fp64_coordinate_denominator"]:
        raise ValueError("N256 conceptual denominator mismatch")

    operators = {
        packet.operator.identity: packet.operator for packet in (*initial, *emitted)
    }
    sparse_bytes = sum(
        8 * len(operator.indptr)
        + 4 * len(operator.indices)
        + 8 * len(operator.data)
        for operator in operators.values()
    )
    return {
        "summary": summary,
        "input_sha256": hashes,
        "input_bundle_sha256": bundle,
        "operators": len(operators),
        "operator_nnz": sum(len(operator.data) for operator in operators.values()),
        "unique_sparse_operator_bytes": sparse_bytes,
        "conceptual_coordinates": conceptual,
        "templates_emitted": len(emitted),
        "transition_segments": len(event_rows),
        "upper_sink_nnz": sum(value != 0 for value in upper),
        "matrix_exponentials": 0,
        "oracle_calls": 0,
    }
