"""Strict decoded-JSON types and key sets around the pinned original contract.

This profile checks metadata only. A successful check is not authentication,
execution admission, or evidence that a numerical comparison actually passed.
"""

import hashlib
import json
from pathlib import Path
from types import ModuleType


PROFILE = "hcsn-n256-strict-metadata-20261119-v1"
ORIGINAL = Path(__file__).resolve().parents[1] / "hcsn_currentstate_n256_firststep_contract"
CONTRACT_SHA256 = "0cd86de60d0bac10f5289ec3d07d9a4452f592858e85d889a32c5fe3564e1b72"
REQUEST_SHA256 = "2b68630e633daf9533eea0f40cc1c4934494600124585f1371c3ac604d5a4907"


def _pinned_bytes(name, digest):
    content = (ORIGINAL / name).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"original source identity changed: {name}")
    return content


# Compile the exact checked bytes, without importing any numerical package.
_legacy = ModuleType("_pinned_n256_firststep_contract")
exec(compile(_pinned_bytes("contract.py", CONTRACT_SHA256), str(ORIGINAL / "contract.py"), "exec"), _legacy.__dict__)
_request_bytes = _pinned_bytes("REQUEST.json", REQUEST_SHA256)
ContractError = _legacy.ContractError


def _shape(actual, expected, path):
    if type(actual) is not type(expected):
        raise ContractError(f"exact JSON type mismatch at {path}")
    if type(expected) is dict:
        if actual.keys() != expected.keys():
            raise ContractError(f"exact JSON key set mismatch at {path}")
        for key, value in expected.items():
            _shape(actual[key], value, f"{path}.{key}")
    elif type(expected) is list:
        if len(actual) != len(expected):
            raise ContractError(f"exact JSON list length mismatch at {path}")
        for index, value in enumerate(expected):
            _shape(actual[index], value, f"{path}[{index}]")


def validate_request(request):
    """Accept the original frozen HOLD request, with exact types and bindings."""
    expected = json.loads(_request_bytes)
    _shape(request, expected, "request")
    if request != expected:
        raise ContractError("frozen source request values or bindings changed")
    return _legacy.validate_request(request)


def _receipt_shape():
    return {
        "schema": "hcsn-n256-corrected-firststep-receipt-v1",
        "identity": _legacy.IDENTITY,
        "target": _legacy.expected_target(),
        "coordinate_counts": {
            "state": 2600, "packet": 67128, "total": 69728,
            "compared": 69728, "equal": 69728, "mismatches": 0,
        },
        "packet_count": 9,
        "calls": {
            "candidate_dynamic_steps": 1, "candidate_sparse_exponential_actions": 2,
            "oracle_dynamic_steps": 1, "oracle_dense_exponentials": 2,
            "canonical_decode_calls": 2, "canonical_encode_calls": 2,
            "torch_calls": 0, "optimizer_steps": 0,
        },
        "candidate_oracle_bitwise_equal": True,
        "canonical_roundtrip_bytes_equal": True,
        "canonical_roundtrip_coordinate_rows_equal": True,
        "serialized_packet_output_coordinates": 264,
        "capsule_bytes": 1,
        "historical_negative_and_unknown_preserved": True,
        "full_roster_qualification": False,
        "largegrid_qualification": False,
        "production_adoption": False,
        "all_closed": False,
    }


def validate_future_receipt(receipt):
    """Check the original exact gate, including zero work as integers, not bools."""
    _shape(receipt, _receipt_shape(), "receipt")
    return _legacy.validate_future_receipt(receipt)


def canonical_json(receipt):
    validate_future_receipt(receipt)
    return json.dumps(receipt, allow_nan=False, sort_keys=True, separators=(",", ":"))
