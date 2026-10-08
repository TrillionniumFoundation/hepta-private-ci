//! Strict JSON DTOs for the immutable cell parameter bundle owner.
//!
//! The DTOs carry only bounded strings, integers, bytes, and explicit enum
//! tags. They never carry an authority token. Decoding reconstructs domain
//! identities and calls the owner validation before a value can cross a
//! runtime seam.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::cell_parameter_bundle::{
    CasArtifactRefV1, CellArtifactManifestV1, CellBundlePredecessorV1, CellComponentModeV1,
    CellComponentRefV1, CellIdentityV1, CellParameterBundleErrorV1, CellParameterBundleReceiptV1,
    CellParameterBundleV1,
};
use super::cell_parameter_bundle_owner::CellParameterBundleOwnerV1;

const MAX_WIRE_BYTES: usize = 256 * 1024;
const MAX_RECORDS: usize = 4_096;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellParameterBundleWireV1 {
    pub bundle_id: String,
    pub identity: CellIdentityWireV1,
    pub parent_predecessor: Option<CellBundlePredecessorWireV1>,
    pub shared_base: CasArtifactRefWireV1,
    pub adapter: CellComponentWireV1,
    pub head: CellComponentWireV1,
    pub state_schema_digest: String,
    pub optimizer_lineage_digest: String,
    pub artifact_manifest: CellArtifactManifestWireV1,
    pub rollback_target: Option<CellBundlePredecessorWireV1>,
    pub bundle_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellIdentityWireV1 {
    pub cell_id: String,
    pub child_id: String,
    pub generation: u64,
    pub scope_digest: String,
    pub lineage_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellBundlePredecessorWireV1 {
    pub bundle_id: String,
    pub bundle_digest: String,
    pub generation: u64,
    pub lineage_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CasArtifactRefWireV1 {
    pub artifact_id: String,
    pub content_digest: String,
    pub manifest_digest: String,
    pub compatibility_digest: String,
    pub encoded_size_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellComponentWireV1 {
    pub component_id: String,
    pub mode: String,
    pub artifact: CasArtifactRefWireV1,
    pub source_artifact_digest: Option<String>,
    pub compatibility_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellArtifactManifestWireV1 {
    pub manifest_id: String,
    pub cas_root_digest: String,
    pub entries: Vec<CasArtifactRefWireV1>,
    pub manifest_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellParameterBundleReceiptWireV1 {
    pub disposition: String,
    pub operation_id: String,
    pub sequence: u64,
    pub bundle_id: String,
    pub bundle_digest: String,
    pub predecessor_head_digest: String,
    pub head_digest: String,
    pub authority_mask: u8,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellParameterBundleOwnerSnapshotWireV1 {
    pub scope_digest: String,
    pub head_digest: String,
    pub records: Vec<CellParameterBundleWireV1>,
    pub receipts: Vec<CellParameterBundleReceiptWireV1>,
}

impl CellParameterBundleOwnerSnapshotWireV1 {
    pub(crate) fn try_into_parts(
        self,
    ) -> Result<
        (
            Digest32,
            Digest32,
            Vec<CellParameterBundleV1>,
            Vec<CellParameterBundleReceiptV1>,
        ),
        CellParameterBundleWireErrorV1,
    > {
        let scope_digest = parse_digest(&self.scope_digest, "scope digest")?;
        let head_digest = parse_digest(&self.head_digest, "head digest")?;
        let records = self
            .records
            .into_iter()
            .map(CellParameterBundleWireV1::try_into_bundle)
            .collect::<Result<Vec<_>, _>>()?;
        let receipts = self
            .receipts
            .iter()
            .map(|receipt| {
                receipt
                    .try_into_receipt()?
                    .ok_or(CellParameterBundleWireErrorV1::ReceiptMismatch)
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok((scope_digest, head_digest, records, receipts))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellParameterBundleWireErrorV1 {
    Json,
    TooLarge,
    Limit,
    InvalidField(&'static str),
    Bundle(CellParameterBundleErrorV1),
    ReceiptMismatch,
}

impl fmt::Display for CellParameterBundleWireErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellParameterBundleWireErrorV1 {}

pub fn encode_cell_parameter_bundle_wire_v1(
    bundle: &CellParameterBundleV1,
) -> Result<Vec<u8>, CellParameterBundleWireErrorV1> {
    bundle
        .validate()
        .map_err(CellParameterBundleWireErrorV1::Bundle)?;
    bounded_json(&CellParameterBundleWireV1::from(bundle))
}

pub fn decode_cell_parameter_bundle_wire_v1(
    bytes: &[u8],
) -> Result<CellParameterBundleV1, CellParameterBundleWireErrorV1> {
    let wire: CellParameterBundleWireV1 = decode_json(bytes)?;
    let bundle = wire.try_into_bundle()?;
    bundle
        .validate()
        .map_err(CellParameterBundleWireErrorV1::Bundle)?;
    Ok(bundle)
}

pub fn encode_cell_parameter_bundle_owner_snapshot_v1(
    owner: &CellParameterBundleOwnerV1,
) -> Result<Vec<u8>, CellParameterBundleWireErrorV1> {
    let snapshot = CellParameterBundleOwnerSnapshotWireV1 {
        scope_digest: owner.scope_digest().to_string(),
        head_digest: owner.head_digest().to_string(),
        records: owner
            .records()
            .iter()
            .map(CellParameterBundleWireV1::from)
            .collect(),
        receipts: owner
            .receipts()
            .iter()
            .map(CellParameterBundleReceiptWireV1::from)
            .collect(),
    };
    bounded_json(&snapshot)
}

pub fn decode_cell_parameter_bundle_owner_snapshot_v1(
    bytes: &[u8],
) -> Result<CellParameterBundleOwnerSnapshotWireV1, CellParameterBundleWireErrorV1> {
    let snapshot: CellParameterBundleOwnerSnapshotWireV1 = decode_json(bytes)?;
    if snapshot.records.len() > MAX_RECORDS
        || snapshot.receipts.len() > MAX_RECORDS
        || snapshot.records.len() != snapshot.receipts.len()
    {
        return Err(CellParameterBundleWireErrorV1::Limit);
    }
    let scope_digest = parse_digest(&snapshot.scope_digest, "scope digest")?;
    let head_digest = parse_digest(&snapshot.head_digest, "head digest")?;
    if scope_digest.is_zero() {
        return Err(CellParameterBundleWireErrorV1::InvalidField("scope digest"));
    }
    for record in &snapshot.records {
        let bundle = record.clone().try_into_bundle()?;
        bundle
            .validate()
            .map_err(CellParameterBundleWireErrorV1::Bundle)?;
    }
    for receipt in &snapshot.receipts {
        let _ = receipt
            .try_into_receipt()?
            .ok_or(CellParameterBundleWireErrorV1::ReceiptMismatch)?;
    }
    if snapshot.records.is_empty() && !head_digest.is_zero() {
        return Err(CellParameterBundleWireErrorV1::ReceiptMismatch);
    }
    Ok(snapshot)
}

fn bounded_json<T: Serialize>(value: &T) -> Result<Vec<u8>, CellParameterBundleWireErrorV1> {
    let bytes = serde_json::to_vec(value).map_err(|_| CellParameterBundleWireErrorV1::Json)?;
    if bytes.len() > MAX_WIRE_BYTES {
        return Err(CellParameterBundleWireErrorV1::TooLarge);
    }
    Ok(bytes)
}

fn decode_json<T: for<'de> Deserialize<'de>>(
    bytes: &[u8],
) -> Result<T, CellParameterBundleWireErrorV1> {
    if bytes.is_empty() || bytes.len() > MAX_WIRE_BYTES {
        return Err(CellParameterBundleWireErrorV1::TooLarge);
    }
    serde_json::from_slice(bytes).map_err(|_| CellParameterBundleWireErrorV1::Json)
}

fn parse_id(value: &str, label: &'static str) -> Result<StableId, CellParameterBundleWireErrorV1> {
    StableId::new(value).map_err(|_| CellParameterBundleWireErrorV1::InvalidField(label))
}

fn parse_digest(
    value: &str,
    label: &'static str,
) -> Result<Digest32, CellParameterBundleWireErrorV1> {
    Digest32::from_str(value).map_err(|_| CellParameterBundleWireErrorV1::InvalidField(label))
}

fn parse_generation(
    value: u64,
    label: &'static str,
) -> Result<Generation, CellParameterBundleWireErrorV1> {
    Generation::new(value).map_err(|_| CellParameterBundleWireErrorV1::InvalidField(label))
}

impl From<&CellParameterBundleV1> for CellParameterBundleWireV1 {
    fn from(value: &CellParameterBundleV1) -> Self {
        Self {
            bundle_id: value.bundle_id.to_string(),
            identity: (&value.identity).into(),
            parent_predecessor: value.parent_predecessor.as_ref().map(Into::into),
            shared_base: (&value.shared_base).into(),
            adapter: (&value.adapter).into(),
            head: (&value.head).into(),
            state_schema_digest: value.state_schema_digest.to_string(),
            optimizer_lineage_digest: value.optimizer_lineage_digest.to_string(),
            artifact_manifest: (&value.artifact_manifest).into(),
            rollback_target: value.rollback_target.as_ref().map(Into::into),
            bundle_digest: value.bundle_digest.to_string(),
        }
    }
}

impl CellParameterBundleWireV1 {
    fn try_into_bundle(self) -> Result<CellParameterBundleV1, CellParameterBundleWireErrorV1> {
        Ok(CellParameterBundleV1 {
            bundle_id: parse_id(&self.bundle_id, "bundle id")?,
            identity: self.identity.try_into_identity()?,
            parent_predecessor: self
                .parent_predecessor
                .map(CellBundlePredecessorWireV1::try_into_predecessor)
                .transpose()?,
            shared_base: self.shared_base.try_into_artifact()?,
            adapter: self.adapter.try_into_component()?,
            head: self.head.try_into_component()?,
            state_schema_digest: parse_digest(&self.state_schema_digest, "state schema")?,
            optimizer_lineage_digest: parse_digest(
                &self.optimizer_lineage_digest,
                "optimizer lineage",
            )?,
            artifact_manifest: self.artifact_manifest.try_into_manifest()?,
            rollback_target: self
                .rollback_target
                .map(CellBundlePredecessorWireV1::try_into_predecessor)
                .transpose()?,
            bundle_digest: parse_digest(&self.bundle_digest, "bundle digest")?,
        })
    }
}

impl From<&CellIdentityV1> for CellIdentityWireV1 {
    fn from(value: &CellIdentityV1) -> Self {
        Self {
            cell_id: value.cell_id.to_string(),
            child_id: value.child_id.to_string(),
            generation: value.generation.get(),
            scope_digest: value.scope_digest.to_string(),
            lineage_digest: value.lineage_digest.to_string(),
        }
    }
}

impl CellIdentityWireV1 {
    fn try_into_identity(self) -> Result<CellIdentityV1, CellParameterBundleWireErrorV1> {
        Ok(CellIdentityV1 {
            cell_id: parse_id(&self.cell_id, "cell id")?,
            child_id: parse_id(&self.child_id, "child id")?,
            generation: parse_generation(self.generation, "generation")?,
            scope_digest: parse_digest(&self.scope_digest, "scope digest")?,
            lineage_digest: parse_digest(&self.lineage_digest, "lineage digest")?,
        })
    }
}

impl From<&CellBundlePredecessorV1> for CellBundlePredecessorWireV1 {
    fn from(value: &CellBundlePredecessorV1) -> Self {
        Self {
            bundle_id: value.bundle_id.to_string(),
            bundle_digest: value.bundle_digest.to_string(),
            generation: value.generation.get(),
            lineage_digest: value.lineage_digest.to_string(),
        }
    }
}

impl CellBundlePredecessorWireV1 {
    fn try_into_predecessor(
        self,
    ) -> Result<CellBundlePredecessorV1, CellParameterBundleWireErrorV1> {
        Ok(CellBundlePredecessorV1 {
            bundle_id: parse_id(&self.bundle_id, "predecessor id")?,
            bundle_digest: parse_digest(&self.bundle_digest, "predecessor digest")?,
            generation: parse_generation(self.generation, "predecessor generation")?,
            lineage_digest: parse_digest(&self.lineage_digest, "predecessor lineage")?,
        })
    }
}

impl From<&CasArtifactRefV1> for CasArtifactRefWireV1 {
    fn from(value: &CasArtifactRefV1) -> Self {
        Self {
            artifact_id: value.artifact_id.to_string(),
            content_digest: value.content_digest.to_string(),
            manifest_digest: value.manifest_digest.to_string(),
            compatibility_digest: value.compatibility_digest.to_string(),
            encoded_size_bytes: value.encoded_size_bytes,
        }
    }
}

impl CasArtifactRefWireV1 {
    fn try_into_artifact(self) -> Result<CasArtifactRefV1, CellParameterBundleWireErrorV1> {
        Ok(CasArtifactRefV1 {
            artifact_id: parse_id(&self.artifact_id, "artifact id")?,
            content_digest: parse_digest(&self.content_digest, "content digest")?,
            manifest_digest: parse_digest(&self.manifest_digest, "manifest digest")?,
            compatibility_digest: parse_digest(&self.compatibility_digest, "compatibility digest")?,
            encoded_size_bytes: self.encoded_size_bytes,
        })
    }
}

impl From<&CellComponentRefV1> for CellComponentWireV1 {
    fn from(value: &CellComponentRefV1) -> Self {
        Self {
            component_id: value.component_id.to_string(),
            mode: match value.mode {
                CellComponentModeV1::Cloned => "cloned",
                CellComponentModeV1::Reinitialized => "reinitialized",
            }
            .to_owned(),
            artifact: (&value.artifact).into(),
            source_artifact_digest: value
                .source_artifact_digest
                .map(|digest| digest.to_string()),
            compatibility_digest: value.compatibility_digest.to_string(),
        }
    }
}

impl CellComponentWireV1 {
    fn try_into_component(self) -> Result<CellComponentRefV1, CellParameterBundleWireErrorV1> {
        let mode = match self.mode.as_str() {
            "cloned" => CellComponentModeV1::Cloned,
            "reinitialized" => CellComponentModeV1::Reinitialized,
            _ => {
                return Err(CellParameterBundleWireErrorV1::InvalidField(
                    "component mode",
                ));
            }
        };
        Ok(CellComponentRefV1 {
            component_id: parse_id(&self.component_id, "component id")?,
            mode,
            artifact: self.artifact.try_into_artifact()?,
            source_artifact_digest: self
                .source_artifact_digest
                .as_deref()
                .map(|digest| parse_digest(digest, "source artifact digest"))
                .transpose()?,
            compatibility_digest: parse_digest(
                &self.compatibility_digest,
                "component compatibility digest",
            )?,
        })
    }
}

impl From<&CellArtifactManifestV1> for CellArtifactManifestWireV1 {
    fn from(value: &CellArtifactManifestV1) -> Self {
        Self {
            manifest_id: value.manifest_id.to_string(),
            cas_root_digest: value.cas_root_digest.to_string(),
            entries: value.entries.iter().map(Into::into).collect(),
            manifest_digest: value.manifest_digest.to_string(),
        }
    }
}

impl CellArtifactManifestWireV1 {
    fn try_into_manifest(self) -> Result<CellArtifactManifestV1, CellParameterBundleWireErrorV1> {
        Ok(CellArtifactManifestV1 {
            manifest_id: parse_id(&self.manifest_id, "manifest id")?,
            cas_root_digest: parse_digest(&self.cas_root_digest, "CAS root digest")?,
            entries: self
                .entries
                .into_iter()
                .map(CasArtifactRefWireV1::try_into_artifact)
                .collect::<Result<Vec<_>, _>>()?,
            manifest_digest: parse_digest(&self.manifest_digest, "manifest digest")?,
        })
    }
}

impl From<&CellParameterBundleReceiptV1> for CellParameterBundleReceiptWireV1 {
    fn from(value: &CellParameterBundleReceiptV1) -> Self {
        Self {
            disposition: match value.disposition {
                super::cell_parameter_bundle::CellParameterBundleAppendDispositionV1::Appended => {
                    "appended"
                }
                super::cell_parameter_bundle::CellParameterBundleAppendDispositionV1::IdempotentReplay => {
                    "idempotent_replay"
                }
            }
            .to_owned(),
            operation_id: value.operation_id.to_string(),
            sequence: value.sequence,
            bundle_id: value.bundle_id.to_string(),
            bundle_digest: value.bundle_digest.to_string(),
            predecessor_head_digest: value.predecessor_head_digest.to_string(),
            head_digest: value.head_digest.to_string(),
            authority_mask: value.authority.flags().wire_mask(),
        }
    }
}

impl CellParameterBundleReceiptWireV1 {
    fn try_into_receipt(
        &self,
    ) -> Result<Option<CellParameterBundleReceiptV1>, CellParameterBundleWireErrorV1> {
        if self.authority_mask != 0 {
            return Err(CellParameterBundleWireErrorV1::InvalidField(
                "authority mask",
            ));
        }
        let disposition = match self.disposition.as_str() {
            "appended" => super::cell_parameter_bundle::CellParameterBundleAppendDispositionV1::Appended,
            "idempotent_replay" => {
                super::cell_parameter_bundle::CellParameterBundleAppendDispositionV1::IdempotentReplay
            }
            _ => return Err(CellParameterBundleWireErrorV1::InvalidField("receipt disposition")),
        };
        Ok(Some(CellParameterBundleReceiptV1 {
            disposition,
            operation_id: parse_id(&self.operation_id, "operation id")?,
            sequence: self.sequence,
            bundle_id: parse_id(&self.bundle_id, "receipt bundle id")?,
            bundle_digest: parse_digest(&self.bundle_digest, "receipt bundle digest")?,
            predecessor_head_digest: parse_digest(
                &self.predecessor_head_digest,
                "predecessor head digest",
            )?,
            head_digest: parse_digest(&self.head_digest, "receipt head digest")?,
            authority: AuthorityPosture::DENY_ALL,
        }))
    }
}
