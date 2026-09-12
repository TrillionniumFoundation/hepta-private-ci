#!/usr/bin/env python3
"""Closed-world verifier for Hepta V8 pre-coding implementation readiness."""

import argparse
import hashlib
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAN_ID = "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
PLAN_VERSION = "8.0.0"
OVERLAY_ID = "HEPTA-V8-PRECODING-READINESS"
OVERLAY_VERSION = "8.2.0-readiness"
READINESS_PATH = "docs/readiness/READINESS.json"
PROTOCOL_PATH = "docs/readiness/PROTOCOLS.json"
GAPS_PATH = "docs/readiness/GAPS.json"
STATUS_PATH = "docs/readiness/STATUS.md"
STATUS_MODEL_PATH = "docs/readiness/STATUS_MODEL.json"
README_PATH = "docs/readiness/README.md"
WORKFLOW_PATH = ".github/workflows/hepta-implementation-readiness.yml"
MODULES_PATH = "docs/modules/MODULES.json"
PACKAGES_PATH = "docs/delivery/WORK_PACKAGES.json"
MODULE_DOCS_PATH = "docs/modules/MODULE_DOCS.json"

AUTHORITY_KEYS = [
    "runtimeAuthority",
    "productionCaller",
    "productionWriter",
    "modelInvocation",
    "providerDispatch",
    "toolExecution",
    "networkConnect",
    "externalFilesystemMutation",
    "secretOperation",
    "matrixSend",
    "externalEffect",
    "fleetMutation",
    "canonicalSelection",
    "merge",
    "operatorAcceptance",
    "promotion",
    "release",
]

DOCUMENT_IDS = [
    "RDY-SRC",
    "RDY-OBJ",
    "RDY-NDU",
    "RDY-NEU",
    "RDY-LRN",
    "RDY-SI",
    "RDY-EMB",
    "RDY-ASM",
    "RDY-PAR",
]

PROTOCOL_IDS = [
    "BranchPurposeManifestV1",
    "CanonicalSourceReceiptV1",
    "ParallelLaneEnvelopeV1",
    "IntegrationCheckpointV1",
    "ObjectiveSourceEnvelopeV1",
    "ObjectiveConstraintSetV1",
    "ObjectiveConflictReceiptV1",
    "ObjectiveCompileReceiptV1",
    "UtilityContributionV1",
    "NduIterationReceiptV1",
    "NduConvergenceCertificateV1",
    "NeuronRuntimeConfigV1",
    "NeuronTickInputV1",
    "NeuronTickReceiptV1",
    "EvaluationPlanV1",
    "EvaluatorIndependenceReceiptV1",
    "RetentionSliceReceiptV1",
    "MutationGrammarManifestV1",
    "SandboxExecutionReceiptV1",
    "CandidateLineageV1",
    "SensorCalibrationManifestV1",
    "RealTimeLoopProfileV1",
    "EmergencyStopReceiptV1",
    "ActuatorReconciliationReceiptV1",
    "ExternalSystemManifestV1",
    "ServiceGraphV1",
    "CapabilityBoundaryV1",
    "AssimilationProposalV1",
    "MigrationPlanV1",
    "AssimilationQualificationReceiptV1",
    "RollbackPointV1",
]

LANE_IDS = [
    "LANE-A-FOUNDATION",
    "LANE-B-RUNTIME",
    "LANE-C-MEMORY",
    "LANE-D-OBJECTIVE-VALUE",
    "LANE-E-LEARNING",
    "LANE-F-ADAPTIVE-POLICY",
    "LANE-G-ENGINEERING",
]

TRACK_IDS = [
    "TRACK-1-READ-ONLY-VERTICAL",
    "TRACK-2-ADAPTIVE-SHADOW",
    "TRACK-3-EMBODIMENT-AND-ASSIMILATION",
]

ASSIMILATION_IDS = [
    "assimilation.discovery",
    "assimilation.manifest",
    "assimilation.contract-synthesis",
    "bridge.debian",
    "assimilation.sandbox",
    "assimilation.state-migration",
    "assimilation.provenance",
    "assimilation.qualifier",
    "organ.federation",
]

BYTE_BOUNDED_SCALAR_TYPES = {
    "utf8",
    "git_oid",
    "id128",
    "sha256",
    "timestamp_utc",
}

FIXED_SCALAR_TYPES = {"bool", "i64", "u32", "u64"}
ARRAY_TYPES = {"bounded_array"}
FIXED_POINT_VECTOR_TYPES = {"bounded_fixed_point_vector"}
OBJECT_TYPES = {"bounded_object"}
FIELD_TYPES = (
    BYTE_BOUNDED_SCALAR_TYPES
    | FIXED_SCALAR_TYPES
    | ARRAY_TYPES
    | FIXED_POINT_VECTOR_TYPES
    | OBJECT_TYPES
    | {"enum"}
)
FIELD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


class DuplicateKey(ValueError):
    pass


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise DuplicateKey(key)
        out[key] = value
    return out


def die(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_IMPLEMENTATION_READINESS: " + message)


def need(condition: bool, message: str) -> None:
    if not condition:
        die(message)


def load(rel: str) -> dict[str, Any]:
    try:
        return json.loads(
            (ROOT / rel).read_text(encoding="utf-8"), object_pairs_hook=pairs
        )
    except Exception as exc:
        die(f"{rel}: {exc}")


def false_authority(value: Any, label: str) -> None:
    need(
        isinstance(value, dict) and list(value) == AUTHORITY_KEYS,
        label + " authority key closure/order",
    )
    need(not any(bool(x) for x in value.values()), label + " positive authority")


def validate_schema_node(
    node: Any,
    maximum_encoded_bytes: int,
    label: str,
    *,
    named: bool,
    depth: int = 0,
) -> None:
    """Validate one closed, finite readiness-protocol field schema."""
    need(isinstance(node, dict), label + " schema object")
    need(depth <= 4, label + " schema nesting")
    prefix = ["name", "type", "required"] if named else ["type"]
    if named:
        need(
            isinstance(node.get("name"), str) and FIELD_NAME.fullmatch(node["name"]),
            label + " field name",
        )
        need(isinstance(node.get("required"), bool), label + " required")
    field_type = node.get("type")
    need(field_type in FIELD_TYPES, label + " unknown type")

    if field_type in FIXED_SCALAR_TYPES:
        need(list(node) == prefix, label + " scalar key closure/order")
        return

    need(
        isinstance(node.get("maxBytes"), int)
        and not isinstance(node.get("maxBytes"), bool)
        and 0 < node["maxBytes"] <= maximum_encoded_bytes,
        label + " maxBytes",
    )
    if field_type in BYTE_BOUNDED_SCALAR_TYPES:
        need(list(node) == prefix + ["maxBytes"], label + " scalar key closure/order")
        return

    if field_type == "enum":
        need(
            list(node) == prefix + ["maxBytes", "values"],
            label + " enum key closure/order",
        )
        values = node.get("values")
        need(
            isinstance(values, list)
            and values
            and all(isinstance(value, str) and value for value in values)
            and len(values) == len(set(values)),
            label + " enum values",
        )
        need(
            all(
                len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
                <= node["maxBytes"]
                for value in values
            ),
            label + " enum value bytes",
        )
        return

    if field_type in ARRAY_TYPES:
        need(
            list(node)
            == prefix + ["maxBytes", "minItems", "maxItems", "uniqueItems", "items"],
            label + " array key closure/order",
        )
        need(
            isinstance(node.get("minItems"), int)
            and not isinstance(node.get("minItems"), bool)
            and isinstance(node.get("maxItems"), int)
            and not isinstance(node.get("maxItems"), bool)
            and 0 <= node["minItems"] <= node["maxItems"]
            and 0 < node["maxItems"] <= node["maxBytes"],
            label + " array count bounds",
        )
        need(isinstance(node.get("uniqueItems"), bool), label + " uniqueItems")
        if node["uniqueItems"] and isinstance(node.get("items"), dict):
            item_values = node["items"].get("values")
            if node["items"].get("type") == "enum" and isinstance(item_values, list):
                need(
                    node["maxItems"] <= len(item_values),
                    label + " unique enum item bound",
                )
        validate_schema_node(
            node.get("items"),
            node["maxBytes"],
            label + "[]",
            named=False,
            depth=depth + 1,
        )
        return

    if field_type in FIXED_POINT_VECTOR_TYPES:
        need(
            list(node)
            == prefix + ["maxBytes", "scale", "minItems", "maxItems", "items"],
            label + " fixed-point vector key closure/order",
        )
        need(node.get("scale") in ("Q24", "Q32"), label + " fixed-point scale")
        need(
            isinstance(node.get("minItems"), int)
            and not isinstance(node.get("minItems"), bool)
            and isinstance(node.get("maxItems"), int)
            and not isinstance(node.get("maxItems"), bool)
            and 0 < node["minItems"] <= node["maxItems"] <= 512,
            label + " fixed-point vector count bounds",
        )
        need(node.get("items") == {"type": "i64"}, label + " fixed-point items")
        return

    need(field_type in OBJECT_TYPES, label + " object type")
    need(
        "additionalProperties" in node,
        label + " additionalProperties missing",
    )
    need(
        node["additionalProperties"] is False,
        label + " additionalProperties must be false",
    )
    need(
        list(node)
        == prefix
        + [
            "maxBytes",
            "minProperties",
            "maxProperties",
            "additionalProperties",
            "properties",
        ],
        label + " object key closure/order",
    )
    properties = node.get("properties")
    need(isinstance(properties, list) and properties, label + " object properties")
    need(
        isinstance(node.get("minProperties"), int)
        and not isinstance(node.get("minProperties"), bool)
        and isinstance(node.get("maxProperties"), int)
        and not isinstance(node.get("maxProperties"), bool)
        and 0 <= node["minProperties"] <= node["maxProperties"] == len(properties),
        label + " object property bounds",
    )
    property_names = [prop.get("name") for prop in properties if isinstance(prop, dict)]
    need(
        len(property_names) == len(properties)
        and len(property_names) == len(set(property_names)),
        label + " duplicate object property",
    )
    for prop in properties:
        validate_schema_node(
            prop,
            node["maxBytes"],
            label + "." + str(prop.get("name", "?")),
            named=True,
            depth=depth + 1,
        )
    need(
        node["minProperties"] == sum(bool(prop["required"]) for prop in properties),
        label + " required property count",
    )


def count_schema_nodes(node: Any, field_type: str) -> int:
    """Count recursively declared nodes of one field-schema type."""
    if isinstance(node, dict):
        return int(node.get("type") == field_type) + sum(
            count_schema_nodes(value, field_type) for value in node.values()
        )
    if isinstance(node, list):
        return sum(count_schema_nodes(value, field_type) for value in node)
    return 0


def acyclic(
    nodes: list[str], dependency_map: dict[str, list[str]], label: str
) -> list[str]:
    node_set = set(nodes)
    need(len(node_set) == len(nodes), label + " duplicate nodes")
    indegree = {node: 0 for node in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for node, dependencies in dependency_map.items():
        need(node in node_set, label + " unknown node " + node)
        need(
            len(dependencies) == len(set(dependencies)), label + " duplicate dependency"
        )
        for dependency in dependencies:
            need(
                dependency in node_set and dependency != node,
                label + " invalid dependency " + node + " -> " + dependency,
            )
            indegree[node] += 1
            outgoing[dependency].append(node)
    queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    result: list[str] = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for consumer in sorted(outgoing[node]):
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                queue.append(consumer)
    need(len(result) == len(nodes), label + " cycle")
    return result


def is_under(path: str, root: str) -> bool:
    clean_path = path.rstrip("/")
    clean_root = root.rstrip("/")
    return clean_path == clean_root or clean_path.startswith(clean_root + "/")


def validate_status_model(model: dict[str, Any]) -> None:
    """Validate the one vocabulary shared by readiness and dossier projections."""
    need(
        model.get("schema") == "hepta.qualification-readiness-status.v1"
        and model.get("schemaVersion") == 1,
        "status model identity",
    )
    expected = [
        "specification_closed",
        "implementation_closed",
        "external_evidence_closed",
    ]
    dimensions = model.get("dimensions")
    need(
        isinstance(dimensions, list)
        and [row.get("id") for row in dimensions] == expected,
        "status model dimensions",
    )
    need(model.get("allowedValues") == ["open", "closed"], "status model values")
    need(model.get("ordering") == expected, "status model ordering")
    projections = model.get("projection")
    need(
        isinstance(projections, dict)
        and set(projections)
        == {"readiness_registry", "execution_dossiers", "native_bindings"},
        "status model projections",
    )
    for label, projection in projections.items():
        need(
            all(projection.get(key) in {"open", "closed"} for key in expected),
            label + " status projection",
        )
        if projection["implementation_closed"] == "closed":
            need(projection["specification_closed"] == "closed", label + " implication")
        if projection["external_evidence_closed"] == "closed":
            need(
                projection["implementation_closed"] == "closed",
                label + " evidence implication",
            )


def status_text(
    readiness: dict[str, Any], protocols: dict[str, Any], gaps: dict[str, Any]
) -> str:
    return "\n".join(
        [
            "# Hepta Pre-coding Implementation Readiness Status",
            "",
            "> Generated by `python3 scripts/hepta-readiness.py generate-status`. Do not edit by hand.",
            "",
            f"**Parent plan:** `{PLAN_ID}` v{PLAN_VERSION}",
            f"**Readiness overlay:** `{OVERLAY_ID}` v{OVERLAY_VERSION}",
            "**Canonical qualification status:** `specification_closed=closed`; `implementation_closed=open`; `external_evidence_closed=open`",
            "",
            "Status vocabulary and implication rules: [`STATUS_MODEL.json`](STATUS_MODEL.json).",
            "",
            "## Closed specification surface",
            "",
            f"- Implementation-level specifications: **{len(readiness['documents'])}**",
            f"- Typed readiness protocols: **{len(protocols['protocols'])}**",
            f"- Closed pre-coding documentation gaps: **{len(gaps['gaps'])}**",
            f"- Module coding-entry bindings: **{len(readiness['moduleBindings'])}**",
            f"- Primary implementation lanes: **{len(readiness['implementationLanes'])}**",
            f"- Integration tracks: **{len(readiness['integrationTracks'])}**",
            f"- Authorized-assimilation components: **{len(readiness['assimilationComponents'])}**",
            f"- External capability/evidence gates: **{len(gaps['externalCapabilityGates'])}**",
            "- Positive authority flags: **0**",
            "",
            "The closed surface fixes source identity, objective compilation, system-level NDU integration, neuron execution, causal evaluation, governed self-iteration, embodied timing/safety, authorized external-system assimilation and all-module parallel development semantics.",
            "",
            "The execution-dossier projection uses the same three dimensions. Source code, real models, future-time efficacy, empirical biomimicry, target hardware, external-system owner consent, independent acceptance and production rollout remain separate gates and cannot be satisfied by documentation or repository fixtures.",
            "",
        ]
    )


def validate_markdown_document(
    row: dict[str, Any], protocol_ids: set[str], gap_ids: set[str]
) -> None:
    path = ROOT / row["path"]
    need(path.is_file(), row["id"] + " document missing")
    text = path.read_text(encoding="utf-8")
    words = len(re.findall(r"\b[\w.-]+\b", text))
    need(len(text.encode("utf-8")) >= 5000, row["id"] + " document too small")
    need(words >= 700, row["id"] + " document too short")
    need(
        not re.search(r"\b(?:TODO|TBD|FIXME|XXX)\b", text, re.I),
        row["id"] + " unresolved marker",
    )
    need(
        all(section in text for section in row["requiredSections"]),
        row["id"] + " sections",
    )
    need(
        "## Appendix A. Closed gap and protocol mapping" in text,
        row["id"] + " closure appendix",
    )
    for protocol_id in row["protocols"]:
        need(
            protocol_id in protocol_ids, row["id"] + " unknown protocol " + protocol_id
        )
        need(protocol_id in text, row["id"] + " protocol not cited " + protocol_id)
    for gap_id in row["gapIds"]:
        need(gap_id in gap_ids, row["id"] + " unknown gap " + gap_id)
        need(gap_id in text, row["id"] + " gap not cited " + gap_id)


def verify() -> int:
    readiness = load(READINESS_PATH)
    protocols = load(PROTOCOL_PATH)
    gaps = load(GAPS_PATH)
    status_model = load(STATUS_MODEL_PATH)
    validate_status_model(status_model)
    modules = load(MODULES_PATH)["modules"]
    packages = load(PACKAGES_PATH)["packages"]
    module_docs = load(MODULE_DOCS_PATH)["modules"]

    need(
        readiness.get("schema") == "hepta.implementation-readiness-registry.v1"
        and readiness.get("schemaVersion") == 1,
        "readiness schema",
    )
    need(
        protocols.get("schema") == "hepta.implementation-readiness-protocol-registry.v1"
        and protocols.get("schemaVersion") == 1,
        "protocol schema",
    )
    need(
        gaps.get("schema") == "hepta.implementation-readiness-gap-ledger.v1"
        and gaps.get("schemaVersion") == 1,
        "gap schema",
    )
    for label, value in [
        ("readiness", readiness),
        ("protocols", protocols),
        ("gaps", gaps),
    ]:
        need(
            value.get("planId") == PLAN_ID
            and value.get("planVersion") == PLAN_VERSION
            and value.get("overlayVersion") == OVERLAY_VERSION,
            label + " plan binding",
        )
        false_authority(value.get("authorityFlags"), label)
    need(
        readiness.get("overlayId") == OVERLAY_ID,
        "readiness overlay identity",
    )
    parent = readiness.get("parentSource", {})
    need(
        parent.get("baseCandidateCommit") == "d75a857bff625fb79663eb16544ebc7f74093859"
        and parent.get("baseCandidateTree")
        == "b2528aad39cbd6362e12504adca2140549063c69"
        and parent.get("selectionPolicy")
        == "exact_receipt_required_no_branch_name_authority",
        "parent source identity",
    )
    claims = readiness.get("claimBoundary", {})
    need(claims.get("documentationReady") is True, "documentation readiness")
    for key in [
        "sourceImplementation",
        "runtimeActivation",
        "longitudinalEfficacy",
        "functionalBiomimicry",
        "physicalSafetyQualification",
        "autonomousPropagation",
    ]:
        need(claims.get(key) is False, "claim boundary " + key)

    module_ids = [row["id"] for row in modules]
    module_id_set = set(module_ids)
    need(len(module_ids) == len(module_id_set) == 40, "module closed world")
    package_ids = {row["id"] for row in packages}

    protocol_rows = protocols.get("protocols", [])
    actual_protocol_ids = [row["id"] for row in protocol_rows]
    need(actual_protocol_ids == PROTOCOL_IDS, "protocol closed world/order")
    need(
        protocols.get("defaults")
        == {
            "canonicalEncoding": "canonical_json_utf8",
            "denyUnknownCriticalFields": True,
            "authorityDelta": "none",
        },
        "protocol defaults",
    )
    rules = protocols.get("rules", {})
    need(
        rules.get("registeredModuleOwnerRequired") is True
        and rules.get("boundedFieldsRequired") is True
        and rules.get("semanticDigestRequired") is True
        and rules.get("singleWriterSemanticsPreserved") is True
        and rules.get("modelOutputMayMintAuthority") is False
        and rules.get("documentationDoesNotActivateProtocol") is True,
        "protocol rules",
    )
    owner_projection: dict[str, list[str]] = {mid: [] for mid in module_ids}
    consumer_projection: dict[str, list[str]] = {mid: [] for mid in module_ids}
    registry_bounded_object_schemas = 0
    for row in protocol_rows:
        pid = row["id"]
        need(
            list(row)
            == [
                "id",
                "owner",
                "consumers",
                "canonicalEncoding",
                "denyUnknownCriticalFields",
                "maximumEncodedBytes",
                "fields",
                "invariants",
                "authorityDelta",
            ],
            pid + " key closure/order",
        )
        need(row["owner"] in module_id_set, pid + " owner")
        need(
            row["consumers"]
            and len(row["consumers"]) == len(set(row["consumers"]))
            and set(row["consumers"]) <= module_id_set,
            pid + " consumers",
        )
        need(
            row["canonicalEncoding"] == "canonical_json_utf8"
            and row["denyUnknownCriticalFields"] is True
            and 0 < int(row["maximumEncodedBytes"]) <= 1048576
            and row["authorityDelta"] == "none",
            pid + " bounded protocol posture",
        )
        fields = row["fields"]
        need(
            fields and len(fields) == len({field["name"] for field in fields}),
            pid + " fields",
        )
        for field in fields:
            registry_bounded_object_schemas += count_schema_nodes(
                field, "bounded_object"
            )
            validate_schema_node(
                field,
                row["maximumEncodedBytes"],
                pid + "." + str(field.get("name", "?")),
                named=True,
            )
        need(
            "semantic_digest_stable" in row["invariants"]
            and "authority_delta_none" in row["invariants"],
            pid + " invariants",
        )
        owner_projection[row["owner"]].append(pid)
        for consumer in row["consumers"]:
            consumer_projection[consumer].append(pid)
    need(
        registry_bounded_object_schemas == 46,
        "protocol bounded-object schema count",
    )

    gap_rows = gaps.get("gaps", [])
    gap_ids = [row["id"] for row in gap_rows]
    need(len(gap_ids) == len(set(gap_ids)) == 54, "gap closed world")
    need(
        gaps.get("allDocumentationGapsClosed") is True
        and gaps.get("sourceImplementationClaimed") is False,
        "gap truth posture",
    )
    for row in gap_rows:
        need(
            list(row)
            == [
                "id",
                "family",
                "gap",
                "state",
                "evidence",
                "protocols",
                "boundModules",
            ],
            row["id"] + " key closure/order",
        )
        need(row["state"] == "closed_specification", row["id"] + " state")
        need(row["evidence"], row["id"] + " evidence")
        for evidence_path in row["evidence"]:
            need(
                (ROOT / evidence_path).is_file(),
                row["id"] + " missing evidence " + evidence_path,
            )
        need(set(row["protocols"]) <= set(PROTOCOL_IDS), row["id"] + " protocols")
        need(
            row["boundModules"] and set(row["boundModules"]) <= module_id_set,
            row["id"] + " modules",
        )
    external = gaps.get("externalCapabilityGates", [])
    need(
        len(external) == 9
        and [row["id"] for row in external]
        == [f"RDY-EXT-{number:03d}" for number in range(1, 10)],
        "external gate closed world/order",
    )
    need(
        all(
            row.get("repositoryDocumentationMaySelfCertify") is False
            and str(row.get("state", "")).startswith("requires_")
            for row in external
        ),
        "external gate truth posture",
    )
    semantics = gaps.get("completionSemantics", {})
    need(
        "normative bounded algorithm" in semantics.get("closedSpecificationMeans", "")
        and "source implementation"
        in semantics.get("closedSpecificationDoesNotMean", ""),
        "completion semantics",
    )

    document_rows = readiness.get("documents", [])
    need(
        [row["id"] for row in document_rows] == DOCUMENT_IDS,
        "document closed world/order",
    )
    mapped_gap_ids: list[str] = []
    for row in document_rows:
        need(
            list(row)
            == [
                "id",
                "path",
                "title",
                "boundModules",
                "protocols",
                "gapIds",
                "workPackages",
                "requiredSections",
            ],
            row["id"] + " document key closure/order",
        )
        need(
            row["boundModules"] and set(row["boundModules"]) <= module_id_set,
            row["id"] + " bound modules",
        )
        need(
            set(row["protocols"]) <= set(PROTOCOL_IDS), row["id"] + " protocol bindings"
        )
        need(
            row["gapIds"] and set(row["gapIds"]) <= set(gap_ids),
            row["id"] + " gap bindings",
        )
        need(
            row["workPackages"] and set(row["workPackages"]) <= package_ids,
            row["id"] + " work packages",
        )
        need(row["requiredSections"], row["id"] + " required sections")
        validate_markdown_document(row, set(PROTOCOL_IDS), set(gap_ids))
        mapped_gap_ids.extend(row["gapIds"])
    need(
        len(mapped_gap_ids) == len(set(mapped_gap_ids)) == 54
        and set(mapped_gap_ids) == set(gap_ids),
        "document-to-gap exact projection",
    )

    lane_rows = readiness.get("implementationLanes", [])
    need([row["id"] for row in lane_rows] == LANE_IDS, "lane closed world/order")
    lane_map = {row["id"]: row for row in lane_rows}
    lane_modules: list[str] = []
    dependency_map: dict[str, list[str]] = {}
    for row in lane_rows:
        need(
            list(row)
            == [
                "id",
                "owner",
                "deputy",
                "modules",
                "dependsOn",
                "entryGate",
                "exitGate",
            ],
            row["id"] + " lane key closure/order",
        )
        need(
            row["owner"] and row["deputy"] and row["entryGate"] and row["exitGate"],
            row["id"] + " lane envelope",
        )
        need(
            row["modules"] and set(row["modules"]) <= module_id_set,
            row["id"] + " lane modules",
        )
        lane_modules.extend(row["modules"])
        dependency_map[row["id"]] = row["dependsOn"]
    need(
        len(lane_modules) == len(set(lane_modules)) == 40
        and set(lane_modules) == module_id_set,
        "exact one-lane module coverage",
    )
    lane_order = acyclic(LANE_IDS, dependency_map, "lane graph")

    binding_rows = readiness.get("moduleBindings", [])
    need(
        [row["module"] for row in binding_rows] == module_ids,
        "module binding order/coverage",
    )
    module_doc_map = {row["module"]: row for row in module_docs}
    document_map = {row["id"]: row for row in document_rows}
    for row in binding_rows:
        mid = row["module"]
        need(
            list(row)
            == [
                "module",
                "primaryLane",
                "specifications",
                "ownedReadinessProtocols",
                "consumedReadinessProtocols",
                "codingGate",
            ],
            mid + " binding key closure/order",
        )
        need(mid in lane_map[row["primaryLane"]]["modules"], mid + " primary lane")
        need(
            row["specifications"] and set(row["specifications"]) <= set(DOCUMENT_IDS),
            mid + " specifications",
        )
        expected_owned = sorted(owner_projection[mid])
        expected_consumed = sorted(consumer_projection[mid])
        need(
            sorted(row["ownedReadinessProtocols"]) == expected_owned,
            mid + " owned protocol projection",
        )
        need(
            sorted(row["consumedReadinessProtocols"]) == expected_consumed,
            mid + " consumed protocol projection",
        )
        need(
            row["codingGate"]
            == [
                "current_canonical_source_receipt",
                "frozen_contract_and_readiness_digest",
                "bounded_existing_work_package_envelope",
                "all_mandatory_fixtures_defined",
                "authority_delta_none",
            ],
            mid + " coding gate",
        )
        module_path = ROOT / module_doc_map[mid]["path"]
        text = module_path.read_text(encoding="utf-8")
        need(
            "## 16. V8.2 pre-coding implementation-readiness overlay" in text,
            mid + " section 16",
        )
        need(row["primaryLane"] in text, mid + " lane not cited")
        for document_id in row["specifications"]:
            need(
                document_id in text
                and document_map[document_id]["path"].split("/")[-1] in text,
                mid + " readiness spec not cited " + document_id,
            )
        for protocol_id in expected_owned + expected_consumed:
            need(
                protocol_id in text,
                mid + " readiness protocol not cited " + protocol_id,
            )
        need(
            module_doc_map[mid]["bytes"] == len(text.encode("utf-8"))
            and module_doc_map[mid]["words"] == len(re.findall(r"\b[\w.-]+\b", text))
            and module_doc_map[mid]["sha256"]
            == hashlib.sha256(text.encode("utf-8")).hexdigest(),
            mid + " module index stale",
        )

    track_rows = readiness.get("integrationTracks", [])
    need([row["id"] for row in track_rows] == TRACK_IDS, "track closed world/order")
    for row in track_rows:
        need(
            list(row) == ["id", "participants", "after", "exitGate"],
            row["id"] + " track key closure/order",
        )
        need(
            row["participants"] and set(row["participants"]) <= set(LANE_IDS),
            row["id"] + " participants",
        )
        need(row["after"] and row["exitGate"], row["id"] + " track gates")

    module_roots = {
        row["id"]: [binding["path"].rstrip("/") for binding in row["rootBindings"]]
        for row in modules
    }
    assimilation_rows = readiness.get("assimilationComponents", [])
    need(
        [row["id"] for row in assimilation_rows] == ASSIMILATION_IDS,
        "assimilation closed world/order",
    )
    for row in assimilation_rows:
        need(
            list(row) == ["id", "owners", "function", "targetRoots", "authority"],
            row["id"] + " assimilation key closure/order",
        )
        need(
            row["owners"] and set(row["owners"]) <= module_id_set, row["id"] + " owners"
        )
        need(
            row["function"] and row["targetRoots"] and row["authority"],
            row["id"] + " envelope",
        )
        for target_root in row["targetRoots"]:
            need(
                any(
                    is_under(target_root, declared_root)
                    for owner in row["owners"]
                    for declared_root in module_roots[owner]
                ),
                row["id"] + " target root outside owner roots " + target_root,
            )
    need(
        all("propagat" not in row["authority"].lower() for row in assimilation_rows)
        and any(
            row["authority"] == "explicit_host_enrollment_only"
            for row in assimilation_rows
        ),
        "assimilation non-propagation authority",
    )

    coding_gate = readiness.get("codingEntryGate", {})
    need(
        coding_gate.get("allDocumentationGapsClosed") is True
        and coding_gate.get("moduleCoverageRequired") == 40
        and coding_gate.get("sourceReceiptRequired") is True
        and coding_gate.get("exactSourceAndSyntheticMergeRequired") is True
        and coding_gate.get("deterministicFallbackRequired") is True
        and coding_gate.get("rollbackSpecifiedRequired") is True
        and coding_gate.get("independentDecisionRolesRequired") is True
        and coding_gate.get("positiveAuthorityDeltaAllowed") is False,
        "coding entry gate",
    )
    global_closure = readiness.get("globalClosure", {})
    need(
        global_closure
        == {
            "documentationGapState": "closed",
            "state": "closed",
            "protocolCount": 31,
            "gapCount": 54,
            "externalGateCount": 9,
            "moduleBindingCount": 40,
        },
        "global closure counts",
    )

    readme = (ROOT / README_PATH).read_text(encoding="utf-8")
    need(
        all(
            token in readme
            for token in [
                "READINESS.json",
                "STATUS_MODEL.json",
                "PROTOCOLS.json",
                "GAPS.json",
                "STATUS.md",
                "python3 scripts/hepta-readiness.py verify",
            ]
        ),
        "readiness README discovery/commands",
    )
    for discovery_path in [
        "README.md",
        "docs/DEVELOPMENT.md",
        "docs/modules/README.md",
        "docs/learning/README.md",
        "docs/cns/README.md",
    ]:
        need(
            "docs/readiness/README.md"
            in (ROOT / discovery_path).read_text(encoding="utf-8")
            or "../readiness/README.md"
            in (ROOT / discovery_path).read_text(encoding="utf-8")
            or "../../readiness/README.md"
            in (ROOT / discovery_path).read_text(encoding="utf-8"),
            discovery_path + " readiness discovery link",
        )

    workflow = (ROOT / WORKFLOW_PATH).read_text(encoding="utf-8")
    for token in [
        "source-head:",
        "merge-candidate:",
        "github.event.pull_request.head.sha",
        "github.event.pull_request.base.sha",
        "git merge-tree --write-tree",
        "git commit-tree",
        "persist-credentials: false",
        "python3 scripts/hepta-readiness.py self-test",
        "python3 scripts/hepta-readiness.py generate-status --check",
        "python3 scripts/hepta-readiness.py verify",
        "python3 scripts/hepta-module-docs.py verify",
        "python3 scripts/hepta-algorithm-docs.py verify",
        "python3 scripts/hepta-cns.py verify",
        "python3 scripts/hepta-hnmf.py verify",
        "python3 scripts/hepta-docs.py verify",
        "contents: read",
    ]:
        need(token in workflow, "workflow missing " + token)
    for token in [
        "contents: write",
        "pull-requests: write",
        "git push",
        "update-ref",
        "paths-ignore:",
        "github.event.pull_request.merge_commit_sha",
    ]:
        need(token not in workflow, "workflow mutation/stale identity " + token)

    need(
        (ROOT / STATUS_PATH).read_text(encoding="utf-8")
        == status_text(readiness, protocols, gaps),
        "readiness status stale",
    )

    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_PRECODING_IMPLEMENTATION_READINESS",
                "overlayVersion": OVERLAY_VERSION,
                "specifications": len(document_rows),
                "protocols": len(protocol_rows),
                "registryBoundedObjectSchemas": registry_bounded_object_schemas,
                "documentationGaps": len(gap_rows),
                "moduleBindings": len(binding_rows),
                "implementationLanes": len(lane_rows),
                "laneOrderDigest": hashlib.sha256(
                    "\n".join(lane_order).encode()
                ).hexdigest(),
                "integrationTracks": len(track_rows),
                "assimilationComponents": len(assimilation_rows),
                "externalCapabilityGates": len(external),
                "authorityGranted": False,
                "sourceImplementationClaimed": False,
            },
            sort_keys=True,
        )
    )
    return 0


def generate_status(check: bool) -> int:
    validate_status_model(load(STATUS_MODEL_PATH))
    text = status_text(load(READINESS_PATH), load(PROTOCOL_PATH), load(GAPS_PATH))
    path = ROOT / STATUS_PATH
    if check:
        need(
            path.is_file() and path.read_text(encoding="utf-8") == text,
            "readiness status stale",
        )
        print("PASS_HEPTA_READINESS_STATUS")
    else:
        path.write_text(text, encoding="utf-8")
        print("WROTE docs/readiness/STATUS.md")
    return 0


def self_test() -> int:
    need(
        acyclic(["a", "b", "c"], {"a": [], "b": ["a"], "c": ["b"]}, "fixture")
        == ["a", "b", "c"],
        "acyclic fixture",
    )
    try:
        acyclic(["a", "b"], {"a": ["b"], "b": ["a"]}, "fixture")
        die("cycle accepted")
    except SystemExit as exc:
        if "cycle" not in str(exc):
            raise
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=pairs)
        die("duplicate accepted")
    except DuplicateKey:
        pass

    valid_enum = {
        "name": "mode",
        "type": "enum",
        "required": True,
        "maxBytes": 16,
        "values": ["safe", "stop"],
    }
    valid_array = {
        "name": "entries",
        "type": "bounded_array",
        "required": True,
        "maxBytes": 1024,
        "minItems": 1,
        "maxItems": 8,
        "uniqueItems": True,
        "items": {"type": "sha256", "maxBytes": 64},
    }
    valid_vector = {
        "name": "features",
        "type": "bounded_fixed_point_vector",
        "required": True,
        "maxBytes": 1024,
        "scale": "Q24",
        "minItems": 1,
        "maxItems": 32,
        "items": {"type": "i64"},
    }
    valid_object = {
        "name": "window",
        "type": "bounded_object",
        "required": True,
        "maxBytes": 1024,
        "minProperties": 1,
        "maxProperties": 2,
        "additionalProperties": False,
        "properties": [
            {"name": "windowId", "type": "id128", "required": True, "maxBytes": 128},
            {
                "name": "notAfter",
                "type": "timestamp_utc",
                "required": False,
                "maxBytes": 64,
            },
        ],
    }
    for fixture in [valid_enum, valid_array, valid_vector, valid_object]:
        validate_schema_node(fixture, 1024, "fixture", named=True)

    invalid_schemas = [
        (
            {
                "name": "mode",
                "type": "enum",
                "required": True,
                "values": ["safe", "stop"],
                "maxBytes": 16,
            },
            "enum key closure/order",
        ),
        (
            {
                **valid_enum,
                "values": ["safe", "safe"],
            },
            "enum values",
        ),
        (
            {
                **valid_array,
                "minItems": 9,
            },
            "array count bounds",
        ),
        (
            {
                **valid_array,
                "items": {
                    "type": "enum",
                    "maxBytes": 16,
                    "values": ["safe", "stop"],
                },
            },
            "unique enum item bound",
        ),
        (
            {
                **valid_vector,
                "items": {"type": "u32"},
            },
            "fixed-point items",
        ),
        (
            {
                **valid_object,
                "additionalProperties": True,
            },
            "additionalProperties must be false",
        ),
        (
            {
                key: value
                for key, value in valid_object.items()
                if key != "additionalProperties"
            },
            "additionalProperties missing",
        ),
        (
            {
                **valid_object,
                "properties": [
                    {"name": "same", "type": "u32", "required": True},
                    {"name": "same", "type": "u32", "required": False},
                ],
            },
            "duplicate object property",
        ),
        (
            {
                **valid_object,
                "minProperties": 2,
            },
            "required property count",
        ),
        (
            {
                **valid_array,
                "items": {"type": "utf8", "maxBytes": 2048},
            },
            "maxBytes",
        ),
    ]
    for fixture, expected in invalid_schemas:
        try:
            validate_schema_node(fixture, 1024, "fixture", named=True)
            die("invalid field schema accepted")
        except SystemExit as exc:
            if expected not in str(exc):
                raise
    need(is_under("a/b/c", "a/b") and not is_under("a/bc", "a/b"), "path fixture")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_READINESS_SELF_TEST",
                "cases": [
                    "acyclic",
                    "cycle",
                    "duplicate_key",
                    "path_ownership",
                    "valid_recursive_field_schemas",
                    "schema_key_order",
                    "duplicate_enum_value",
                    "invalid_array_bounds",
                    "invalid_unique_enum_bound",
                    "invalid_fixed_point_items",
                    "duplicate_object_property",
                    "invalid_required_property_count",
                    "nested_byte_bound_escape",
                    "missing_additional_properties_policy",
                    "positive_additional_properties_policy",
                ],
                "authorityGranted": False,
                "boundedObjectFixtures": {
                    "positive": 1,
                    "missingAdditionalProperties": 1,
                    "permissiveAdditionalProperties": 1,
                },
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("self-test")
    status = sub.add_parser("generate-status")
    status.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.command == "verify":
        return verify()
    if args.command == "self-test":
        return self_test()
    return generate_status(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
