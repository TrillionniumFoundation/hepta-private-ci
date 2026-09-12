//! An explicitly versioned binding profile for trusted compiled, stateless organs.
//!
//! The V1 registry does not specify a canonical codec. These bindings are a
//! projection supplied by its trusted producer, not a replacement V1 schema.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::OrganEdge;
use crate::OrganGraphError;
use crate::OrganGraphsV1;
use crate::OrganHostV1;
use crate::OrganRole;
use crate::OrganRuntimeError;
use crate::TrustedReadOnlyOrganV1;

#[path = "organ_wire_codec.rs"]
mod codec;

pub const MAX_COMPILED_BODY_GRAPH_BYTES: usize = 2 * 1024 * 1024;

/// Canonical protocol identity for the registered body snapshot projection.
///
/// The JSON CNS registry owns the semantic `BodyGraphSnapshotV1` protocol.
/// Native code must still present an explicit, versioned admission for the
/// bounded V2 compiled projection below; a payload or source digest alone is
/// never treated as registry admission.
pub const BODY_GRAPH_SNAPSHOT_PROTOCOL_V1: &str = "BodyGraphSnapshotV1";
pub const COMPILED_BODY_GRAPH_PROFILE_V2: &str = "hepta.compiled-body-graph.v2";

fn compiled_body_graph_schema_digest_v2() -> Digest32 {
    Digest32::of_bytes(b"hepta.compiled-body-graph.v2.schema.v1")
}

/// Host-owned snapshot of the protocol registry entry used by native handoff.
/// Construction is intentionally explicit and rejects empty identities. The
/// registry is metadata only: it grants no runtime or effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeHandoffProtocolRegistryV1 {
    protocol_id: StableId,
    profile_id: StableId,
    profile_version: u16,
    schema_digest: Digest32,
}

impl NativeHandoffProtocolRegistryV1 {
    /// The only built-in entry. A production owner may construct a reviewed
    /// registry snapshot with `new` for a future profile/version.
    pub fn canonical() -> Self {
        Self {
            protocol_id: StableId::new(BODY_GRAPH_SNAPSHOT_PROTOCOL_V1)
                .expect("canonical protocol identity is valid"),
            profile_id: StableId::new(COMPILED_BODY_GRAPH_PROFILE_V2)
                .expect("canonical profile identity is valid"),
            profile_version: 2,
            schema_digest: compiled_body_graph_schema_digest_v2(),
        }
    }

    pub fn new(
        protocol_id: StableId,
        profile_id: StableId,
        profile_version: u16,
        schema_digest: Digest32,
    ) -> Result<Self, OrganWireError> {
        if profile_version == 0 || schema_digest.is_zero() {
            return Err(OrganWireError::ProtocolRegistry);
        }
        Ok(Self {
            protocol_id,
            profile_id,
            profile_version,
            schema_digest,
        })
    }

    fn admit(&self, request: &NativeHandoffProtocolAdmissionV1) -> Result<(), OrganWireError> {
        if request.protocol_id != self.protocol_id {
            return Err(OrganWireError::ProtocolRegistry);
        }
        if request.profile_id != self.profile_id || request.profile_version != self.profile_version {
            return Err(OrganWireError::ProtocolVersion);
        }
        if request.schema_digest != self.schema_digest {
            return Err(OrganWireError::ProtocolSchema);
        }
        Ok(())
    }

    pub fn protocol_id(&self) -> &StableId {
        &self.protocol_id
    }

    pub fn profile_id(&self) -> &StableId {
        &self.profile_id
    }

    pub fn profile_version(&self) -> u16 {
        self.profile_version
    }

    pub fn schema_digest(&self) -> Digest32 {
        self.schema_digest
    }
}

/// Caller-supplied, host-independent protocol claim. It is checked against a
/// host-owned registry before any graph decode or handler construction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeHandoffProtocolAdmissionV1 {
    pub protocol_id: StableId,
    pub profile_id: StableId,
    pub profile_version: u16,
    pub schema_digest: Digest32,
}

impl NativeHandoffProtocolAdmissionV1 {
    pub fn canonical() -> Self {
        let registry = NativeHandoffProtocolRegistryV1::canonical();
        Self {
            protocol_id: registry.protocol_id,
            profile_id: registry.profile_id,
            profile_version: registry.profile_version,
            schema_digest: registry.schema_digest,
        }
    }
}

/// Receipt produced only after registry, digest, generation, placement and
/// graph validation all pass. It is an admission observation, not a lease or
/// a production capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeHandoffReceiptV1 {
    pub protocol_id: StableId,
    pub profile_id: StableId,
    pub profile_version: u16,
    pub schema_digest: Digest32,
    pub payload_digest: Digest32,
    pub generation: Generation,
    pub authority: codex_hepta_types::AuthorityPosture,
}

/// The V1 manifest's identity and port projection. The digest binds its complete
/// source manifest (including version, resource and retirement policies).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganManifestBindingV1 {
    pub organ_id: StableId,
    pub manifest_digest: Digest32,
    pub organ_class: OrganRole,
    pub input_ports: Vec<StableId>,
    pub output_ports: Vec<StableId>,
}

/// Exact, ordered V1 projection supplied by a trusted canonical producer.
/// `snapshot_digest` is source provenance, not recomputed from this projection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BodyGraphBindingV1 {
    pub generation: Generation,
    pub organ_manifests: Vec<OrganManifestBindingV1>,
    pub dependency_edges: Vec<OrganEdge>,
    pub fallback_edges: Vec<OrganEdge>,
    pub topological_order: Vec<usize>,
    pub snapshot_digest: Digest32,
}

/// Host-owned admission configuration, independent of the received payload.
/// Placement names are the host's trusted deployment identity, not attestations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledOrganAdmissionV2 {
    pub expected_digest: Digest32,
    pub generation: Generation,
    pub process: StableId,
    pub host: StableId,
}

/// A reviewed compiled handler and its manifest identity from the host catalog.
/// The digest does not sandbox the implementation or attest machine code.
#[derive(Debug)]
pub struct CompiledOrganHandlerV2 {
    pub manifest_digest: Digest32,
    pub handler: Box<dyn TrustedReadOnlyOrganV1>,
}

#[derive(Debug, Eq, PartialEq)]
pub struct VerifiedCompiledBodyGraphV2 {
    body: BodyGraphBindingV1,
    graph: OrganGraphsV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OrganWireError {
    Bounds,
    Encoding,
    UnsupportedVersion,
    UnsupportedExecutionProfile,
    Authority,
    Digest,
    Generation,
    Projection,
    Placement,
    HandlerManifest,
    ProtocolRegistry,
    ProtocolVersion,
    ProtocolSchema,
    Graph(OrganGraphError),
    Runtime(OrganRuntimeError),
}

impl fmt::Display for OrganWireError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl Error for OrganWireError {}

/// Producer-side encoding; obtaining these bytes or their digest grants nothing.
pub fn encode_compiled_body_graph_v2(
    body: &BodyGraphBindingV1,
    graph: &OrganGraphsV1,
) -> Result<Vec<u8>, OrganWireError> {
    validate_projection(body, graph)?;
    codec::encode(body, graph)
}

/// Domain-separated identity of the complete V2 bytes, including both graphs,
/// manifest digests, ports, timing/evidence profiles, ownership and placement.
pub fn compiled_body_graph_digest_v2(bytes: &[u8]) -> Result<Digest32, OrganWireError> {
    if bytes.len() > MAX_COMPILED_BODY_GRAPH_BYTES {
        return Err(OrganWireError::Bounds);
    }
    let mut input = b"hepta.compiled-body-graph.v2\0".to_vec();
    input.extend_from_slice(bytes);
    Ok(Digest32::of_bytes(&input))
}

/// Verify before constructing handlers or invoking any lifecycle callback.
/// Never populate `admission` with digest or placement assertions from `bytes`.
pub fn decode_compiled_body_graph_v2(
    bytes: &[u8],
    admission: &CompiledOrganAdmissionV2,
) -> Result<VerifiedCompiledBodyGraphV2, OrganWireError> {
    if admission.expected_digest.is_zero()
        || compiled_body_graph_digest_v2(bytes)? != admission.expected_digest
    {
        return Err(OrganWireError::Digest);
    }
    let (body, graph) = codec::decode(bytes)?;
    validate_projection(&body, &graph)?;
    if graph.generation != admission.generation {
        return Err(OrganWireError::Generation);
    }
    // This host executes every handler in one process; declared distributed
    // placement cannot become a fictitious failure-isolation guarantee.
    if graph
        .failure_domains
        .iter()
        .any(|domain| domain.process != admission.process || domain.host != admission.host)
    {
        return Err(OrganWireError::Placement);
    }
    Ok(VerifiedCompiledBodyGraphV2 { body, graph })
}

/// Registry-gated native handoff entry point. The protocol claim is checked
/// against the independently provisioned registry before decoding the bytes;
/// the existing host admission then verifies the independently supplied
/// payload digest, generation and placement. Successful return includes a
/// receipt so callers cannot confuse a decoded projection with an admitted
/// protocol handoff.
pub fn admit_compiled_body_graph_v2(
    bytes: &[u8],
    admission: &CompiledOrganAdmissionV2,
    protocol: &NativeHandoffProtocolAdmissionV1,
    registry: &NativeHandoffProtocolRegistryV1,
) -> Result<(VerifiedCompiledBodyGraphV2, NativeHandoffReceiptV1), OrganWireError> {
    registry.admit(protocol)?;
    let payload_digest = compiled_body_graph_digest_v2(bytes)?;
    let verified = decode_compiled_body_graph_v2(bytes, admission)?;
    if verified.generation() != admission.generation {
        return Err(OrganWireError::Generation);
    }
    let receipt = NativeHandoffReceiptV1 {
        protocol_id: protocol.protocol_id.clone(),
        profile_id: protocol.profile_id.clone(),
        profile_version: protocol.profile_version,
        schema_digest: protocol.schema_digest,
        payload_digest,
        generation: verified.generation(),
        authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
    };
    Ok((verified, receipt))
}

impl VerifiedCompiledBodyGraphV2 {
    pub fn generation(&self) -> Generation {
        self.body.generation
    }

    pub fn snapshot_digest(&self) -> Digest32 {
        self.body.snapshot_digest
    }

    /// Consume the verified value and the trusted local catalog. A successful
    /// construction is still Registered, not started or externally qualified.
    pub fn into_host(
        self,
        handlers: Vec<CompiledOrganHandlerV2>,
    ) -> Result<OrganHostV1, OrganWireError> {
        if handlers.len() != self.body.organ_manifests.len()
            || handlers.iter().any(|registered| {
                !self.body.organ_manifests.iter().any(|manifest| {
                    &manifest.organ_id == registered.handler.id()
                        && manifest.manifest_digest == registered.manifest_digest
                })
            })
        {
            return Err(OrganWireError::HandlerManifest);
        }
        OrganHostV1::new(
            self.graph,
            handlers.into_iter().map(|entry| entry.handler).collect(),
        )
        .map_err(OrganWireError::Runtime)
    }
}

fn validate_projection(
    body: &BodyGraphBindingV1,
    graph: &OrganGraphsV1,
) -> Result<(), OrganWireError> {
    let validated = graph.validate().map_err(OrganWireError::Graph)?;
    if graph
        .organs
        .iter()
        .any(|node| !node.effect_scope.is_empty())
    {
        return Err(OrganWireError::Authority);
    }
    if body.snapshot_digest.is_zero()
        || body.generation != graph.generation
        || body.organ_manifests.len() != graph.organs.len()
        || body.dependency_edges != graph.initialization
        || body.fallback_edges != graph.fallback
        || body.topological_order != validated.initialization_order
    {
        return Err(OrganWireError::Projection);
    }
    for (manifest, node) in body.organ_manifests.iter().zip(&graph.organs) {
        if manifest.manifest_digest.is_zero()
            || manifest.organ_id != node.id
            || manifest.organ_class != node.role
            || manifest.input_ports != node.inputs
            || manifest.output_ports != node.outputs
            || node.inputs.iter().collect::<BTreeSet<_>>().len() != node.inputs.len()
            || node.outputs.iter().collect::<BTreeSet<_>>().len() != node.outputs.len()
        {
            return Err(OrganWireError::Projection);
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "organ_wire_tests.rs"]
mod tests;
