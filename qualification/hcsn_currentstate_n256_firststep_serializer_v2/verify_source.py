"""Zero-N256-work verifier for the packet-output serializer revision."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
REPOSITORY = ROOT.parents[1]
FORBIDDEN_IMPORTS = {"jax", "numpy", "scipy", "tensorflow", "torch"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    development_red = json.loads((ROOT / "DEVELOPMENT_RED.json").read_text())
    source = ROOT / "serializer.py"
    tree = ast.parse(source.read_text(), filename=str(source))
    compile(tree, str(source), "exec")
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    if imports & FORBIDDEN_IMPORTS:
        raise ValueError("serializer source imports numerical dependencies")
    packet = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Packet")
    fields = {
        node.target.id
        for node in packet.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    if fields != {"identity", "generation", "origin", "target", "start", "end", "alpha", "generator", "output"}:
        raise ValueError("serializer v2 packet fields mismatch")
    if request["bindings"] != {
        "parent_contract_sha256": digest(REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_contract/contract.py"),
        "inherited_v1_serializer_sha256": digest(REPOSITORY / "qualification/hcsn_currentstate_n256_canonical_serializer_intent/canonical_serializer.py"),
        "serializer_v2_source_sha256": digest(source),
    }:
        raise ValueError("serializer source binding mismatch")
    if request["target"] != {
        "lane": "warm",
        "lane_order": 1,
        "time_fraction": [1, 1000],
        "capsule_identity": "af3119de18a4f2f9049fd4f33c2331448237cb1c90810f6cdf2f2bedaa5bf7c1",
        "state_coordinates": 2600,
        "packet_alpha_coordinates": 1320,
        "packet_generator_coordinates": 65544,
        "packet_output_coordinates": 264,
        "packet_coordinates": 67128,
        "coordinate_denominator": 69728,
    }:
        raise ValueError("authentic first-step target mismatch")
    if freeze["serializer_v2_source_sha256"] != digest(source):
        raise ValueError("source freeze serializer mismatch")
    if freeze["request_sha256"] != digest(ROOT / "REQUEST.json"):
        raise ValueError("source freeze request mismatch")
    if freeze["tests_sha256"] != digest(ROOT / "test_serializer.py"):
        raise ValueError("source freeze tests mismatch")
    if development_red["preserved"] is not True or development_red["n256_serializer_calls"] != 0:
        raise ValueError("development RED is not preserved")
    if set(request["future_sources"].values()) != {None} or set(request["required_future_admission"].values()) != {None}:
        raise ValueError("future source or admission unexpectedly populated")
    exact_zero = (
        "n256_serializer_calls",
        "dynamic_steps",
        "matrix_exponential_actions",
        "torch_calls",
        "optimizer_steps",
    )
    if any(request[field] != 0 for field in exact_zero) or request["n256_numerical_execution_allowed"] is not False:
        raise ValueError("source revision authorizes or claims N256 work")
    if any(request[field] is not False for field in ("full_roster_qualification", "largegrid_qualification", "production_adoption", "all_closed")):
        raise ValueError("source revision grants qualification")
    print(json.dumps({
        "status": "PASS_SMALL_STDLIB_OUTPUT_SERIALIZER_SOURCE_HOLD_N256",
        "identity": request["identity"],
        "packet_fields": sorted(fields),
        "packet_output_coordinates_required": 264,
        "n256_serializer_calls": 0,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "all_closed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
