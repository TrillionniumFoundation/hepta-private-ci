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

impl VerifiedCompiledBodyGraphV2 {
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
