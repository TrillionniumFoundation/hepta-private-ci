"""Synthetic on-disk Lane B unit fixtures; never production source evidence."""

from pathlib import Path
import json


def write_lane_b_fixture(root: Path, modules: list[str], operations: dict[str, list[str]]) -> dict:
    """Exercise real loading and anchor checks without coupling unit tests to live registries."""
    source_base = {"commit": "a" * 40, "tree": "b" * 40}
    truth = {
        "schema": "hepta.lane-b-implementation-truth.v3",
        "schemaVersion": 3,
        "laneId": "LANE-B-RUNTIME",
        "sourceBase": source_base,
        "moduleOrder": list(modules),
        "operationCount": sum(len(operations[module]) for module in modules),
        "allowedMappingClasses": ["owner_native"],
        "claimBoundary": {
            "documentationStructureComplete": True,
            "designOperationInventoryComplete": True,
            "nativeSourceMappingComplete": True,
            "repositoryControlledDocumentationGapsClosed": True,
            "repositoryControlledMappingGapsClosed": True,
            "repositoryControlledSourceBoundaryGapsClosed": False,
            "targetDesignImplementationComplete": False,
            "productionConsumerCallsitesComplete": False,
            "productExecutionComplete": False,
            "deploymentQualificationComplete": False,
            "independentAcceptanceComplete": False,
            "externalEffectsComplete": False,
            "hardwareEvidenceComplete": False,
            "futureWindowEfficacyComplete": False,
            "allGapsClosed": False,
        },
        "modules": [],
    }
    for module in modules:
        owner_root = f"fixture-owners/{module}"
        source_path = f"{owner_root}/owner.rs"
        test_path = f"{owner_root}/test_owner.py"
        source = root / source_path
        source.parent.mkdir(parents=True)
        source.write_text("\n".join(f"fn {op}() {{}}" for op in operations[module]), encoding="utf-8")
        (root / test_path).write_text("# Structural unit fixture only.\n", encoding="utf-8")
        map_path = f"docs/modules/{module}/IMPLEMENTATION_MAP.json"
        row = {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "module": module,
            "sourceBase": source_base,
            "resolvedRoots": [owner_root],
            "repositoryControlledGaps": [],
            "externalEvidenceGates": ["Real product evidence is outside this unit fixture."],
            "claimBoundary": {"repositoryControlledSourceBoundaryGapsClosed": False},
            "stateOwnerDisposition": "Synthetic owner used only by structural unit tests.",
            "terminalObserverDisposition": "No product outcome or effect is observed by this fixture.",
            "operations": [],
        }
        for operation in operations[module]:
            row["operations"].append({
                "designOperation": operation,
                "mappingClass": "owner_native",
                "ownerEntrypoint": {
                    "role": "owner_entrypoint",
                    "path": source_path,
                    "symbol": f"fn {operation}(",
                    "buildTarget": "synthetic-unit-fixture",
                },
                "delegatedCallees": [],
                "tests": [{"path": test_path, "command": "python3 -m unittest"}],
                "sourceSemantics": "Synthetic structural fixture, not executable product qualification or authority.",
            })
        target = root / map_path
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(row), encoding="utf-8")
        truth["modules"].append({"module": module, "mapPath": map_path, "operationIds": operations[module]})
        for document in [
            f"docs/modules/{module}/TECHNICAL.md",
            f"qualification/module-execution-dossiers/detail/{module}.md",
        ]:
            path = root / document
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {module}\nSynthetic unit fixture, not product evidence.\n", encoding="utf-8")
    return truth
