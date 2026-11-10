//! Bounded canonical storage only; decoded bytes never construct sealed task
//! receipts, authentication, model grants or learning evidence.

use super::*;

pub(super) fn configuration(
    identity: &AgentdIdentity,
    fence: &TaskFlowFence,
    registry: &CircuitCellRegistryV1,
    sources: Vec<CircuitTaskSourceInputV1>,
) -> Result<(BTreeMap<String, CircuitTaskSourceInputV1>, Digest32), Error> {
    let definition = registry.definition();
    if !(1..=64).contains(&sources.len())
        || identity.spawn_generation == 0
        || fence.owner_agent_id != identity.agent_id
        || fence.generation == 0
        || fence.owner_epoch == 0
        || [&fence.owner_id, &fence.fencing_token]
            .iter()
            .any(|s| s.is_empty() || s.len() > 128 || s.chars().any(char::is_control))
        || definition.programs.len() != 1
        || definition.programs[0].nodes.len() > 16
    {
        return Err(Error::InvalidBinding);
    }
    let program = &definition.programs[0];
    if program.program_id != definition.entry_program
        || program.nodes.iter().any(|node| match node.kind {
            CircuitNodeKindV2::Compute { .. } | CircuitNodeKindV2::Decide { .. } => {
                node.node_id != program.entry_node
            }
            CircuitNodeKindV2::Exit { .. } => node.node_id == program.entry_node,
            CircuitNodeKindV2::Subcircuit { .. } | CircuitNodeKindV2::Join { .. } => true,
        })
        || program
            .edges
            .iter()
            .any(|edge| edge.from != program.entry_node || edge.feedback_delay_ms.is_some())
    {
        return Err(Error::InvalidBinding);
    }
    let mut registered = BTreeMap::new();
    for source in sources {
        if source.scope.agent_id.as_str() != identity.agent_id.as_str()
            || !(1..=3_600_000).contains(&source.lease_duration_ms)
            || source
                .deadline_micros
                .saturating_sub(source.monotonic_micros)
                > source.lease_duration_ms * 1_000
        {
            return Err(Error::InvalidBinding);
        }
        encode_input(
            &source.input(StableId::new("circuit-source").map_err(|_| Error::InvalidBinding)?),
        )?;
        if registered
            .insert(source.scope.run_id.to_string(), source)
            .is_some()
        {
            return Err(Error::InvalidBinding);
        }
    }
    let mut bytes = b"hepta.circuit.original-source-owner.v1\0".to_vec();
    blob(&mut bytes, identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    for path in [
        &identity.fleet_root,
        &identity.workspace,
        &identity.home_root,
        &identity.run_root,
        &identity.control_socket,
        &identity.app_server_socket,
    ] {
        blob(&mut bytes, path.as_os_str().as_encoded_bytes());
    }
    blob(&mut bytes, &json(&identity.resources)?);
    blob(&mut bytes, &json(fence)?);
    blob(&mut bytes, registry.definition_digest().as_str().as_bytes());
    for source in registered.values() {
        blob(
            &mut bytes,
            &encode_input(
                &source.input(StableId::new("circuit-source").map_err(|_| Error::InvalidBinding)?),
            )?,
        );
        bytes.extend_from_slice(&source.lease_duration_ms.to_be_bytes());
    }
    Ok((registered, Digest32::of_bytes(&bytes)))
}

fn request_identity(request: &CircuitTaskRequestV1) -> Result<Vec<u8>, Error> {
    json(&(
        &request.start,
        request.objective_digest.to_string(),
        request.deadline_ms,
    ))
}

pub(super) fn request(
    request: &CircuitTaskRequestV1,
    record: &RunStartRecordV1,
) -> Result<Vec<u8>, Error> {
    let mut bytes = b"HCSTREQ1".to_vec();
    blob(&mut bytes, &request_identity(request)?);
    let a = &record.authentication;
    let d = &record.admission;
    let s = &record.snapshot;
    for id in [&a.issuer_id, &a.message_id, &d.profile_id, &s.run_id] {
        blob(&mut bytes, id.as_str().as_bytes());
    }
    for value in [
        a.key_epoch,
        a.sequence,
        a.expires_at_ms,
        d.profile_revision,
        d.observed_at_unix_micros,
        d.deadline_unix_micros,
        s.authority_epoch,
        s.generation,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    for digest in [
        a.scope_digest,
        a.signed_body_digest,
        d.profile_digest,
        d.supplied_source_digest,
        d.intent_digest,
        d.admitted_source_digest,
        s.objective_digest,
        s.hard_constraint_digest,
        s.preference_state_digest,
        s.model_tuple_digest,
        s.prompt_registry_digest,
        s.artifact_set_digest,
        s.fence_digest,
        record.runtime_body_digest,
        record.objective_function_v1_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&a.signature);
    if d.authority.grants_any()
        || record.disposition
            != codex_hepta_learning_ledger::RunStartObjectiveDispositionV1::Compiled
        || record.objective_semantic_bytes.is_empty()
        || record.objective_function_v1_bytes.is_empty()
        || Digest32::of_bytes(&record.objective_semantic_bytes) != s.objective_digest
        || Digest32::of_bytes(&record.objective_function_v1_bytes)
            != record.objective_function_v1_digest
    {
        return Err(Error::InvalidBinding);
    }
    // Only Compiled/DENY_ALL are admitted by this profile; no flag is omitted.
    bytes.extend_from_slice(&[0, 0]);
    blob(&mut bytes, &record.objective_semantic_bytes);
    blob(&mut bytes, &record.objective_function_v1_bytes);
    bounded(&bytes)?;
    Ok(bytes)
}

pub(super) fn require_request(bytes: &[u8], request: &CircuitTaskRequestV1) -> Result<(), Error> {
    let mut reader = Reader::new(bytes, b"HCSTREQ1")?;
    if reader.blob()? != request_identity(request)? {
        return Err(Error::InvalidBinding);
    }
    Ok(())
}

/// Recover the original complete record from our anchored request frame. The
/// caller must still recompute the request and compare all canonical bytes.
pub(super) fn original_record(bytes: &[u8]) -> Result<RunStartRecordV1, Error> {
    use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
    use codex_hepta_learning_ledger::RunStartAuthenticationV1;
    use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
    use codex_hepta_learning_ledger::RunStartSnapshotV1;
    let mut r = Reader::new(bytes, b"HCSTREQ1")?;
    r.blob()?; // Derived request, revalidated by read_publication.
    let issuer_id = r.id()?;
    let message_id = r.id()?;
    let profile_id = r.id()?;
    let run_id = r.id()?;
    let key_epoch = u64::from_be_bytes(r.take()?);
    let sequence = u64::from_be_bytes(r.take()?);
    let expires_at_ms = u64::from_be_bytes(r.take()?);
    let profile_revision = u64::from_be_bytes(r.take()?);
    let observed_at_unix_micros = u64::from_be_bytes(r.take()?);
    let deadline_unix_micros = u64::from_be_bytes(r.take()?);
    let authority_epoch = u64::from_be_bytes(r.take()?);
    let generation = u64::from_be_bytes(r.take()?);
    let scope_digest = r.digest()?;
    let signed_body_digest = r.digest()?;
    let profile_digest = r.digest()?;
    let supplied_source_digest = r.digest()?;
    let intent_digest = r.digest()?;
    let admitted_source_digest = r.digest()?;
    let objective_digest = r.digest()?;
    let hard_constraint_digest = r.digest()?;
    let preference_state_digest = r.digest()?;
    let model_tuple_digest = r.digest()?;
    let prompt_registry_digest = r.digest()?;
    let artifact_set_digest = r.digest()?;
    let fence_digest = r.digest()?;
    let runtime_body_digest = r.digest()?;
    let objective_function_v1_digest = r.digest()?;
    let signature = r.take()?;
    if r.take::<2>()? != [0, 0] {
        return Err(Error::InvalidBinding);
    }
    let objective_semantic_bytes = r.blob()?.to_vec();
    let objective_function_v1_bytes = r.blob()?.to_vec();
    r.end()?;
    Ok(RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id,
            key_epoch,
            message_id,
            sequence,
            expires_at_ms,
            scope_digest,
            signed_body_digest,
            signature,
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id,
            profile_revision,
            profile_digest,
            supplied_source_digest,
            intent_digest,
            admitted_source_digest,
            observed_at_unix_micros,
            deadline_unix_micros,
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id,
            objective_digest,
            hard_constraint_digest,
            preference_state_digest,
            model_tuple_digest,
            prompt_registry_digest,
            artifact_set_digest,
            authority_epoch,
            generation,
            fence_digest,
        },
        runtime_body_digest,
        objective_semantic_bytes,
        objective_function_v1_digest,
        objective_function_v1_bytes,
    })
}

pub(super) fn dispatch_input(
    dispatch: &CircuitDispatchV2,
    input: &CellStepInputV1,
) -> Result<Vec<u8>, Error> {
    let mut bytes = b"HCSTINP1".to_vec();
    blob(&mut bytes, &json(dispatch)?);
    blob(&mut bytes, &encode_input(input)?);
    bounded(&bytes)?;
    Ok(bytes)
}

fn encode_input(input: &CellStepInputV1) -> Result<Vec<u8>, Error> {
    if input.scope.principal_digest.is_zero()
        || input.source_frontier.is_zero()
        || input.objective_digest.is_zero()
        || input.ndu_snapshot_digest.is_zero()
        || input.monotonic_micros == 0
        || input.deadline_micros <= input.monotonic_micros
        || input.observation.is_empty()
        || input.observation.len() > 32 * 1_024
        || !(1..=64).contains(&input.candidates.len())
        || input.candidates.iter().enumerate().any(|(i, c)| {
            input.candidates[..i]
                .iter()
                .any(|p| p.candidate_id == c.candidate_id)
        })
    {
        return Err(Error::InvalidBinding);
    }
    let mut bytes = Vec::new();
    for id in [
        &input.operation_id,
        &input.scope.agent_id,
        &input.scope.cell_id,
        &input.scope.run_id,
    ] {
        blob(&mut bytes, id.as_str().as_bytes());
    }
    for digest in [
        input.scope.principal_digest,
        input.source_frontier,
        input.objective_digest,
        input.ndu_snapshot_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&input.monotonic_micros.to_be_bytes());
    bytes.extend_from_slice(&input.deadline_micros.to_be_bytes());
    blob(&mut bytes, &input.observation);
    bytes.extend_from_slice(&(input.candidates.len() as u32).to_be_bytes());
    for mask in &input.candidates {
        blob(&mut bytes, mask.candidate_id.as_str().as_bytes());
        bytes.push(u8::from(mask.allowed));
    }
    bounded(&bytes)?;
    Ok(bytes)
}

pub(super) fn decode_input(bytes: &[u8]) -> Result<CellStepInputV1, Error> {
    let mut outer = Reader::new(bytes, b"HCSTINP1")?;
    outer.blob()?; // Original serialized dispatch, compared in resolve/publish.
    let encoded = outer.blob()?;
    outer.end()?;
    let mut r = Reader(encoded);
    let input = CellStepInputV1 {
        operation_id: r.id()?,
        scope: CellScopeV1 {
            agent_id: r.id()?,
            cell_id: r.id()?,
            run_id: r.id()?,
            principal_digest: r.digest()?,
        },
        source_frontier: r.digest()?,
        objective_digest: r.digest()?,
        ndu_snapshot_digest: r.digest()?,
        monotonic_micros: u64::from_be_bytes(r.take()?),
        deadline_micros: u64::from_be_bytes(r.take()?),
        observation: r.blob()?.to_vec(),
        candidates: {
            let count = u32::from_be_bytes(r.take()?);
            if !(1..=64).contains(&count) {
                return Err(Error::InvalidBinding);
            }
            let mut masks = Vec::with_capacity(count as usize);
            for _ in 0..count {
                let candidate_id = r.id()?;
                let allowed = match r.take::<1>()? {
                    [0] => false,
                    [1] => true,
                    _ => return Err(Error::InvalidBinding),
                };
                masks.push(CellCandidateMaskV1 {
                    candidate_id,
                    allowed,
                });
            }
            masks
        },
    };
    r.end()?;
    if encode_input(&input)? != encoded {
        return Err(Error::InvalidBinding);
    }
    Ok(input)
}

pub(super) fn result(
    definition: &BoundedCircuitDefinitionV2,
    request: &CircuitTaskRequestV1,
    saved_input: &[u8],
    input: &CellStepInputV1,
    receipt: &CircuitTaskReceiptV1,
) -> Result<Vec<u8>, Error> {
    let trace = receipt.trace();
    let dispatches = trace.run().completed_computation_dispatches(definition)?;
    if trace.run().run_id() != request.start.run_id
        || trace.run().outcome().is_none()
        || trace.run().unresolved() != 0
        || receipt.executions().len() != 1
        || trace.completions().len() != 1
        || dispatches.len() != 1
        || dispatch_input(&dispatches[0], input)? != saved_input
    {
        return Err(Error::InvalidBinding);
    }
    let execution = receipt
        .executions()
        .get(&dispatches[0].activation_id)
        .ok_or(Error::InvalidBinding)?;
    let decision = &execution.decision;
    let decision_bytes = crate::circuit_cell_output::encode_receipt(decision)?;
    // The Circuit completion authenticates the invocation and semantic output
    // together with the decision, exactly as circuit_cell::finish publishes it.
    let mut completion_bytes = b"hepta.circuit.cell-completion.v1\0".to_vec();
    completion_bytes.extend_from_slice(dispatches[0].invocation_digest.as_str().as_bytes());
    completion_bytes.extend_from_slice(execution.completion.output_digest.as_str().as_bytes());
    completion_bytes.extend_from_slice(&decision_bytes);
    if decision.scope != input.scope
        || decision.operation_id != input.operation_id
        || decision.source_frontier != input.source_frontier
        || trace.completions().get(&dispatches[0].activation_id) != Some(&execution.completion)
        || execution.completion.output_digest != Sha256Digest::for_bytes(&execution.output)
        || execution.completion.receipt_digest != Sha256Digest::for_bytes(&completion_bytes)
    {
        return Err(Error::InvalidBinding);
    }
    decision
        .representation
        .validate()
        .map_err(crate::CircuitCellErrorV1::from)?;
    let mut bytes = b"HCSTRES1".to_vec();
    blob(&mut bytes, saved_input);
    blob(&mut bytes, trace.history_digest().as_str().as_bytes());
    blob(&mut bytes, &execution.output);
    blob(&mut bytes, &json(&(trace.run(), trace.completions()))?);
    blob(&mut bytes, &decision_bytes);
    blob(
        &mut bytes,
        &json(&(
            &decision.representation.drive_q24,
            &decision.representation.prediction_q24,
        ))?,
    );
    bounded(&bytes)?;
    Ok(bytes)
}

pub(super) fn publication(bytes: &[u8], input: &[u8]) -> Result<(Sha256Digest, Vec<u8>), Error> {
    let mut r = Reader::new(bytes, b"HCSTRES1")?;
    if r.blob()? != input {
        return Err(Error::InvalidBinding);
    }
    let history =
        Sha256Digest::parse(std::str::from_utf8(r.blob()?).map_err(|_| Error::InvalidBinding)?)
            .map_err(|_| Error::InvalidBinding)?;
    let output = r.blob()?.to_vec();
    for _ in 0..3 {
        if r.blob()?.is_empty() {
            return Err(Error::InvalidBinding);
        }
    }
    r.end()?;
    if output.is_empty() {
        return Err(Error::InvalidBinding);
    }
    Ok((history, output))
}

pub(super) fn require_decision(
    bytes: &[u8],
    decision: &codex_hepta_neuron::CellDecisionReceiptV1,
) -> Result<(), Error> {
    let mut r = Reader::new(bytes, b"HCSTRES1")?;
    for _ in 0..4 {
        r.blob()?;
    }
    if r.blob()? != crate::circuit_cell_output::encode_receipt(decision)?
        || r.blob()?
            != json(&(
                &decision.representation.drive_q24,
                &decision.representation.prediction_q24,
            ))?
    {
        return Err(Error::InvalidBinding);
    }
    r.end()
}

pub(super) fn decision_metadata(bytes: &[u8]) -> Result<(Digest32, Digest32), Error> {
    let mut r = Reader::new(bytes, b"HCSTRES1")?;
    for _ in 0..4 {
        r.blob()?;
    }
    let decision = r.blob()?;
    let mut d = Reader(
        decision
            .strip_prefix(b"hepta.circuit.committed-cell-decision.v1\0")
            .ok_or(Error::InvalidBinding)?,
    );
    for _ in 0..5 {
        d.id()?;
    }
    for _ in 0..3 {
        d.digest()?;
    }
    let bundle = d.digest()?;
    d.digest()?; // Original source frontier.
    d.digest()?; // Original checkpoint before this committed step.
    let checkpoint = d.digest()?;
    if bundle.is_zero() || checkpoint.is_zero() {
        return Err(Error::InvalidBinding);
    }
    Ok((bundle, checkpoint))
}

pub(super) fn bounded(bytes: &[u8]) -> Result<(), Error> {
    if bytes.is_empty() || bytes.len() > 65_536 {
        return Err(Error::InvalidBinding);
    }
    Ok(())
}

fn json(value: &impl serde::Serialize) -> Result<Vec<u8>, Error> {
    serde_json::to_vec(value).map_err(|_| Error::InvalidBinding)
}

fn blob(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
}

struct Reader<'a>(&'a [u8]);
impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8], magic: &[u8; 8]) -> Result<Self, Error> {
        bounded(bytes)?;
        Ok(Self(
            bytes.strip_prefix(magic).ok_or(Error::InvalidBinding)?,
        ))
    }
    fn take<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        let (value, remaining) = self.0.split_at_checked(N).ok_or(Error::InvalidBinding)?;
        self.0 = remaining;
        value.try_into().map_err(|_| Error::InvalidBinding)
    }
    fn blob(&mut self) -> Result<&'a [u8], Error> {
        let count = u32::from_be_bytes(self.take()?) as usize;
        let (value, remaining) = self
            .0
            .split_at_checked(count)
            .ok_or(Error::InvalidBinding)?;
        self.0 = remaining;
        Ok(value)
    }
    fn id(&mut self) -> Result<StableId, Error> {
        StableId::new(std::str::from_utf8(self.blob()?).map_err(|_| Error::InvalidBinding)?)
            .map_err(|_| Error::InvalidBinding)
    }
    fn digest(&mut self) -> Result<Digest32, Error> {
        Ok(Digest32::from_array(self.take()?))
    }
    fn end(self) -> Result<(), Error> {
        if self.0.is_empty() {
            Ok(())
        } else {
            Err(Error::InvalidBinding)
        }
    }
}
