//! Fixed-schema, non-recursive codec. Counts are checked before allocation.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::BodyGraphBindingV1;
use super::MAX_COMPILED_BODY_GRAPH_BYTES;
use super::OrganManifestBindingV1;
use super::OrganWireError;
use crate::DataflowTiming;
use crate::FailureDomainV1;
use crate::FallbackTerminal;
use crate::FeedbackProfileV1;
use crate::InputPort;
use crate::OrganEdge;
use crate::OrganGraphsV1;
use crate::OrganNodeV1;
use crate::OrganRole;
use crate::OutputPort;
use crate::RuntimeLinkV1;

const MAGIC: &[u8; 8] = b"HEPTAORG";

pub(super) fn encode(
    body: &BodyGraphBindingV1,
    graph: &OrganGraphsV1,
) -> Result<Vec<u8>, OrganWireError> {
    let mut w = Writer(MAGIC.to_vec());
    w.index(/*value*/ 2); // V2 transport, not a V1 canonical snapshot codec.
    w.byte(/*value*/ 0); // Compiled, stateless, read-only execution profile.
    w.byte(/*value*/ 0); // All eight AuthorityPosture flags are false.
    w.u64(body.generation.get());
    w.digest(body.snapshot_digest);
    w.list(&body.organ_manifests, |w, manifest| {
        w.id(&manifest.organ_id);
        w.digest(manifest.manifest_digest);
        w.role(manifest.organ_class);
        w.list(&manifest.input_ports, Writer::id);
        w.list(&manifest.output_ports, Writer::id);
    });
    w.list(&body.dependency_edges, Writer::edge);
    w.list(&body.fallback_edges, Writer::edge);
    w.list(&body.topological_order, |w, index| w.index(*index));
    w.u64(graph.generation.get());
    w.list(&graph.organs, |w, node| {
        w.id(&node.id);
        w.id(&node.owner);
        w.role(node.role);
        w.list(&node.inputs, Writer::id);
        w.list(&node.outputs, Writer::id);
        w.index(/*value*/ 0); // Non-empty effect scopes are rejected before encoding.
        match node.terminal {
            FallbackTerminal::None => w.byte(/*value*/ 0),
            FallbackTerminal::SafeState(digest) => {
                w.byte(/*value*/ 1);
                w.digest(digest);
            }
            FallbackTerminal::HumanTakeover(digest) => {
                w.byte(/*value*/ 2);
                w.digest(digest);
            }
        }
    });
    w.list(&graph.initialization, Writer::edge);
    w.list(&graph.runtime, |w, link| {
        w.index(link.output.organ);
        w.index(link.output.port);
        w.index(link.input.organ);
        w.index(link.input.port);
        w.byte(match link.timing {
            DataflowTiming::Buffered => 0,
            DataflowTiming::Synchronous => 1,
        });
    });
    w.list(&graph.feedback, |w, profile| {
        w.index(profile.members.len());
        for member in &profile.members {
            w.index(*member);
        }
        w.u64(profile.reference_generation.get());
        w.u64(profile.period_ns);
        w.u64(profile.delay_ns);
        w.u64(profile.jitter_ns);
        w.0.extend_from_slice(&profile.queue_capacity.to_be_bytes());
        w.u64(profile.max_gain_q24);
        w.u64(profile.saturation_q24);
        w.digest(profile.gains_and_saturation);
        w.digest(profile.operating_region);
        w.digest(profile.stability_analysis);
        w.digest(profile.perturbation_tests);
        w.index(profile.exit_organ);
    });
    w.list(&graph.fallback, Writer::edge);
    w.list(&graph.failure_domains, |w, domain| {
        w.index(domain.organ);
        w.id(&domain.process);
        w.id(&domain.host);
    });
    if w.0.len() > MAX_COMPILED_BODY_GRAPH_BYTES {
        return Err(OrganWireError::Bounds);
    }
    Ok(w.0)
}

pub(super) fn decode(bytes: &[u8]) -> Result<(BodyGraphBindingV1, OrganGraphsV1), OrganWireError> {
    if bytes.len() > MAX_COMPILED_BODY_GRAPH_BYTES {
        return Err(OrganWireError::Bounds);
    }
    let mut r = Reader(bytes);
    if r.take(/*count*/ 8)? != MAGIC {
        return Err(OrganWireError::Encoding);
    }
    if r.index()? != 2 {
        return Err(OrganWireError::UnsupportedVersion);
    }
    if r.byte()? != 0 {
        return Err(OrganWireError::UnsupportedExecutionProfile);
    }
    if r.byte()? != 0 {
        return Err(OrganWireError::Authority);
    }
    let generation = r.generation()?;
    let snapshot_digest = r.digest()?;
    let body = BodyGraphBindingV1 {
        generation,
        snapshot_digest,
        organ_manifests: r.list(/*limit*/ 128, |r| {
            Ok(OrganManifestBindingV1 {
                organ_id: r.id()?,
                manifest_digest: r.digest()?,
                organ_class: r.role()?,
                input_ports: r.list(/*limit*/ 32, Reader::id)?,
                output_ports: r.list(/*limit*/ 32, Reader::id)?,
            })
        })?,
        dependency_edges: r.list(/*limit*/ 1024, Reader::edge)?,
        fallback_edges: r.list(/*limit*/ 1024, Reader::edge)?,
        topological_order: r.list(/*limit*/ 128, Reader::index)?,
    };
    let graph = OrganGraphsV1 {
        generation: r.generation()?,
        organs: r.list(/*limit*/ 128, |r| {
            let id = r.id()?;
            let owner = r.id()?;
            let role = r.role()?;
            let inputs = r.list(/*limit*/ 32, Reader::id)?;
            let outputs = r.list(/*limit*/ 32, Reader::id)?;
            if r.index()? != 0 {
                return Err(OrganWireError::Authority);
            }
            let terminal = match r.byte()? {
                0 => FallbackTerminal::None,
                1 => FallbackTerminal::SafeState(r.digest()?),
                2 => FallbackTerminal::HumanTakeover(r.digest()?),
                _ => return Err(OrganWireError::Encoding),
            };
            Ok(OrganNodeV1 {
                id,
                owner,
                role,
                inputs,
                outputs,
                effect_scope: BTreeSet::new(),
                terminal,
            })
        })?,
        initialization: r.list(/*limit*/ 1024, Reader::edge)?,
        runtime: r.list(/*limit*/ 1024, |r| {
            Ok(RuntimeLinkV1 {
                output: OutputPort {
                    organ: r.index()?,
                    port: r.index()?,
                },
                input: InputPort {
                    organ: r.index()?,
                    port: r.index()?,
                },
                timing: match r.byte()? {
                    0 => DataflowTiming::Buffered,
                    1 => DataflowTiming::Synchronous,
                    _ => return Err(OrganWireError::Encoding),
                },
            })
        })?,
        feedback: r.list(/*limit*/ 128, |r| {
            let members = r.list(/*limit*/ 128, Reader::index)?;
            if members.windows(/*size*/ 2).any(|pair| pair[0] >= pair[1]) {
                return Err(OrganWireError::Encoding);
            }
            Ok(FeedbackProfileV1 {
                members: members.into_iter().collect(),
                reference_generation: r.generation()?,
                period_ns: r.u64()?,
                delay_ns: r.u64()?,
                jitter_ns: r.u64()?,
                queue_capacity: u32::from_be_bytes(r.array()?),
                max_gain_q24: r.u64()?,
                saturation_q24: r.u64()?,
                gains_and_saturation: r.digest()?,
                operating_region: r.digest()?,
                stability_analysis: r.digest()?,
                perturbation_tests: r.digest()?,
                exit_organ: r.index()?,
            })
        })?,
        fallback: r.list(/*limit*/ 1024, Reader::edge)?,
        failure_domains: r.list(/*limit*/ 128, |r| {
            Ok(FailureDomainV1 {
                organ: r.index()?,
                process: r.id()?,
                host: r.id()?,
            })
        })?,
    };
    if !r.0.is_empty() {
        // Fixed schema has no extension bag: unknown fields fail closed.
        return Err(OrganWireError::Encoding);
    }
    Ok((body, graph))
}

struct Writer(Vec<u8>);

impl Writer {
    fn byte(&mut self, value: u8) {
        self.0.push(value);
    }

    fn index(&mut self, value: usize) {
        // encode's caller validates every count/index against graph bounds.
        self.0.extend_from_slice(&(value as u16).to_be_bytes());
    }

    fn u64(&mut self, value: u64) {
        self.0.extend_from_slice(&value.to_be_bytes());
    }

    fn digest(&mut self, value: Digest32) {
        self.0.extend_from_slice(value.as_array());
    }

    fn id(&mut self, value: &StableId) {
        self.index(value.as_str().len());
        self.0.extend_from_slice(value.as_str().as_bytes());
    }

    fn role(&mut self, role: OrganRole) {
        self.byte(match role {
            OrganRole::Cognitive => 0,
            OrganRole::LocalSafety => 1,
            OrganRole::Other => 2,
        });
    }

    fn edge(&mut self, edge: &OrganEdge) {
        self.index(edge.from);
        self.index(edge.to);
    }

    fn list<T>(&mut self, values: &[T], write: impl Fn(&mut Self, &T)) {
        self.index(values.len());
        for value in values {
            write(self, value);
        }
    }
}

struct Reader<'a>(&'a [u8]);

impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], OrganWireError> {
        let (value, rest) = self
            .0
            .split_at_checked(count)
            .ok_or(OrganWireError::Encoding)?;
        self.0 = rest;
        Ok(value)
    }

    fn array<const N: usize>(&mut self) -> Result<[u8; N], OrganWireError> {
        self.take(N)?
            .try_into()
            .map_err(|_| OrganWireError::Encoding)
    }

    fn byte(&mut self) -> Result<u8, OrganWireError> {
        Ok(self.array::<1>()?[0])
    }

    fn index(&mut self) -> Result<usize, OrganWireError> {
        Ok(usize::from(u16::from_be_bytes(self.array()?)))
    }

    fn u64(&mut self) -> Result<u64, OrganWireError> {
        Ok(u64::from_be_bytes(self.array()?))
    }

    fn generation(&mut self) -> Result<Generation, OrganWireError> {
        Generation::new(self.u64()?).map_err(|_| OrganWireError::Generation)
    }

    fn digest(&mut self) -> Result<Digest32, OrganWireError> {
        Ok(Digest32::from_array(self.array()?))
    }

    fn id(&mut self) -> Result<StableId, OrganWireError> {
        let count = self.index()?;
        if count == 0 || count > 128 {
            return Err(OrganWireError::Bounds);
        }
        let value = std::str::from_utf8(self.take(count)?).map_err(|_| OrganWireError::Encoding)?;
        StableId::new(value).map_err(|_| OrganWireError::Encoding)
    }

    fn role(&mut self) -> Result<OrganRole, OrganWireError> {
        match self.byte()? {
            0 => Ok(OrganRole::Cognitive),
            1 => Ok(OrganRole::LocalSafety),
            2 => Ok(OrganRole::Other),
            _ => Err(OrganWireError::Encoding),
        }
    }

    fn edge(&mut self) -> Result<OrganEdge, OrganWireError> {
        Ok(OrganEdge {
            from: self.index()?,
            to: self.index()?,
        })
    }

    fn list<T>(
        &mut self,
        limit: usize,
        read: impl Fn(&mut Self) -> Result<T, OrganWireError>,
    ) -> Result<Vec<T>, OrganWireError> {
        let count = self.index()?;
        if count > limit || count > self.0.len() {
            return Err(OrganWireError::Bounds);
        }
        (0..count).map(|_| read(self)).collect()
    }
}
