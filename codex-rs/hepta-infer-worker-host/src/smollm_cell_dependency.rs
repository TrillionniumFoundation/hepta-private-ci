//! Exact TCD1 reconstruction for the existing eleven-object SmolLM profile.
//! This checks declared bytes; the original CURRENT and FinalUse owners decide use.

use codex_hepta_types::Digest32;

use super::Member;
use super::need;

/// Owned, independently pinned snapshots decoded by the protected host-file owner.
pub(crate) struct ControlledCellInputsV2 {
    pub(crate) sidecar: Vec<u8>,
    pub(crate) sidecar_digest: Digest32,
    pub(crate) dependency_wire: Vec<u8>,
    pub(crate) dependency_id: Digest32,
    pub(crate) operation_id: String,
}

pub(super) enum DependencyPlan {
    OriginalTcr1,
    PinnedTcd1 { wire: Vec<u8>, id: Digest32 },
}

pub(super) fn verify(
    plan: DependencyPlan,
    generation: u64,
    profile: Digest32,
    release: &[u8],
    members: &[Member],
) -> Result<(), String> {
    let DependencyPlan::PinnedTcd1 { wire, id } = plan else {
        return Ok(());
    };
    need(
        !wire.is_empty() && wire.len() <= 1_048_576 && !id.is_zero(),
        "TCD1 bound/pin",
    )?;
    need(
        generation > 0 && !profile.is_zero() && members.len() == 11,
        "TCD1 loader profile",
    )?;
    // validate_declaration and measured TCM1 verification ran first. Names,
    // payload hashes, lengths, membership and TCR1 context are independently
    // derived from this owner's exact profile and current parameter FD.
    let mut expected = b"TCD1".to_vec();
    expected.extend_from_slice(&generation.to_be_bytes());
    expected.extend_from_slice(profile.as_array());
    expected.extend_from_slice(&(release.len() as u32).to_be_bytes());
    expected.extend_from_slice(release);
    expected.extend_from_slice(&1_u16.to_be_bytes());
    expected.extend_from_slice(&0_u16.to_be_bytes());
    expected.extend_from_slice(&(members.len() as u16).to_be_bytes());
    for (index, member) in members.iter().enumerate() {
        let role = match member.name.as_str() {
            "adapter/artifact.safetensors" => 4,
            "base/model.safetensors" => 1,
            "base/special_tokens_map.json"
            | "base/tokenizer.json"
            | "base/tokenizer_config.json" => 2,
            "adapter/target-contract.json"
            | "adapter/wrapped-adapter.json"
            | "base/README.md"
            | "base/config.json"
            | "base/generation_config.json"
            | "base/material-manifest.json" => 6,
            _ => return Err("controlled Cell material: TCD1 exact file role".to_owned()),
        };
        expected.extend_from_slice(&(member.name.len() as u16).to_be_bytes());
        expected.extend_from_slice(member.name.as_bytes());
        expected.push(role);
        for digest in [&member.manifest_id, &member.payload_sha256] {
            expected.extend_from_slice(
                digest
                    .parse::<Digest32>()
                    .map_err(|e| e.to_string())?
                    .as_array(),
            );
        }
        expected.extend_from_slice(&member.size.to_be_bytes());
        // The adapter root requires the complete fixed base/tokenizer/config
        // roster. There are no optional files or peer-selected dependencies.
        let count = if index == 0 { members.len() - 1 } else { 0 };
        expected.extend_from_slice(&(count as u16).to_be_bytes());
        for child in 1..=count {
            expected.extend_from_slice(&(child as u16).to_be_bytes());
        }
    }
    need(
        wire == expected,
        "exact TCD1 generation/profile/paths/dependency closure",
    )?;
    need(
        Digest32::of_parts(&[b"trnm.cell-dependency-closure.v1\0", &expected]) == id,
        "TCD1 domain identity",
    )
}

#[cfg(test)]
#[path = "smollm_cell_dependency_tests.rs"]
mod tests;
