enum ArchiveModeV3 {
    ModelGeneration,
    GoalScope,
}
const GOAL_RECEIPT_DOMAIN_V3: &[u8] = b"hepta.agentd.goal-scope-archive-receipt.v3";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct GoalScopeArchiveReceiptV3 {
    version: u32,
    scope: AgentdNeuronGoalScopeV3,
    archive_digest: String,
    archive_bytes: u64,
    previous: AgentdNeuronGoalScopeArchiveFrontierV3,
}

impl GenerationArchiveStore {
    pub(super) fn open_goal_scopes_v3(
        control: &Path,
        maximum: u64,
    ) -> Result<Self, AgentdNeuronControlErrorV2> {
        Self::open_mode(control, maximum, ArchiveModeV3::GoalScope)
    }
    fn initialize_goal_frontier_v3(mut self) -> Result<Self, AgentdNeuronControlErrorV2> {
        let path = self.directory.join("goal-scope-frontier-v3.json");
        let frontier: AgentdNeuronGoalScopeArchiveFrontierV3 = if path.exists() {
            serde_json::from_slice(&read_private(&path, 4096)?)
                .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?
        } else {
            let empty = AgentdNeuronGoalScopeArchiveFrontierV3::default();
            let bytes = serde_json::to_vec(&empty)
                .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
            publish(
                &self.directory,
                "goal-scope-frontier-v3.json",
                &bytes,
                Publication::MutableFrontier,
            )?;
            empty
        };
        frontier.validate()?;
        self.goal_frontier = Some(frontier);
        let head = self.goal_frontier_v3()?;
        if head.last_scope_ordinal != 0 {
            let receipt = self.read_goal_receipt_v3(head.last_scope_ordinal)?;
            let bytes = serde_json::to_vec(&receipt)
                .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
            if receipt.previous.scope_count.checked_add(1) != Some(head.scope_count)
                || receipt
                    .previous
                    .total_bytes
                    .checked_add(receipt.archive_bytes)
                    .and_then(|total| total.checked_add(bytes.len() as u64))
                    != Some(head.total_bytes)
                || head.total_bytes > self.maximum_total_bytes
            {
                return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
            }
            self.read_goal_archive_v3(&receipt)?;
        }
        Ok(self)
    }
    pub(super) fn goal_frontier_v3(
        &self,
    ) -> Result<&AgentdNeuronGoalScopeArchiveFrontierV3, AgentdNeuronControlErrorV2> {
        self.goal_frontier
            .as_ref()
            .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)
    }
    pub(super) fn archived_goal_scope_v3(
        &self,
        ordinal: u64,
    ) -> Result<Option<AgentdNeuronGoalScopeV3>, AgentdNeuronControlErrorV2> {
        if ordinal == 0 || ordinal > self.goal_frontier_v3()?.last_scope_ordinal {
            return Ok(None);
        }
        let receipt = self.read_goal_receipt_v3(ordinal)?;
        self.read_goal_archive_v3(&receipt)?;
        Ok(Some(receipt.scope))
    }
    pub(super) fn commit_goal_scope_v3(
        &mut self,
        scope: &AgentdNeuronGoalScopeV3,
        archive: &NeuronGenerationArchiveV1,
    ) -> Result<(), AgentdNeuronControlErrorV2> {
        scope.validate().map_err(poison_control_state)?;
        if scope.identity.model_generation != archive.generation()
            || scope.identity.runtime_configuration_digest != archive.configuration_digest()
            || scope.identity.body_bundle_digest != archive.body_bundle_digest()
        {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        let head = self.goal_frontier_v3()?.clone();
        if scope.ordinal <= head.last_scope_ordinal {
            let receipt = self.read_goal_receipt_v3(scope.ordinal)?;
            return if receipt.scope == *scope
                && self.read_goal_archive_v3(&receipt)?.digest() == archive.digest()
            {
                Ok(())
            } else {
                Err(AgentdNeuronControlErrorV2::GenerationConflict)
            };
        }
        if head.last_scope_ordinal.checked_add(1) != Some(scope.ordinal) {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        let receipt = GoalScopeArchiveReceiptV3 {
            version: 3,
            scope: scope.clone(),
            archive_digest: archive.digest().to_string(),
            archive_bytes: archive.bytes().len() as u64,
            previous: head.clone(),
        };
        let bytes = serde_json::to_vec(&receipt)
            .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        let total = head
            .total_bytes
            .checked_add(receipt.archive_bytes)
            .and_then(|total| total.checked_add(bytes.len() as u64))
            .filter(|total| *total <= self.maximum_total_bytes)
            .ok_or(AgentdNeuronControlErrorV2::StoragePressure)?;
        publish(
            &self.directory,
            &format!("scope-{}.archive", scope.ordinal),
            archive.bytes(),
            Publication::Immutable,
        )?;
        publish(
            &self.directory,
            &format!("scope-{}.receipt-v3.json", scope.ordinal),
            &bytes,
            Publication::Immutable,
        )?;
        let frontier = AgentdNeuronGoalScopeArchiveFrontierV3 {
            schema_version: 3,
            last_scope_ordinal: scope.ordinal,
            scope_count: head
                .scope_count
                .checked_add(1)
                .ok_or(AgentdNeuronControlErrorV2::ControllerPoisoned)?,
            total_bytes: total,
            receipt_digest: Digest32::of_parts(&[GOAL_RECEIPT_DOMAIN_V3, &bytes]).to_string(),
        };
        publish(
            &self.directory,
            "goal-scope-frontier-v3.json",
            &serde_json::to_vec(&frontier)
                .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?,
            Publication::MutableFrontier,
        )?;
        self.goal_frontier = Some(frontier);
        Ok(())
    }
    pub(super) fn query_goal_scope_v3(
        &self,
        scope: &AgentdNeuronGoalScopeV3,
        tick_id: &StableId,
        digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        let receipt = self.read_goal_receipt_v3(scope.ordinal)?;
        if receipt.scope != *scope {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        self.read_goal_archive_v3(&receipt)?
            .query_operation(tick_id, digest)
            .map_err(AgentdNeuronControlErrorV2::Runtime)
    }
    fn read_goal_receipt_v3(
        &self,
        ordinal: u64,
    ) -> Result<GoalScopeArchiveReceiptV3, AgentdNeuronControlErrorV2> {
        let head = self.goal_frontier_v3()?;
        if ordinal == 0 || ordinal > head.last_scope_ordinal {
            return Err(AgentdNeuronControlErrorV2::UnknownGeneration);
        }
        let bytes = read_private(
            &self
                .directory
                .join(format!("scope-{ordinal}.receipt-v3.json")),
            4096,
        )?;
        let receipt: GoalScopeArchiveReceiptV3 = serde_json::from_slice(&bytes)
            .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        receipt.scope.validate().map_err(poison_control_state)?;
        receipt.previous.validate()?;
        if receipt.version != 3
            || receipt.scope.ordinal != ordinal
            || receipt.previous.last_scope_ordinal.checked_add(1) != Some(ordinal)
            || receipt.archive_bytes == 0
            || receipt.archive_bytes > MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1 as u64
            || ordinal == head.last_scope_ordinal
                && head.receipt_digest
                    != Digest32::of_parts(&[GOAL_RECEIPT_DOMAIN_V3, &bytes]).to_string()
        {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        Ok(receipt)
    }
    fn read_goal_archive_v3(
        &self,
        receipt: &GoalScopeArchiveReceiptV3,
    ) -> Result<NeuronGenerationArchiveV1, AgentdNeuronControlErrorV2> {
        let bytes = read_private(
            &self
                .directory
                .join(format!("scope-{}.archive", receipt.scope.ordinal)),
            receipt.archive_bytes,
        )?;
        let expected = receipt
            .archive_digest
            .parse()
            .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        let archive = NeuronGenerationArchiveV1::from_bytes(bytes, expected)
            .map_err(AgentdNeuronControlErrorV2::Runtime)?;
        if archive.generation() != receipt.scope.identity.model_generation
            || archive.configuration_digest() != receipt.scope.identity.runtime_configuration_digest
            || archive.body_bundle_digest() != receipt.scope.identity.body_bundle_digest
            || archive.bytes().len() as u64 != receipt.archive_bytes
        {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        Ok(archive)
    }
}
