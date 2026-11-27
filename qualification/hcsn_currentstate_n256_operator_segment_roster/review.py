"""Reconstruct exact N256 sparse-operator and segment rosters without dynamics.

The review consumes the exact new-export-only input bundle and the published
symbolic packet roster.  It materializes only the four reusable CSR topology
objects.  It never propagates state and never calls an exponential, oracle,
serializer, Torch, optimizer, or model.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, replace
from fractions import Fraction as F
from pathlib import Path

from qualification.hcsn_currentstate_n256_engineering import candidate


ENGINEERING_SOURCE_SHA256 = (
    "91c55d87fd993c9d01d1b1e98ba855bf171dfd74f2bdc12bd94fc23d9dc7a9d3"
)
PRIMITIVE_SOURCE_SHA256 = (
    "0152e168cd3c5581517522b972276f6317c907eb740a09adb5219a9e820a09ad"
)
INPUT_SHA256 = {
    "metadata": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "state": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "phase": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "npz_b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "npz": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
}
ROSTER_SHA256 = {
    "summary": "e3e21bd9f21940e22738b8f06b9b50333d82a923a6d46894316c242b88dd122f",
    "packets": "cc5a9199c076215d2f808f0974cc201d34954eafebafea1bf955c929eb36dc1c",
    "capsules": "eebc5a010c935c9ca5fc3daaa1716733907f34039c7e3ae4e4bf8fff8ef441f8",
    "events": "e84d6ca273236341f6bd138bff9c199758fb8cf4ed43a0550ca3e77ff8076d0a",
}
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
PUBLISHED_ROSTER_IDENTITY = (
    "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
)
EXPECTED_OPERATOR_ROSTER_SHA256 = (
    "b4f1916f021df7c8d4b0cc8f25e09511a427c49c21e45d1432d7d918cb6f8b20"
)
EXPECTED_SEGMENT_ROSTER_SHA256 = (
    "e619e001e04bb0dcc64cb1be78cc9773381241ac8d8a4171d3d4f1b7041eace9"
)


class RosterReviewError(ValueError):
    """Raised before accepting a changed input or noncanonical roster."""


@dataclass(frozen=True)
class OperatorSegmentCertificate:
    engineering_source_sha256: str
    primitive_source_sha256: str
    input_bundle_sha256: str
    published_roster_identity: str
    operator_roster_sha256: str
    segment_roster_sha256: str
    unique_operators: int
    operator_nnz: int
    unique_sparse_operator_bytes: int
    transition_segments: int
    emitted_templates: int
    initial_templates: int
    dynamic_calls: int = 0
    matrix_exponential_calls: int = 0
    oracle_calls: int = 0
    serializer_calls: int = 0
    torch_calls: int = 0
    optimizer_calls: int = 0
    model_calls: int = 0
    provider_calls: int = 0
    numerical_execution_allowed: bool = False
    provider_admitted: bool = False
    largegrid_qualification: bool = False
    all_closed: bool = False


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _csr_record(operator, emitted_uses, initial_uses=0):
    return {
        "operator_identity": operator.identity,
        "dimension": operator.dimension,
        "nnz": len(operator.data),
        "csr_bytes": (
            8 * len(operator.indptr)
            + 4 * len(operator.indices)
            + 8 * len(operator.data)
        ),
        "emitted_uses": emitted_uses,
        "initial_template_uses": initial_uses,
    }


def _fraction_pair(value):
    return [value.numerator, value.denominator]


def _require_source_and_original_hashes(paths, roster_dir):
    engineering_path = Path(candidate.__file__)
    primitive_path = Path(candidate.n128.__file__)
    if _digest(engineering_path.read_bytes()) != ENGINEERING_SOURCE_SHA256:
        raise RosterReviewError("N256 engineering source SHA-256 mismatch")
    if _digest(primitive_path.read_bytes()) != PRIMITIVE_SOURCE_SHA256:
        raise RosterReviewError("N128 primitive source SHA-256 mismatch")
    actual_inputs = {
        name: _digest(Path(path).read_bytes()) for name, path in paths.items()
    }
    if actual_inputs != {name: INPUT_SHA256[name] for name in paths}:
        raise RosterReviewError("N256 input-original SHA-256 mismatch")
    roster_dir = Path(roster_dir)
    actual_roster = {
        "summary": _digest((roster_dir / "SUMMARY.json").read_bytes()),
        "packets": _digest((roster_dir / "PACKET_ROSTER.jsonl").read_bytes()),
        "capsules": _digest((roster_dir / "CAPSULES.json").read_bytes()),
        "events": _digest((roster_dir / "EVENTS.jsonl").read_bytes()),
    }
    if actual_roster != ROSTER_SHA256:
        raise RosterReviewError("N256 roster-original SHA-256 mismatch")


def reconstruct_rosters(metadata_path, state_path, phase_path, npz_b64_path, roster_dir):
    """Return canonical operator and per-segment rosters after exact validation."""

    paths = {
        "metadata": metadata_path,
        "state": state_path,
        "phase": phase_path,
        "npz_b64": npz_b64_path,
    }
    _require_source_and_original_hashes(paths, roster_dir)
    hashes, metadata, phase, arrays = candidate.load_inputs(
        metadata_path, state_path, phase_path, npz_b64_path
    )
    summary, published, capsules, events = candidate.roster_records(roster_dir)
    if hashes != INPUT_SHA256 or summary["coordinate_identity_sha256"] != PUBLISHED_ROSTER_IDENTITY:
        raise RosterReviewError("N256 input bundle or roster identity mismatch")
    bundle = _digest(_canonical(hashes))
    if bundle != INPUT_BUNDLE_SHA256:
        raise RosterReviewError("N256 input bundle SHA-256 mismatch")

    nodes = arrays["nodes.npy"][1]
    spatial, lower, _upper, reset = candidate.spatial_operator(metadata, nodes)
    zero = candidate.CSR.from_rows(({},))
    initial = []
    for item in phase["packets"]:
        start, end = F(item["start"]), F(item["end"])
        source = candidate.source_identity(
            bundle, item["identity"], start, end, 1, 0, ()
        )
        initial.append(
            candidate.Template(source, 1, start, end, 1, 0, zero, (1.0,), ())
        )

    emitted = []
    capsule_rows = []
    segment_rows = []
    lane_segment_counts = Counter()

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
                emitted_rows = []
                for origin, target in ((1, 2), (2, 3)):
                    if origin == 2 and left < F(1, 5):
                        continue
                    parents = tuple(
                        packet for packet in releasing if packet.target == origin
                    )
                    operator, output = candidate.block_operator(
                        parents, spatial, lower, reset
                    )
                    parent_sources = sorted(packet.source for packet in parents)
                    source = candidate.source_identity(
                        bundle,
                        "lower-flux",
                        left,
                        right,
                        target,
                        origin,
                        parent_sources,
                    )
                    packet = candidate.Template(
                        source,
                        target,
                        left + F(1, 5),
                        right + F(1, 5),
                        target,
                        origin,
                        operator,
                        output,
                        tuple(parent_sources),
                    )
                    retained.append(packet)
                    emitted.append(packet)
                    emitted_rows.append(
                        {
                            "origin": origin,
                            "target": target,
                            "emitted_source": source,
                            "operator_identity": operator.identity,
                            "dimension": operator.dimension,
                            "nnz": len(operator.data),
                            "csr_bytes": (
                                8 * len(operator.indptr)
                                + 4 * len(operator.indices)
                                + 8 * len(operator.data)
                            ),
                            "parent_sources": parent_sources,
                            "parent_dimensions": sorted(
                                packet.dimension for packet in parents
                            ),
                        }
                    )
                pending = tuple(retained)
                time = right
                segment_rows.append(
                    {
                        "segment_order": len(segment_rows),
                        "lane_segment_order": lane_segment_counts[name],
                        "lane": name,
                        "left_fraction": _fraction_pair(left),
                        "right_fraction": _fraction_pair(right),
                        "releasing": len(releasing),
                        "pending_after": len(pending),
                        "emitted": emitted_rows,
                    }
                )
                lane_segment_counts[name] += 1
            capsule_rows.append((name, lane_order, time, pending))
        return time, pending

    saved = None
    time, pending = F(0), tuple(initial)
    for query in candidate.WARM:
        time, pending = lane("warm", (query,), (time, pending))
        if query == candidate.COLD[0]:
            saved = (time, pending)
    lane("coarse", candidate.COARSE)
    if saved is None:
        raise RosterReviewError("cold source capsule is absent")
    lane("cold", candidate.COLD, saved)

    counters = Counter()
    normalized_capsules = []
    for name, _lane_order, time, pending in capsule_rows:
        normalized_capsules.append((name, counters[name], time, pending))
        counters[name] += 1
    if len(normalized_capsules) != 14 or len(segment_rows) != 45:
        raise RosterReviewError("N256 capsule or segment count mismatch")

    published_by_capsule = {}
    for record in published:
        published_by_capsule.setdefault(record["capsule_order"], []).append(record)
    conceptual = 0
    for order, ((name, lane_order, time, pending), capsule) in enumerate(
        zip(normalized_capsules, capsules)
    ):
        if (
            name,
            lane_order,
            _fraction_pair(time),
            len(pending),
        ) != (
            capsule["lane"],
            capsule["lane_order"],
            capsule["time"]["fraction"],
            capsule["packets"],
        ):
            raise RosterReviewError("N256 capsule roster mismatch")
        records = published_by_capsule.get(order, [])
        if len(records) != len(pending):
            raise RosterReviewError("N256 published packet count mismatch")
        for packet, record in zip(pending, records):
            actual = (
                packet.source,
                packet.generation,
                packet.dimension,
                packet.target,
                packet.origin,
                _fraction_pair(packet.start),
                _fraction_pair(packet.end),
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
                raise RosterReviewError("N256 published packet roster mismatch")
        count = (
            10 * candidate.INTERIOR
            + 50
            + sum(packet.dimension**2 + 6 * packet.dimension for packet in pending)
        )
        if count != capsule["coordinate_count"]:
            raise RosterReviewError("N256 capsule coordinate count mismatch")
        conceptual += count
    if conceptual != summary["fp64_coordinate_denominator"]:
        raise RosterReviewError("N256 conceptual denominator mismatch")

    expected_events = [record for record in events if record["kind"] == "transition"]
    if len(expected_events) != len(segment_rows):
        raise RosterReviewError("N256 event count mismatch")
    for segment, event in zip(segment_rows, expected_events):
        if (
            segment["lane"],
            segment["left_fraction"],
            segment["right_fraction"],
            segment["releasing"],
            segment["pending_after"],
        ) != (
            event["lane"],
            event["left"]["fraction"],
            event["right"]["fraction"],
            event["releasing"],
            event["pending_after"],
        ):
            raise RosterReviewError("N256 transition roster mismatch")

    operators = {
        packet.operator.identity: packet.operator for packet in (*initial, *emitted)
    }
    emitted_uses = Counter(packet.operator.identity for packet in emitted)
    initial_uses = Counter(packet.operator.identity for packet in initial)
    operator_rows = [
        _csr_record(
            operator,
            emitted_uses[identity],
            initial_uses[identity],
        )
        for identity, operator in sorted(operators.items())
    ]
    return operator_rows, segment_rows


def review_operator_segment_rosters(
    metadata_path, state_path, phase_path, npz_b64_path, roster_dir
):
    """Validate and certify the exact canonical roster identities."""

    operators, segments = reconstruct_rosters(
        metadata_path, state_path, phase_path, npz_b64_path, roster_dir
    )
    operator_sha256 = _digest(_canonical(operators))
    segment_sha256 = _digest(_canonical(segments))
    if operator_sha256 != EXPECTED_OPERATOR_ROSTER_SHA256:
        raise RosterReviewError("operator roster SHA-256 mismatch")
    if segment_sha256 != EXPECTED_SEGMENT_ROSTER_SHA256:
        raise RosterReviewError("segment roster SHA-256 mismatch")
    return OperatorSegmentCertificate(
        engineering_source_sha256=ENGINEERING_SOURCE_SHA256,
        primitive_source_sha256=PRIMITIVE_SOURCE_SHA256,
        input_bundle_sha256=INPUT_BUNDLE_SHA256,
        published_roster_identity=PUBLISHED_ROSTER_IDENTITY,
        operator_roster_sha256=operator_sha256,
        segment_roster_sha256=segment_sha256,
        unique_operators=len(operators),
        operator_nnz=sum(record["nnz"] for record in operators),
        unique_sparse_operator_bytes=sum(record["csr_bytes"] for record in operators),
        transition_segments=len(segments),
        emitted_templates=sum(len(record["emitted"]) for record in segments),
        initial_templates=sum(
            record["initial_template_uses"] for record in operators
        ),
    )
