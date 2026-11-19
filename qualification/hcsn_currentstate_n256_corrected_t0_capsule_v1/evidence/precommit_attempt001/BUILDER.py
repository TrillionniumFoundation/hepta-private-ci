"""Build one corrected-lineage authentic N256 t=0 capsule."""

import argparse
import hashlib
import json
import struct
from fractions import Fraction
from pathlib import Path


IDENTITY = "hcsn-n256-corrected-t0-capsule-contract-20261117-c06d-001"
EXECUTION_KEY = "hcsn-n256-corrected-t0-capsule-20261117-c06d-001"
CAPSULE_IDENTITY = "838859bc4f9a3d52538287a71845be51e03e1707f50abb3673ce79867d2fcee2"
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
SERIALIZER_SHA256 = "3107fb296043de8f3e3c78e13aa940aea38aa64c16dfe68d342d2adb0c7aa97a"
CANDIDATE_SHA256 = "49616d4fcff9685a6cfcbee00ff45a2fd9ab4eb9c6ce04e62c02f927752d50db"
CANDIDATE_ADMISSION_SHA256 = "d3ec236043f1563a6c05d0843a1b431ec1288da70047a3dc451031c25f67f61b"
CANDIDATE_REQUEST_SHA256 = "9db32bf0c81051a8ba719a0fd54ece202e312ae84ab5ede43d181e3d86f410fe"
ORACLE_ADAPTER_SHA256 = "311eeeb69ba5002171d3aa765610bc9caea1cb2942309ba6e67543297cb74084"
ORACLE_ADMISSION_SHA256 = "7f3c24118a3504d393d59b31576e8a140c206a154dfaecf4c5ec0aa327feb90c"
ORACLE_REQUEST_SHA256 = "b99b8621b4ea6c4083815d736d07de96ef056251104224044d780c2135f7cdcc"
STATE_SHA256 = "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c"
PHASE_SHA256 = "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548"
NPZ_B64_SHA256 = "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb"
DECODED_NPZ_SHA256 = "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8"
MAX_CAPSULE_BYTES = 8 * 1024 * 1024

RELATIVE = {
    "phase": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json",
    "candidate": "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py",
    "candidate_admission": "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/admission.py",
    "candidate_request": "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/REQUEST.json",
    "oracle": "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/adapter.py",
    "oracle_admission": "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/admission.py",
    "oracle_request": "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/REQUEST.json",
    "serializer": "qualification/hcsn_currentstate_n256_canonical_serializer_intent/canonical_serializer.py",
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def source_identity(bundle, kind, start, end):
    return _sha(
        _canonical(
            {
                "bundle": bundle,
                "kind": kind,
                "start": [start.numerator, start.denominator],
                "end": [end.numerator, end.denominator],
                "target": 1,
                "origin": 0,
                "parents": [],
            }
        )
    )


def state_blocks(active_values, content_values):
    if len(active_values) != 257 or len(content_values) != 257 * 4:
        raise ValueError("authentic N256 state shape")
    interior = range(1, 256)
    channels = [active_values] + [content_values[index::4] for index in range(4)]
    active = []
    for channel in channels:
        active.extend(channel[index] for index in interior)
        active.extend(0.0 for _ in interior)
    upper = []
    for channel in channels:
        upper.extend((channel[-1], 0.0, 0.0))
    return {
        "active": ((5, 2, 255), tuple(active)),
        "discounted_hit": ((5, 2), (0.0,) * 10),
        "lower_hit": ((5, 2), (0.0,) * 10),
        "occupation": ((5, 3), (0.0,) * 15),
        "upper": ((5, 3), tuple(upper)),
    }


def expected_bindings():
    return {
        "candidate_admission_sha256": CANDIDATE_ADMISSION_SHA256,
        "candidate_request_sha256": CANDIDATE_REQUEST_SHA256,
        "candidate_source_sha256": CANDIDATE_SHA256,
        "canonical_serializer_sha256": SERIALIZER_SHA256,
        "decoded_npz_sha256": DECODED_NPZ_SHA256,
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "npz_b64_original_sha256": NPZ_B64_SHA256,
        "oracle_adapter_sha256": ORACLE_ADAPTER_SHA256,
        "oracle_admission_sha256": ORACLE_ADMISSION_SHA256,
        "oracle_request_sha256": ORACLE_REQUEST_SHA256,
        "phase_original_sha256": PHASE_SHA256,
        "roster_identity": ROSTER_IDENTITY,
        "state_original_sha256": STATE_SHA256,
    }


def _verify_inherited(root):
    expected = {
        "candidate": CANDIDATE_SHA256,
        "candidate_admission": CANDIDATE_ADMISSION_SHA256,
        "candidate_request": CANDIDATE_REQUEST_SHA256,
        "oracle": ORACLE_ADAPTER_SHA256,
        "oracle_admission": ORACLE_ADMISSION_SHA256,
        "oracle_request": ORACLE_REQUEST_SHA256,
        "serializer": SERIALIZER_SHA256,
        "phase": PHASE_SHA256,
    }
    observed = {name: _sha((root / RELATIVE[name]).read_bytes()) for name in expected}
    if observed != expected:
        raise ValueError("corrected-lineage inherited source binding")


def build(root, output):
    root = Path(root)
    _verify_inherited(root)
    from qualification.hcsn_currentstate_n256_canonical_serializer_intent import (
        canonical_serializer as serializer,
    )
    from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent import (
        adapter as oracle_adapter,
    )
    from qualification.hcsn_currentstate_n256_sparse_dynamic_v2_intent import (
        sparse_dynamic as candidate,
    )

    oracle = oracle_adapter.load_authentic_input(root)
    phase = json.loads((root / RELATIVE["phase"]).read_text())
    if len(phase.get("packets", ())) != 8 or len(oracle.phase_packets) != 8:
        raise ValueError("authentic phase packet denominator")

    active = struct.unpack("<257d", oracle.active_payload)
    content = struct.unpack("<1028d", oracle.signed_content_payload)
    blocks = []
    for name, (shape, values) in state_blocks(active, content).items():
        blocks.append(
            serializer.Block(name, "<f8", shape, struct.pack(f"<{len(values)}d", *values))
        )

    packets = []
    for raw, adapted in zip(phase["packets"], oracle.phase_packets):
        kind, start, end, oracle_alpha = adapted
        if (kind, start, end) != (raw["identity"], Fraction(raw["start"]), Fraction(raw["end"])):
            raise ValueError("candidate/oracle phase identity mismatch")
        candidate_alpha = candidate._phase_packet_alpha(raw)
        if candidate_alpha != tuple(float(value) for value in oracle_alpha):
            raise ValueError("candidate/oracle phase amplitude mismatch")
        packets.append(
            serializer.Packet(
                identity=source_identity(INPUT_BUNDLE_SHA256, kind, start, end),
                generation=1,
                origin=0,
                target=1,
                start=str(start),
                end=str(end),
                alpha=struct.pack("<5d", *candidate_alpha),
                operator=struct.pack("<2d", 0.0, 1.0),
            )
        )

    envelope = serializer.Envelope(
        metadata={
            "identity": IDENTITY,
            "execution_key": EXECUTION_KEY,
            "capsule_identity": CAPSULE_IDENTITY,
            "lane": "warm",
            "lane_order": 0,
            "time": "0",
            "coordinate_count": 2656,
            "historical_negative_and_unknown_preserved": True,
            "largegrid_qualification": False,
            "production_adoption": False,
            "all_closed": False,
            "bindings": expected_bindings(),
        },
        blocks=tuple(blocks),
        packets=tuple(sorted(packets, key=lambda packet: packet.identity)),
    )
    capsule_sha256 = serializer.publish_atomic(output, envelope)
    payload = output.read_bytes()
    decoded = serializer.decode(payload, MAX_CAPSULE_BYTES)
    expected_decoded = serializer.Envelope(
        {**envelope.metadata, "schema": serializer.SCHEMA}, envelope.blocks, envelope.packets
    )
    if decoded != expected_decoded:
        raise ValueError("canonical decode envelope mismatch")
    if len(payload) > MAX_CAPSULE_BYTES:
        raise ValueError("capsule allocation bound")
    return {
        "identity": IDENTITY,
        "execution_key": EXECUTION_KEY,
        "capsule_sha256": capsule_sha256,
        "capsule_bytes": len(payload),
        "packet_ids": [packet.identity for packet in envelope.packets],
        "counts": {
            "candidate_phase_parser_calls": 8,
            "canonical_decode_calls": 1,
            "canonical_encode_invocations": 2,
            "dynamic_runs": 0,
            "independent_parser_calls": 0,
            "matrix_exponential_actions": 0,
            "optimizer_steps": 0,
            "oracle_adapter_calls": 1,
            "provider_calls": 0,
            "publish_atomic_calls": 1,
            "torch_calls": 0,
        },
        "largegrid_qualification": False,
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    result = build(arguments.root, arguments.output)
    arguments.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
