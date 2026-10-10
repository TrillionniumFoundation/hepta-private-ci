"""Convert scoped discovery and retained owner evidence into reviewable records.

The host owns consent authentication, revocation and evidence collection. This
pure conversion cannot grant them. Incomplete selected-unit coverage survives in
the bundle, and the proposal can request only the `proposed` lifecycle state.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re

from ..discovery import DiscoveryCandidate
from ..discovery.parsers import valid_unit_name


EVIDENCE_FIELDS = (
    "filesystemScope",
    "identityMap",
    "networkSurface",
    "secretReferences",
    "capabilityBoundary",
    "adapterSource",
    "contractSet",
    "migrationPlan",
    "qualificationPlan",
    "rollbackPoint",
)
MAX_EVIDENCE_BYTES = 262_144
IDENTITY_DOMAIN = b"hepta.assimilation.manifest-identity.v1\0"


class ProposalError(ValueError):
    """Stable conversion failure; no partial proposal is returned."""


@dataclass(frozen=True)
class AssimilationProposalBundle:
    payload: bytes
    sha256: str


def _encode(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unique_members(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ProposalError("duplicate_discovery_field")
        value[key] = item
    return value


def build_assimilation_proposal(
    candidate: DiscoveryCandidate,
    *,
    system_id: str,
    proposal_id: str,
    objective_digest: str,
    owner_identity: str,
    observed_at: str,
    evidence: dict[str, bytes],
) -> AssimilationProposalBundle:
    """Build a proposed sensor-bus adapter from exact discovery/evidence bytes.

    Evidence values are retained owner-source artifacts, not caller-supplied
    checksums or claims of qualification. The host must store those bytes under
    their returned digests before publishing the bundle. A checksum alone does
    not authenticate an owner or make a partial discovery inventory complete.
    """
    for value in (system_id, proposal_id):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ProposalError("invalid_record_id")
    if (
        not isinstance(objective_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", objective_digest)
        or objective_digest == "0" * 64
    ):
        raise ProposalError("invalid_objective")
    if (
        not isinstance(owner_identity, str)
        or not owner_identity
        or len(owner_identity.encode()) > 256
    ):
        raise ProposalError("invalid_owner")
    if not isinstance(observed_at, str) or len(observed_at) > 64:
        raise ProposalError("invalid_observation_time")
    try:
        timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, AttributeError):
        raise ProposalError("invalid_observation_time") from None
    if not isinstance(evidence, dict) or set(evidence) != set(EVIDENCE_FIELDS):
        raise ProposalError("incomplete_owner_evidence")
    if any(
        not isinstance(value, bytes) or not 0 < len(value) <= MAX_EVIDENCE_BYTES
        for value in evidence.values()
    ):
        raise ProposalError("invalid_evidence_bytes")
    if (
        not isinstance(candidate.payload, bytes)
        or len(candidate.payload) > 8_388_608
        or _digest(candidate.payload) != candidate.sha256
    ):
        raise ProposalError("discovery_digest_mismatch")
    try:
        discovery = json.loads(candidate.payload, object_pairs_hook=_unique_members)
        if _encode(discovery) != candidate.payload:
            raise ProposalError("noncanonical_discovery")
        if set(discovery) != {
            "schema",
            "scope",
            "os",
            "sources",
            "installed_packages",
            "package_records",
            "units",
            "ordering",
            "ordering_blocked",
            "unresolved_dependencies",
            "coverage",
            "drop_ins_resolved",
            "host_snapshot_required",
            "runtime_authority",
            "activation",
        }:
            raise ProposalError("unknown_discovery_fields")
        if (
            discovery["schema"] != "hepta.scoped-discovery-candidate.v1"
            or discovery["coverage"] != "selected_metadata_only"
            or discovery["runtime_authority"] is not False
            or discovery["activation"] is not False
            or discovery["os"]["id"] != "debian"
        ):
            raise ProposalError("unsupported_discovery")
        scope = discovery["scope"]
        elapsed = timestamp - datetime(1970, 1, 1, tzinfo=timezone.utc)
        observed_ns = (
            elapsed.days * 86400 + elapsed.seconds
        ) * 1_000_000_000 + elapsed.microseconds * 1000
        if not 0 <= observed_ns < scope["expires_unix_ns"]:
            raise ProposalError("observation_outside_enrollment")
        source_by_path = {
            source["path"]: source["sha256"] for source in discovery["sources"]
        }
        for value in (
            scope["host_digest"],
            scope["enrollment_receipt_digest"],
            *source_by_path.values(),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0" * 64:
                raise ProposalError("invalid_source_digest")
        units = discovery["units"]
        if not 1 <= len(units) <= 64 or len(source_by_path) != len(
            discovery["sources"]
        ):
            raise ProposalError("invalid_discovery_sources")
        unit_paths = {path.rsplit("/", 1)[-1]: path for path in scope["unit_paths"]}
        if len(unit_paths) != len(units) or set(unit_paths) != {
            unit["name"] for unit in units
        }:
            raise ProposalError("unit_scope_mismatch")
        if any(not valid_unit_name(unit["name"]) for unit in units):
            raise ProposalError("invalid_unit_name")
        support = {name: _digest(value) for name, value in evidence.items()}
        manifest_identity = {
            "systemId": system_id,
            "systemClass": "debian_service",
            "hostIdentityDigest": scope["host_digest"],
            "osReleaseDigest": source_by_path[scope["os_release_path"]],
            "packageInventoryDigest": source_by_path["var/lib/dpkg/status"],
            "filesystemScopeDigest": support["filesystemScope"],
            "identityMapDigest": support["identityMap"],
            "networkSurfaceDigest": support["networkSurface"],
            "secretReferenceDigest": support["secretReferences"],
            "observedAt": observed_at,
            "authorizationWitness": scope["enrollment_receipt_digest"],
        }
        # Bind the identity projection before the graph. The graph's back-link
        # must not demand a cryptographic fixed point with serviceGraphDigest.
        identity_digest = _digest(IDENTITY_DOMAIN + _encode(manifest_identity))
        nodes = [
            {
                "nodeId": unit["name"],
                "nodeClass": "service",
                "ownerIdentity": owner_identity,
                "manifestDigest": source_by_path[unit_paths[unit["name"]]],
            }
            for unit in sorted(units, key=lambda unit: unit["name"])
        ]
        edges = []
        external_dependencies = []
        for unit in units:
            for relation in ("after", "before", "requires", "wants"):
                if (
                    not isinstance(unit[relation], list)
                    or len(unit[relation]) > 128
                    or len(set(unit[relation])) != len(unit[relation])
                ):
                    raise ProposalError("invalid_dependency_set")
                for target in unit[relation]:
                    if not valid_unit_name(target):
                        raise ProposalError("invalid_dependency_name")
                    edge = {
                        "sourceNodeId": unit["name"],
                        "targetNodeId": target,
                        "edgeClass": relation,
                    }
                    (edges if target in unit_paths else external_dependencies).append(
                        edge
                    )
        edges.sort(
            key=lambda edge: (
                edge["sourceNodeId"],
                edge["edgeClass"],
                edge["targetNodeId"],
            )
        )
        if len(edges) > 4096 or len(external_dependencies) > 4096:
            raise ProposalError("service_graph_limit")
        if (
            len(_encode(nodes)) > 131_072
            or any(len(_encode(node)) > 1024 for node in nodes)
            or len(_encode(edges)) > 131_072
            or any(len(_encode(edge)) > 768 for edge in edges)
        ):
            raise ProposalError("service_graph_limit")
        graph = {
            "graphId": system_id,
            "systemManifestDigest": identity_digest,
            "nodes": nodes,
            "dependencyEdges": edges,
            "socketEdges": [],
            "dbusEdges": [],
            "stateOwnershipEdges": [],
            "topologicalOrderDigest": _digest(_encode(discovery["ordering"])),
            "cycleDisposition": "explicit_strategy_required"
            if discovery["ordering_blocked"]
            else "acyclic",
        }
        graph_digest = _digest(_encode(graph))
        if len(_encode(graph)) > 524_288:
            raise ProposalError("service_graph_limit")
        manifest = {**manifest_identity, "serviceGraphDigest": graph_digest}
        manifest_digest = _digest(_encode(manifest))
        proposal = {
            "proposalId": proposal_id,
            "systemManifestDigest": manifest_digest,
            "capabilityBoundaryDigest": support["capabilityBoundary"],
            "targetOrganClass": "sensor_bus",
            "adapterSourceDigest": support["adapterSource"],
            "contractSetDigest": support["contractSet"],
            "migrationPlanDigest": support["migrationPlan"],
            "qualificationPlanDigest": support["qualificationPlan"],
            "rollbackPointDigest": support["rollbackPoint"],
            "requestedLifecycleState": "proposed",
        }
        payload = _encode(
            {
                "schema": "hepta.assimilation.review-bundle.v1",
                "objectiveDigest": objective_digest,
                "discoveryDigest": candidate.sha256,
                "manifestIdentityDigest": identity_digest,
                "manifest": manifest,
                "manifestDigest": manifest_digest,
                "serviceGraph": graph,
                "serviceGraphDigest": graph_digest,
                "proposal": proposal,
                "evidenceDigests": support,
                "omissions": [
                    "capability_boundary_not_admitted",
                    "effective_units_not_resolved",
                    "runtime_graph_not_observed",
                    "state_ownership_not_admitted",
                ],
                "externalDependencies": sorted(
                    external_dependencies,
                    key=lambda edge: (
                        edge["sourceNodeId"],
                        edge["edgeClass"],
                        edge["targetNodeId"],
                    ),
                ),
                "admitted": False,
                "activation": False,
                "authorityGranted": False,
            }
        )
        return AssimilationProposalBundle(payload, _digest(payload))
    except ProposalError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ProposalError("malformed_discovery") from None
