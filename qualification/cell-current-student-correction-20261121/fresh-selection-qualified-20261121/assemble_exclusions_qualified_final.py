"""Freeze retained old-only exclusions from the actual qualified parser; no new source access."""
import ast
import hashlib
import json
from pathlib import Path
import re


BASE = Path("/tmp/hepta-e16-ac5459-recovered-20261121")
PREP = BASE / "e2_training_candidate/fresh_deployment_preparation"
OUT = BASE / "e2_training_candidate/fresh_selection_preparation"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(relative, expected):
    path = BASE / relative
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    return json.loads(raw), {"path": str(path), "bytes": len(raw), "sha256": expected}


def retained_hashes(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from retained_hashes(item, path + "." + key if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from retained_hashes(item, path + "[" + str(index) + "]")
    elif isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value):
        yield {"field": path, "sha256": value}


def literal(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [literal(value) for value in node.elts]
    if isinstance(node, ast.Dict):
        return {literal(key): literal(value) for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Pow, ast.Mult)):
        left, right = literal(node.left), literal(node.right)
        assert type(left) is int and type(right) is int
        return left ** right if isinstance(node.op, ast.Pow) else left * right
    raise ValueError("nonliteral declared protocol constant")


def main():
    specs = [
        ("DEDUP", "e2_training_candidate/fresh_deployment_preparation/old_metadata/DEDUP_INVENTORY.json", "aa522307a3d06aba4ac355846cba05417c0a9dc06a88b834d618b414247c1d9a"),
        ("A_B3", "e2_training_candidate/fresh_deployment_preparation/old_metadata/A_B3_DEDUP.json", "32b4ecfae3c1000bb15487468bc9ceb53ddf9d4649167ef12f12905df775ce0e"),
        ("OLD_FUTURE_TASKS", "e2_training_candidate/fresh_deployment_preparation/OLD_FUTURE_EXCLUSION_CONTRIBUTION.json", "92b3a8f5166a2f73897c8012b6b64dad2c8d93f28488ec3486fc9e67ab6ad232"),
        ("OLD_FUTURE_SCAN", "e2_training_candidate/fresh_deployment_preparation/OLD_FUTURE_SCAN_EXCLUSION_CONTRIBUTION.json", "b5d95e87b4b86671d698462bd8bbb9f739fe767f2184b1c27d094a8626b79d7b"),
        ("E5_METADATA_V2", "root/e2_fresh_exclusions/E5_METADATA_OWNER_EXCLUSION_CONTRIBUTION_V2.json", "3445b888139af5af6baacecd21cacb7c88af8b683dd096205de57428996e091f"),
        ("E5_QUALIFIED_AST", "e5_old_material_exclusion_20261121/qualified_replay_evidence_20261121/originals/EXCLUSION_E5.json", "3e584380318eb001dd85aa5c05cf4d473f9d079216ffe6c070a9859a476ca197"),
        ("E5_QUALIFIED_FINGERPRINTS", "e5_old_material_exclusion_20261121/qualified_replay_evidence_20261121/originals/FINGERPRINT_SETS.json", "e1d29371c955e03b09e977f57cf7f429f4340c45955ba0663cab362a2b9852ab"),
    ]
    values, sources = {}, {}
    for name, path, expected in specs:
        values[name], sources[name] = read(path, expected)
    qualified = values["E5_QUALIFIED_AST"]
    assert qualified["python"]["version"] == "3.12.3"
    assert qualified["python"]["qualified_fresh_binary_identity_verified_by_this_extractor"] is True
    assert qualified["python"]["qualified_actual_interpreter_identity"]["sha256"] == "e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f"
    assert qualified["fingerprint_sets"] == values["E5_QUALIFIED_FINGERPRINTS"]
    diff, sources["E5_PARSER_VERSION_DIFF"] = read("e5_old_material_exclusion_20261121/qualified_replay_evidence_20261121/FINGERPRINT_DIFF_LOCAL31214_VS_ACTUAL3123.json", "5e8ec7e8d01ba40a6364461070fb1442bd48457dce2b0e511aad55953d89bfb8")
    assert diff["actual_qualified_full_sha256"] == sources["E5_QUALIFIED_FINGERPRINTS"]["sha256"]
    assert set(diff["changed_sets"]) == {"function_ast_sha256", "source_module_ast_sha256"}
    assert all(len(row["actual_only"]) == len(row["old_only"]) == 2 for row in diff["changed_sets"].values())
    assert qualified["coverage_complete_for_declared_python_inputs"] is False
    projects, provenance, hashes, hash_sets = set(), [], set(), {}

    def repository(value, source, field, scope):
        assert isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value)
        projects.add(value.casefold())
        provenance.append({"repository": value, "owner": value.split("/")[0].casefold(),
                           "source": source, "field": field, "scope": scope})

    for name in ("DEDUP", "A_B3"):
        for index, value in enumerate(values[name]["repositories"]):
            repository(value["canonical_repository"], name, f"repositories[{index}].canonical_repository", "published_old_panel")
        rows = list(retained_hashes(values[name]))
        hash_sets[name] = {"kind": "typed_original_fields_including_conservative_receipt_hashes", "rows": rows}
        hashes.update(row["sha256"] for row in rows)
    for name, key in (("OLD_FUTURE_TASKS", "canonical_projects"), ("OLD_FUTURE_SCAN", "repositories"), ("E5_METADATA_V2", "repositories")):
        for index, value in enumerate(values[name][key]):
            repository(value, name, f"{key}[{index}]", values[name].get("scope", "retained_old_source_provenance_in_bound_contribution"))
        if "content_sha256s" in values[name]:
            hashes.update(values[name]["content_sha256s"])
            hash_sets[name] = {"kind": "bound_contribution_content_sha256s", "count": len(values[name]["content_sha256s"])}
    e5 = values["E5_QUALIFIED_FINGERPRINTS"]
    for index, value in enumerate(e5["projects"]):
        repository(value, "E5_QUALIFIED_FINGERPRINTS", f"projects[{index}]", "16_original_materials_plus_original_selection_only_exposure")
    for name, values_in_set in e5.items():
        if name.endswith("sha256"):
            assert all(re.fullmatch("[0-9a-f]{64}", value) for value in values_in_set)
            hashes.update(values_in_set)
            hash_sets["E5_QUALIFIED_FINGERPRINTS." + name] = {"kind": "explicit_typed_hash_set", "count": len(values_in_set)}
    owners = sorted({value.split("/")[0] for value in projects})
    assert "jaraco" in owners and "agronholm" in owners
    contract = BASE / "e2_training_candidate/fresh_protocol_static/source_464131/fresh_contract.py"
    assert hashlib.sha256(contract.read_bytes()).hexdigest() == "724f29a89e97293e209f2aad27e3b3b88d8a57a1534c065c3adf6f7b21f2af3f"
    constants = {}
    for node in ast.parse(contract.read_bytes()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"REPOSITORIES", "POLICY", "AS_OF", "COMMIT_ORDER", "CAPS"}:
                constants[name] = literal(node.value)
    admissions = [{"repository": value, "status": "BEFORE_SCAN_REFUSAL" if value.split("/")[0].casefold() in owners else "ELIGIBLE_FOR_ORDERED_SCAN", "actual_content_read": False}
                  for value in constants["REPOSITORIES"]]
    assert [value["repository"] for value in admissions if value["status"] == "BEFORE_SCAN_REFUSAL"] == ["jaraco/inflect", "agronholm/exceptiongroup"]
    excluded = {"schema": "hepta.current-student-fresh-excluded-inventory.v1",
                "status": "FROZEN_ACTUAL_QUALIFIED_3_12_3_PENDING_SEPARATE_GIT_PUBLICATION",
                "owners": owners, "repositories": sorted(projects), "content_sha256s": sorted(hashes),
                "source_bindings": sources, "repository_provenance": provenance, "hash_set_provenance": hash_sets,
                "derived_AST_python": values["E5_QUALIFIED_AST"]["python"], "derived_AST_algorithm": values["E5_QUALIFIED_AST"]["algorithm"],
                "derived_AST_coverage_complete": values["E5_QUALIFIED_AST"]["coverage_complete_for_declared_python_inputs"],
                "fresh_fixed_pool_admissions": admissions,
                "limitations": ["E5 derived ASTs use the actual recorded CPython 3.12.3 interpreter and unchanged default ast.dump algorithm. The earlier 3.12.14 draft remains retained separately; two function and two module hashes differ.",
                                "One retained loguru t_string.py source does not parse in the actual 3.12.3 interpreter. Its raw SHA and original SyntaxError are retained and coverage remains false.",
                                "Original published hashes retain their own provenance; conservative receipt-binding hashes are not relabelled as function AST hashes.",
                                "Owner and exact SHA/AST exclusions do not prove absence of pretraining contamination or semantic duplicates.",
                                "The fixed eight-source list and all original caps remain unchanged; at most six source owners are currently eligible."],
                "fresh_candidate_content_reads": 0, "model_calls": 0, "native_calls": 0}
    path = OUT / "EXCLUDED_INVENTORY.json"
    with path.open("xb") as stream:
        stream.write(canonical(excluded) + b"\n")
    weights_raw = (OUT / "WEIGHTS_FROZEN.json").read_bytes()
    assert hashlib.sha256(weights_raw).hexdigest() == "c7ac446407e45c81fc00f51748d7aaaa29e9a8f1f290a6eef146c1da9c41ee32"
    weights = json.loads(weights_raw)
    selection = {"schema": "hepta.current-student-fresh-selection.v1", "weights_digest": digest(weights),
                 "excluded_inventory_digest": digest(excluded),
                 "repositories": constants["REPOSITORIES"], "caps": constants["CAPS"], "as_of": constants["AS_OF"],
                 "commit_order": constants["COMMIT_ORDER"], "request_policy": constants["POLICY"],
                 "owner_root": "/home/qian-qi/work/e2-fresh-current-student-20261121-ac5459",
                 "automatic_retry": False, "old_raw_policy_comparable": False,
                 "preparation_status": "FROZEN_PENDING_SEPARATE_GIT_PUBLICATION"}
    target = OUT / "SELECTION.json"
    with target.open("xb") as stream:
        stream.write(canonical(selection) + b"\n")
    print(json.dumps({"frozen_excluded": {"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                      "selection_ready_for_publication": {"path": str(target), "bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()},
                      "owners": len(owners), "repositories": len(projects), "unique64hex": len(hashes), "admissions": admissions}, sort_keys=True))


if __name__ == "__main__":
    main()
