//! Explicit legacy versus complete streaming parity; historical limits remain
//! unchanged. A stream header is separately frozen before evaluation.
use crate::*;
pub enum Inputs {
    Legacy(parity::Inputs),
    Streaming(streaming_parity::Inputs),
}
impl Inputs {
    pub fn load(root: &Path) -> Result<Self> {
        let bytes = report::read(&root.join("manifest.json"))?;
        let manifest: Value = serde_json::from_slice(&bytes)?;
        let loaded = if manifest["schema"] == "hepta.trained-cell-stream-parity.v8" {
            Self::Streaming(streaming_parity::Inputs::load(root)?)
        } else {
            Self::Legacy(parity::Inputs::load(root)?)
        };
        ensure(
            loaded.manifest() == &manifest,
            "parity manifest changed while loading",
        )?;
        Ok(loaded)
    }
    pub fn manifest(&self) -> &Value {
        match self {
            Self::Legacy(v) => &v.manifest,
            Self::Streaming(v) => &v.manifest,
        }
    }
    pub fn data_manifest(&self) -> &Value {
        match self {
            Self::Legacy(v) => &v.manifest,
            Self::Streaming(v) => &v.header,
        }
    }
    pub fn payloads(&self) -> &[Vec<u8>; 2] {
        match self {
            Self::Legacy(v) => &v.payloads,
            Self::Streaming(v) => &v.payloads,
        }
    }
    pub fn verify_family(&self, protocol: &str) -> Result<()> {
        match self {
            Self::Legacy(v) => v.verify_family(protocol, report::TASKS),
            Self::Streaming(v) => v.verify_family(protocol),
        }
    }
    pub fn compare_unpublished(&self, index: usize) -> Result<Value> {
        match self {
            Self::Legacy(v) => parity::compare_unpublished(v, index),
            Self::Streaming(v) => v.compare_unpublished(index),
        }
    }
    pub fn compare_handoff(
        &self,
        index: usize,
        typed: &mut OwnerTypedSelectedCandidateV5<handoff_version::Handoff>,
        owner: &LearningArtifactOwnerService,
        now: u64,
    ) -> Result<Value> {
        match self {
            Self::Legacy(v) => parity::compare_handoff(v, index, typed, owner, now),
            Self::Streaming(v) => typed.with_owner(owner, now, |bundle| {
                v.compare_bundle(index, bundle.serving())
            })?,
        }
    }
}
