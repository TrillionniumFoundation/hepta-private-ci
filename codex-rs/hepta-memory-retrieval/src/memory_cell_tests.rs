use std::cell::RefCell;

use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_types::Digest32;

use super::*;

struct Owner {
    scope: ContractIdV1,
    entity: ContractIdV1,
    live_sources: Vec<ContractDigestV1>,
    snapshot: ContractDigestV1,
    checked: RefCell<Vec<ContractDigestV1>>,
}

impl MemorySourceVerifierV1 for Owner {
    fn verify_current_source(
        &self,
        request: &MemoryRequestV1,
        source: ContractDigestV1,
        snapshot: ContractDigestV1,
    ) -> Result<(), HnmfContractError> {
        self.checked.borrow_mut().push(source);
        if request.scope != self.scope
            || request.entity != self.entity
            || snapshot != self.snapshot
            || !self.live_sources.contains(&source)
        {
            return Err(HnmfContractError::Conflict("source owner denied"));
        }
        Ok(())
    }
}

fn fixture() -> Result<(MemoryRequestV1, MemoryReadoutV1, Owner), HnmfContractError> {
    let request = MemoryRequestV1 {
        schema: "hepta.memory.request.v1".to_owned(),
        query_id: ContractIdV1::new("query:1")?,
        scope: ContractIdV1::new("workspace:1")?,
        entity: ContractIdV1::new("sensor:1")?,
        text: "Recall the stable attribute".to_owned(),
        at: 20,
        since: 10,
        max_hops: 3,
        max_cells: 2,
    };
    let sources = [b"source-a", b"source-b"]
        .map(|value| ContractDigestV1::from_digest(Digest32::of_bytes(value)))
        .into_iter()
        .collect::<Result<Vec<_>, _>>()?;
    let readout = MemoryReadoutV1 {
        schema: "hepta.memory.readout.v1".to_owned(),
        query_id: request.query_id.clone(),
        operation: Some(MemoryOperationV1::Semantic),
        status: MemoryReadStatusV1::Ok,
        value: 7.into(),
        source_ids: sources.clone(),
        generation: ContractGenerationV1::new(1)?,
        snapshot_digest: ContractDigestV1::from_digest(Digest32::of_bytes(b"snapshot"))?,
        prediction_kind: MemoryPredictionKindV1::ModelPrediction,
        cell_digests: vec![
            ContractDigestV1::from_digest(Digest32::of_bytes(b"cell-a"))?,
            ContractDigestV1::from_digest(Digest32::of_bytes(b"cell-b"))?,
        ],
        hops: 3,
        elapsed_seconds: 0.001,
        reason: None,
    };
    let owner = Owner {
        scope: request.scope.clone(),
        entity: request.entity.clone(),
        live_sources: sources,
        snapshot: readout.snapshot_digest,
        checked: RefCell::new(Vec::new()),
    };
    Ok((request, readout, owner))
}

#[test]
fn every_support_is_checked_without_upgrading_the_prediction() -> Result<(), HnmfContractError> {
    let (request, readout, owner) = fixture()?;
    let original = readout.clone();
    assert_eq!(
        revalidate_memory_readout_v1(&request, &readout, readout.generation, owner.snapshot, &owner),
        Ok(())
    );
    assert_eq!(readout, original);
    assert_eq!(*owner.checked.borrow(), readout.source_ids);
    Ok(())
}

#[test]
fn changed_request_epoch_or_budget_fails_before_source_access() -> Result<(), HnmfContractError> {
    let (request, readout, owner) = fixture()?;
    let mut mutations = vec![readout.clone(); 5];
    mutations[0].query_id = ContractIdV1::new("query:other")?;
    mutations[1].generation = ContractGenerationV1::new(2)?;
    mutations[2].snapshot_digest = ContractDigestV1::from_digest(Digest32::of_bytes(b"other"))?;
    mutations[3].hops = 4;
    mutations[4].cell_digests.push(ContractDigestV1::from_digest(Digest32::of_bytes(b"third-cell"))?);
    for changed in mutations {
        assert_eq!(
            revalidate_memory_readout_v1(&request, &changed, readout.generation, owner.snapshot, &owner),
            Err(HnmfContractError::Conflict("memory request/snapshot binding"))
        );
    }
    assert!(owner.checked.borrow().is_empty());
    Ok(())
}

#[test]
fn foreign_scope_entity_or_revoked_support_fails_closed() -> Result<(), HnmfContractError> {
    let (request, readout, mut owner) = fixture()?;
    let mut foreign_scope = request.clone();
    foreign_scope.scope = ContractIdV1::new("workspace:other")?;
    let mut foreign_entity = request.clone();
    foreign_entity.entity = ContractIdV1::new("sensor:other")?;
    for changed in [foreign_scope, foreign_entity] {
        assert_eq!(
            revalidate_memory_readout_v1(&changed, &readout, readout.generation, owner.snapshot, &owner),
            Err(HnmfContractError::Conflict("source owner denied"))
        );
    }
    owner.checked.borrow_mut().clear();
    owner.live_sources.pop();
    assert_eq!(
        revalidate_memory_readout_v1(&request, &readout, readout.generation, owner.snapshot, &owner),
        Err(HnmfContractError::Conflict("source owner denied"))
    );
    assert_eq!(*owner.checked.borrow(), readout.source_ids);
    Ok(())
}

#[test]
fn an_unavailable_readout_cannot_supply_context() -> Result<(), HnmfContractError> {
    let (request, mut readout, owner) = fixture()?;
    readout.status = MemoryReadStatusV1::Stale;
    let _ = readout.value.take();
    readout.source_ids.clear();
    readout.cell_digests.clear();
    readout.prediction_kind = MemoryPredictionKindV1::None;
    readout.reason = Some("source revoked".to_owned());
    assert_eq!(
        revalidate_memory_readout_v1(&request, &readout, readout.generation, owner.snapshot, &owner),
        Err(HnmfContractError::Invalid("memory result unavailable"))
    );
    assert!(owner.checked.borrow().is_empty());
    Ok(())
}
