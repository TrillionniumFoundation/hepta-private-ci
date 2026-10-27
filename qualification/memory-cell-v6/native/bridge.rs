//! Executable qualification caller; the owner export is a local fixture, not a
//! production authority adapter or a continuously refreshed revocation service.

use std::error::Error;
use std::fs;
use std::path::Path;

use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::decode_memory_readout_v1;
use codex_hepta_cognitive_types::decode_memory_request_v1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::HnmfContractError;
use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::ContextItem;
use codex_hepta_context_compiler::ContextRole;
use codex_hepta_context_compiler::compile;
use codex_hepta_memory_retrieval::MemorySourceVerifierV1;
use codex_hepta_memory_retrieval::revalidate_memory_readout_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnedSource {
    source_id: ContractDigestV1,
    scope: String,
    entity: String,
    seq: u64,
    revoked: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnerExport {
    schema: String,
    generation: ContractGenerationV1,
    snapshot_digest: ContractDigestV1,
    source_cut: u64,
    sources: Vec<OwnedSource>,
}

impl MemorySourceVerifierV1 for OwnerExport {
    fn verify_current_source(
        &self,
        request: &MemoryRequestV1,
        source: ContractDigestV1,
        snapshot: ContractDigestV1,
    ) -> Result<(), HnmfContractError> {
        if snapshot != self.snapshot_digest {
            return Err(HnmfContractError::Conflict("owner snapshot"));
        }
        let record = self.sources.iter().find(|row| row.source_id == source)
            .ok_or(HnmfContractError::Missing("owned source"))?;
        if record.revoked
            || record.scope != request.scope.as_str()
            || record.entity != request.entity.as_str()
            || record.seq > self.source_cut
        {
            return Err(HnmfContractError::Conflict("source owner rejected dependency"));
        }
        Ok(())
    }
}

fn bounded_file(path: &Path) -> Result<Vec<u8>, Box<dyn Error>> {
    if path.is_symlink() || fs::metadata(path)?.len() > 2_000_000 {
        return Err("invalid bounded qualification fixture".into());
    }
    Ok(fs::read(path)?)
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = std::env::args().collect::<Vec<_>>();
    if args.len() != 4 {
        return Err("usage: native-memory-bridge REQUEST READOUT OWNER_EXPORT".into());
    }
    let request_bytes = bounded_file(Path::new(&args[1]))?;
    let readout_bytes = bounded_file(Path::new(&args[2]))?;
    let owner_bytes = bounded_file(Path::new(&args[3]))?;
    let request = decode_memory_request_v1(&request_bytes)?;
    let readout = decode_memory_readout_v1(&readout_bytes)?;
    let owner: OwnerExport = serde_json::from_slice(&owner_bytes)?;
    if owner.schema != "hepta.memory.native-owner-fixture.v1"
        || owner.sources.is_empty()
        || owner.sources.len() > 4096
        || owner.source_cut >= 1_u64 << 53
    {
        return Err("invalid owner export".into());
    }
    let source_ids = owner.sources.iter().map(|row| row.source_id).collect::<std::collections::BTreeSet<_>>();
    if source_ids.len() != owner.sources.len() {
        return Err("duplicate source ownership".into());
    }
    revalidate_memory_readout_v1(&request, &readout, owner.generation, owner.snapshot_digest, &owner)?;
    // Canonical serialization includes value, prediction_kind and all source /
    // model identities. Only its digest crosses this V1 compiler boundary.
    let content = serde_json::to_vec(&readout)?;
    let item_id = StableId::new(format!("memory:{}", request.query_id))?;
    let receipt = compile(CompilationRequest {
        compilation_id: StableId::new("memory-cell-v6:native-qualification")?,
        run_snapshot_digest: readout.snapshot_digest.digest(),
        objective_digest: Digest32::of_bytes(&request_bytes),
        token_budget: 32768,
        items: vec![ContextItem {
            item_id: item_id.clone(),
            role: ContextRole::UntrustedEvidence,
            content_digest: Digest32::of_bytes(&content),
            source_digest: Digest32::of_bytes(&serde_json::to_vec(&readout.source_ids)?),
            // A byte upper bound for this fixture, not a provider token receipt.
            token_count: u64::try_from(content.len())?,
            contains_secret: false, // This executable admits public synthetic fixtures only.
        }],
    })?;
    if !receipt.trusted_instruction_ids.is_empty()
        || receipt.untrusted_evidence_ids != vec![item_id]
        || !receipt.omitted_ids.is_empty()
        || receipt.authority.grants_any()
    {
        return Err("context separation invariant failed".into());
    }
    println!("{}", serde_json::to_string(&json!({
        "schema": "hepta.memory.native-bridge-receipt.v1",
        "query_id": request.query_id,
        "operation": readout.operation,
        "prediction_kind": readout.prediction_kind,
        "value": readout.value,
        "source_ids": readout.source_ids,
        "cell_digests": readout.cell_digests,
        "readout_sha256": Digest32::of_bytes(&readout_bytes).to_string(),
        "owner_fixture_sha256": Digest32::of_bytes(&owner_bytes).to_string(),
        "trusted_instruction_ids": [],
        "untrusted_evidence_ids": receipt.untrusted_evidence_ids.iter().map(StableId::as_str).collect::<Vec<_>>(),
        "context_digest": receipt.context_digest.to_string(),
        "authority_granted": receipt.authority.grants_any(),
        "token_charge_kind": "byte upper bound; no provider/tokenizer claim",
        "scope": "leaf qualification caller; not full product integration"
    }))?);
    Ok(())
}
