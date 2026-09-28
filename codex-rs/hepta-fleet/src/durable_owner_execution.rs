//! Durable physical-use pins. Expiry/revocation retire authorization, not work.
use super::*;

const MAX_EXECUTION_HOLDS: usize = 32_768;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetExecutionContextV1 {
    pub principal_id: String,
    pub host_id: String,
    pub host_generation: u64,
    pub boot_identity: String,
    pub resources: ResourceVectorV1,
    pub execution_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetExecutionHoldV1 {
    pub effect_id: String,
    pub context: FleetExecutionContextV1,
    pub grant: AllocationGrant,
    pub revocation_snapshot_sha256: String,
    pub prepared_at_ms: u64,
}

/// Implemented by the selected-host process/containment driver, not a request.
/// A successful signal, a missing receipt, or lease expiry is not quiescence.
pub trait FleetQuiescenceProbe {
    fn is_quiescent(&self, hold: &FleetExecutionHoldV1) -> std::io::Result<bool>;
}

impl DurableFleetOwner {
    pub fn prepare_execution(
        &mut self,
        effect_id: &str,
        context: FleetExecutionContextV1,
        witness: &crate::RevocationBoundGrantUseWitnessV1,
    ) -> Result<FleetExecutionHoldV1, DurableFleetError> {
        validate_operation_id(effect_id)?;
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        if self.state.fleet_execution_holds.contains_key(effect_id)
            || self.state.fleet_execution_holds.len() >= MAX_EXECUTION_HOLDS
        {
            return Err(DurableFleetError::ExecutionAlreadyPrepared);
        }
        let incarnation = self
            .state
            .fleet_host_incarnations
            .get(&context.host_id)
            .ok_or(DurableFleetError::InvalidHostIncarnation)?;
        if incarnation.boot_identity != context.boot_identity
            || incarnation.host_generation != context.host_generation
            || !valid_digest(&context.execution_sha256)
        {
            return Err(DurableFleetError::ExecutionContextMismatch);
        }
        let snapshot = self
            .state
            .fleet_revocation_frontier
            .as_ref()
            .ok_or(DurableFleetError::ExecutionContextMismatch)?;
        if snapshot.semantic_digest()? != witness.revocation_snapshot_sha256 {
            return Err(DurableFleetError::ExecutionContextMismatch);
        }
        let ledger =
            LeaseLedger::from_snapshot(Arc::clone(&self.clock), self.state.fleet_grants.clone())?;
        let allocation_id = &witness.grant.allocation_id;
        let grant = self
            .state
            .fleet_grants
            .active_grants
            .get(allocation_id)
            .ok_or(DurableFleetError::ExecutionContextMismatch)?;
        let mut current = FleetAuthorityPort::verify_final_use(
            &ledger,
            allocation_id,
            witness.grant.lease_generation,
            &context.host_id,
            context.host_generation,
            &grant.semantic_digest,
        )?;
        // Compare the authority binding, not the two sampling timestamps.
        if witness.grant.verified_at_ms > current.verified_at_ms {
            return Err(DurableFleetError::ExecutionContextMismatch);
        }
        current.verified_at_ms = witness.grant.verified_at_ms;
        if current != witness.grant
            || grant.principal_id != context.principal_id
            || !context.resources.fits(grant.resources)
        {
            return Err(DurableFleetError::ExecutionContextMismatch);
        }
        // A new effect ID cannot turn one execution identity into a second
        // process or independently spend the allocation's full budget again.
        let mut demand = context.resources;
        for existing in self.state.fleet_execution_holds.values() {
            if existing.grant.allocation_id != *allocation_id {
                continue;
            }
            if existing.context.execution_sha256 == context.execution_sha256 {
                return Err(DurableFleetError::ExecutionAlreadyPrepared);
            }
            demand = demand
                .checked_add(existing.context.resources)
                .map_err(|_| DurableFleetError::ArithmeticOverflow)?;
        }
        if !demand.fits(grant.resources) {
            return Err(DurableFleetError::Ledger(
                crate::LeaseLedgerError::CapacityExceeded,
            ));
        }
        let hold = FleetExecutionHoldV1 {
            effect_id: effect_id.to_string(),
            context,
            grant: grant.clone(),
            revocation_snapshot_sha256: witness.revocation_snapshot_sha256.clone(),
            prepared_at_ms: self.clock.now_unix_ms()?,
        };
        let mut candidate = self.state.clone();
        candidate
            .fleet_execution_holds
            .insert(effect_id.to_string(), hold.clone());
        let digest = operation_digest(b"execution-prepared", &hold)?;
        let operation = FleetOperationReceiptV1 {
            operation_id: format!("execution-prepare-{digest}"),
            operation_kind: FleetOperationKindV1::ExecutionPrepared,
            operation_digest: digest,
            committed_generation: next_generation(self.state.generation)?,
            committed_at_ms: hold.prepared_at_ms,
            lease_receipt: None,
            authority_witness: None,
        };
        append_operation(&mut candidate, operation.clone())?;
        self.commit(candidate, operation)?;
        Ok(hold)
    }

    /// Release the allocation's physical pin only after every selected-host
    /// observation proves its containment group empty (or its old boot dead).
    pub fn reconcile_execution_group<P: FleetQuiescenceProbe>(
        &mut self,
        allocation_id: &str,
        probe: &P,
    ) -> Result<bool, DurableFleetError> {
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        let holds: Vec<_> = self
            .state
            .fleet_execution_holds
            .values()
            .filter(|hold| hold.grant.allocation_id == allocation_id)
            .cloned()
            .collect();
        if holds.is_empty() {
            return Ok(true);
        }
        for hold in &holds {
            if !probe.is_quiescent(hold)? {
                return Ok(false);
            }
        }
        let mut candidate = self.state.clone();
        for hold in &holds {
            candidate.fleet_execution_holds.remove(&hold.effect_id);
        }
        let digest = operation_digest(b"execution-quiesced", &(self.state.generation, &holds))?;
        let operation = FleetOperationReceiptV1 {
            operation_id: format!("execution-quiesced-{digest}"),
            operation_kind: FleetOperationKindV1::ExecutionQuiesced,
            operation_digest: digest,
            committed_generation: next_generation(self.state.generation)?,
            committed_at_ms: self.clock.now_unix_ms()?,
            lease_receipt: None,
            authority_witness: None,
        };
        append_operation(&mut candidate, operation.clone())?;
        self.commit(candidate, operation)?;
        Ok(true)
    }
}

pub(super) fn reserved_totals(
    state: &DurableFleetStateV1,
) -> Result<BTreeMap<String, ResourceVectorV1>, DurableFleetError> {
    if state.fleet_execution_holds.len() > MAX_EXECUTION_HOLDS {
        return Err(DurableFleetError::CorruptState);
    }
    let mut allocations: BTreeMap<&str, &AllocationGrant> = state
        .fleet_grants
        .active_grants
        .iter()
        .map(|(id, grant)| (id.as_str(), grant))
        .collect();
    let mut execution_identities = BTreeSet::new();
    let mut execution_demands: BTreeMap<&str, ResourceVectorV1> = BTreeMap::new();
    for (effect_id, hold) in &state.fleet_execution_holds {
        let grant = &hold.grant;
        if effect_id != &hold.effect_id
            || validate_operation_id(effect_id).is_err()
            || hold.context.principal_id != grant.principal_id
            || hold.context.host_id != grant.host_id
            || hold.context.host_generation != grant.host_generation
            || !valid_digest(&hold.context.boot_identity)
            || !valid_digest(&hold.context.execution_sha256)
            || !valid_digest(&hold.revocation_snapshot_sha256)
            || !valid_digest(&grant.semantic_digest)
            || grant.revoked
            || grant.host_generation == 0
            || grant.lease_generation == 0
            || !hold.context.resources.fits(grant.resources)
            || !execution_identities.insert((
                grant.allocation_id.as_str(),
                hold.context.execution_sha256.as_str(),
            ))
        {
            return Err(DurableFleetError::CorruptState);
        }
        let demand = execution_demands
            .get(grant.allocation_id.as_str())
            .copied()
            .unwrap_or_default()
            .checked_add(hold.context.resources)
            .map_err(|_| DurableFleetError::ArithmeticOverflow)?;
        if !demand.fits(grant.resources) {
            return Err(DurableFleetError::Ledger(
                crate::LeaseLedgerError::CapacityExceeded,
            ));
        }
        execution_demands.insert(grant.allocation_id.as_str(), demand);
        if let Some(existing) = allocations.get(grant.allocation_id.as_str()) {
            if existing.host_id != grant.host_id
                || existing.host_generation != grant.host_generation
                || existing.resources != grant.resources
                || existing.principal_id != grant.principal_id
                || existing.semantic_digest != grant.semantic_digest
            {
                return Err(DurableFleetError::ExecutionContextMismatch);
            }
        } else {
            allocations.insert(&grant.allocation_id, grant);
        }
    }
    let mut totals = BTreeMap::new();
    for grant in allocations.values() {
        let value = totals.get(&grant.host_id).copied().unwrap_or_default();
        let value = ResourceVectorV1::checked_add(value, grant.resources)
            .map_err(|_| DurableFleetError::ArithmeticOverflow)?;
        if !value.is_empty() {
            totals.insert(grant.host_id.clone(), value);
        }
    }
    Ok(totals)
}

pub(super) fn require_capacity(state: &DurableFleetStateV1) -> Result<(), DurableFleetError> {
    for (host_id, reserved) in reserved_totals(state)? {
        let capacity = state
            .fleet_capacity_observations
            .get(&host_id)
            .ok_or(DurableFleetError::CorruptState)?
            .capacity;
        if !reserved.fits(capacity) {
            return Err(DurableFleetError::Ledger(
                crate::LeaseLedgerError::CapacityExceeded,
            ));
        }
    }
    Ok(())
}
