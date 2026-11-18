"""Zero-numerical-work inspection for the corrected N256 first-step contract."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


FORBIDDEN_IMPORTS = {"jax", "numpy", "scipy", "tensorflow", "torch"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(package_root, repository_root):
    package_root = Path(package_root)
    repository_root = Path(repository_root)
    request_path = package_root / "REQUEST.json"
    contract_path = package_root / "contract.py"
    request = json.loads(request_path.read_text())
    tree = ast.parse(contract_path.read_text(), filename=str(contract_path))
    compile(tree, str(contract_path), "exec")
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    if imports & FORBIDDEN_IMPORTS:
        raise ValueError("source-only contract imports numerical dependencies")
    if request["numerical_execution_allowed"] is not False:
        raise ValueError("source-only contract enables numerical execution")
    for group in ("future_sources", "required_future_admission"):
        if set(request[group].values()) != {None}:
            raise ValueError(f"{group} is unexpectedly populated")
    bound_paths = {
        "corrected_candidate_source_sha256": "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py",
        "oracle_adapter_source_sha256": "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/adapter.py",
        "canonical_serializer_source_sha256": "qualification/hcsn_currentstate_n256_canonical_serializer_intent/canonical_serializer.py",
        "roster_capsules_sha256": "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/CAPSULES.json",
        "roster_spans_sha256": "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/COORDINATE_SPANS.jsonl",
        "corrected_t0_capsule_sha256": "qualification/hcsn_currentstate_n256_corrected_t0_capsule_v1/evidence/attempt002_hosted/capsule.bin",
        "corrected_t0_receipt_sha256": "qualification/hcsn_currentstate_n256_corrected_t0_capsule_v1/evidence/attempt002_hosted/RECEIPT.json",
        "corrected_t0_artifact_sha256": "qualification/hcsn_currentstate_n256_corrected_t0_capsule_v1/evidence/attempt002_hosted/artifact.zip",
    }
    for field, relative in bound_paths.items():
        if request["bindings"][field] != _sha(repository_root / relative):
            raise ValueError(f"binding mismatch: {field}")
    serializer_tree = ast.parse(
        (repository_root / bound_paths["canonical_serializer_source_sha256"]).read_text()
    )
    packet_classes = [
        node
        for node in serializer_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Packet"
    ]
    if len(packet_classes) != 1:
        raise ValueError("inherited serializer packet schema")
    packet_fields = {
        node.target.id
        for node in packet_classes[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    if packet_fields != {
        "identity",
        "generation",
        "origin",
        "target",
        "start",
        "end",
        "alpha",
        "operator",
    }:
        raise ValueError("inherited serializer schema changed; re-review required")
    if request["serializer_requirements"] != {
        "state_coordinates": 2600,
        "packet_alpha_coordinates": 1320,
        "packet_generator_coordinates": 65544,
        "packet_output_coordinates": 264,
        "packet_coordinates": 67128,
        "inherited_serializer_fullstate_ready": False,
        "future_serializer_revision_required": True,
    }:
        raise ValueError("future full-state serializer requirement mismatch")
    capsules = json.loads((repository_root / bound_paths["roster_capsules_sha256"]).read_text())
    matches = [item for item in capsules if item["capsule_identity"] == request["target"]["capsule_identity"]]
    if matches != [{
        "lane": "warm",
        "lane_order": 1,
        "time": {"fraction": [1, 1000], "fp64_le": "fca9f1d24d62503f"},
        "channels": 5,
        "packets": 9,
        "coordinate_count": 69728,
        "capsule_identity": request["target"]["capsule_identity"],
    }]:
        raise ValueError("authentic warm-1 roster target mismatch")
    if request["historical_resource_red_6295_unchanged"] is not True:
        raise ValueError("#6295 resource RED is not preserved")
    return {
        "schema": "hcsn-n256-corrected-firststep-contract-static-audit-v1",
        "identity": request["identity"],
        "request_sha256": _sha(request_path),
        "contract_sha256": _sha(contract_path),
        "bound_originals": len(bound_paths),
        "target_coordinates": 69728,
        "inherited_serializer_packet_fields": sorted(packet_fields),
        "inherited_serializer_fullstate_ready": False,
        "missing_serialized_output_coordinates": 264,
        "future_serializer_revision_required": True,
        "authentic_firststep_capsules": 0,
        "authentic_firststep_coordinates": 0,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "serializer_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "full_roster_qualification": False,
        "largegrid_qualification": False,
        "all_closed": False,
        "status": "PASS_SOURCE_ONLY_FIRSTSTEP_CONTRACT_HOLD",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--repository-root", required=True)
    arguments = parser.parse_args()
    print(json.dumps(inspect(arguments.package_root, arguments.repository_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
