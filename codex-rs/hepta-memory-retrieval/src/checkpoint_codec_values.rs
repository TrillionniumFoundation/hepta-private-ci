//! V1 field order and explicit enum tags. Changing these requires a new schema.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::Codec;
use super::MemoryCheckpointCodecErrorV1;
use super::Reader;
use super::Result;
use super::Writer;
use crate::ActiveEngramNodeV1;
use crate::EngramActivationPathV1;
use crate::EngramContradictionV1;
use crate::EngramNodeV1;
use crate::EngramPopulationV1;
use crate::EngramRecallReceiptV1;
use crate::EngramResourceReceiptV1;
use crate::EngramSnapshotV1;
use crate::EngramSupportV1;
use crate::GeneratedRecallV1;
use crate::RecallAbstentionReasonV1;
use crate::RecallDispositionV1;
use crate::RecallPacketV1;
use crate::RecallSelectionV1;
use crate::RetrievalChannelV1;
use crate::RetrievalGeneratorOwnerV1;
use crate::RetrievalGeneratorReceiptV1;
use crate::RetrievalSourceCompletenessV1;
use crate::SynapseRelationV1;
use crate::SynapseV1;

impl Codec for Digest32 {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        writer.append(self.as_array())
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        let mut bytes = [0; 32];
        bytes.copy_from_slice(reader.take(32)?);
        Ok(Self::from_array(bytes))
    }
}

impl Codec for StableId {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        let bytes = self.as_str().as_bytes();
        u32::try_from(bytes.len())
            .map_err(|_| MemoryCheckpointCodecErrorV1::SizeLimit)?
            .write(writer)?;
        writer.append(bytes)
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        let count = usize::try_from(u32::read(reader)?)
            .map_err(|_| MemoryCheckpointCodecErrorV1::SizeLimit)?;
        if count > 128 {
            return Err(MemoryCheckpointCodecErrorV1::SizeLimit);
        }
        let value = std::str::from_utf8(reader.take(count)?)
            .map_err(|_| MemoryCheckpointCodecErrorV1::InvalidValue("id encoding"))?;
        Self::new(value).map_err(|_| MemoryCheckpointCodecErrorV1::InvalidValue("id"))
    }
}

impl Codec for Revision {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        self.get().write(writer)
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        Self::new(u64::read(reader)?)
            .map_err(|_| MemoryCheckpointCodecErrorV1::InvalidValue("revision"))
    }
}

impl Codec for FixedQ32 {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        self.raw().write(writer)
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        Ok(Self::from_raw(i64::read(reader)?))
    }
}

impl Codec for ProbabilityQ32 {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        self.raw().write(writer)
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        Self::from_raw(u64::read(reader)?)
            .map_err(|_| MemoryCheckpointCodecErrorV1::InvalidValue("probability"))
    }
}

impl Codec for AuthorityPosture {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        if self.grants_any() {
            return Err(MemoryCheckpointCodecErrorV1::InvalidValue("authority"));
        }
        0_u8.write(writer)
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        if u8::read(reader)? != 0 {
            return Err(MemoryCheckpointCodecErrorV1::InvalidValue("authority"));
        }
        Ok(Self::DENY_ALL)
    }
}

macro_rules! fields {
    ($type:ident { $($field:ident),+ $(,)? }) => {
        impl Codec for $type {
            fn write(&self, writer: &mut Writer) -> Result<()> {
                $(self.$field.write(writer)?;)+
                Ok(())
            }
            fn read(reader: &mut Reader<'_>) -> Result<Self> {
                Ok(Self { $($field: Codec::read(reader)?,)+ })
            }
        }
    };
}

macro_rules! tags {
    ($type:ident { $($variant:ident = $tag:literal),+ $(,)? }) => {
        impl Codec for $type {
            fn write(&self, writer: &mut Writer) -> Result<()> {
                let tag: u8 = match self { $(Self::$variant => $tag,)+ };
                tag.write(writer)
            }
            fn read(reader: &mut Reader<'_>) -> Result<Self> {
                match u8::read(reader)? {
                    $($tag => Ok(Self::$variant),)+
                    _ => Err(MemoryCheckpointCodecErrorV1::InvalidValue(stringify!($type))),
                }
            }
        }
    };
}

tags!(EngramPopulationV1 {
    SensoryTrace = 1, EpisodicBinding = 2, SemanticConcept = 3,
    ProceduralSkill = 4, PredictiveWorld = 5, UtilitySalience = 6, MetaMemory = 7,
});
tags!(SynapseRelationV1 {
    Associative = 1, Temporal = 2, Causal = 3, Procedural = 4,
    Predictive = 5, Supports = 6, Inhibitory = 7, Contradicts = 8,
});
tags!(RetrievalChannelV1 {
    Lexical = 1, Vector = 2, Entity = 3, Temporal = 4,
    Causal = 5, Procedural = 6, ContradictionSupport = 7, Graph = 8,
});
tags!(RetrievalGeneratorOwnerV1 {
    CognitiveLexical = 1, CognitiveEntity = 2, CognitiveTemporal = 3,
    CognitiveAssociative = 4, EncoderVector = 5, KnowledgeGraphCausal = 6,
    KnowledgeGraphProcedural = 7, KnowledgeGraphContradiction = 8,
});
tags!(RetrievalSourceCompletenessV1 {
    Exhausted = 1, LimitReached = 2, Unavailable = 3,
});
tags!(RecallAbstentionReasonV1 {
    NoCandidate = 1, InsufficientChannelCoverage = 2, ScoreBelowFloor = 3,
    OutOfDistribution = 4, ContradictoryEvidence = 5,
});

impl Codec for RecallDispositionV1 {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        match self {
            Self::Recalled => 1_u8.write(writer),
            Self::Abstained(reason) => {
                2_u8.write(writer)?;
                reason.write(writer)
            }
        }
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        match u8::read(reader)? {
            1 => Ok(Self::Recalled),
            2 => Ok(Self::Abstained(RecallAbstentionReasonV1::read(reader)?)),
            _ => Err(MemoryCheckpointCodecErrorV1::InvalidValue("disposition")),
        }
    }
}

fields!(EngramSupportV1 { record_id, record_revision });
fields!(EngramNodeV1 {
    node_id, population, support, threshold, confidence, generation_vector_digest,
});
fields!(SynapseV1 {
    source_node_id, target_node_id, relation, weight, support_digest, generation_vector_digest,
});
fields!(EngramSnapshotV1 {
    generation_vector_digest, engram_generation_digest, nodes, synapses, snapshot_digest, authority,
});
fields!(ActiveEngramNodeV1 { node_id, population, activation, confidence, support });
fields!(EngramActivationPathV1 { source_node_id, target_node_id, relation, contribution });
fields!(EngramContradictionV1 { left_node_id, right_node_id });
fields!(EngramResourceReceiptV1 {
    candidate_records, expanded_nodes, traversed_synapses, active_nodes, settling_steps, receipt_digest,
});
fields!(EngramRecallReceiptV1 {
    generation_vector_digest, engram_snapshot_digest, dynamics_policy_digest,
    active_nodes, activation_paths, contradictions, selected_support, coverage,
    confidence, settling_steps, resources, receipt_digest, authority,
});
fields!(RecallSelectionV1 {
    record_id, record_revision, record_digest, weighted_score, maximum_ood,
    channels, support_digests, contradiction_group_digests,
});
fields!(RecallPacketV1 {
    cue_digest, policy_digest, candidate_union_digest, generation_vector_digest,
    disposition, selections, omitted_count, distinct_channels, engram, packet_digest, authority,
});
fields!(RetrievalGeneratorReceiptV1 {
    generator, generation_vector_digest, owner_generation_digest,
    candidate_count, completeness, receipt_digest, authority,
});
fields!(GeneratedRecallV1 {
    packet, generator_receipts, source_completeness_digest, receipt_digest, authority,
});
