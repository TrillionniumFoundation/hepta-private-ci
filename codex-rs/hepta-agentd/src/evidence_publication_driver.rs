// Included in evidence_production.rs to reuse the same private production
// validators. This command runs before daemon attachment, including recovery
// when newer local appends prevent normal exact-frontier startup.

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidencePublicationRequestV1 {
    schema_version: u32,
    request: EvidencePublicationActionV1,
}

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum EvidencePublicationActionV1 {
    Prepare {
        maximum_intents: usize,
    },
    Publish {
        batch_id: String,
        frontier_file: PathBuf,
    },
}

impl AgentdIdentity {
    /// Execute one owner-controlled production publication or reconciliation.
    ///
    /// The request and descriptor must be private owner files. Frontier values
    /// must be signed externally; this method never creates a key or signature.
    /// It can run before daemon startup, but cannot bootstrap an unaccepted store
    /// or change the admitted source, executable, backend or trust policies.
    pub async fn run_evidence_publication_request(
        &self,
        request_file: &Path,
        descriptor_file: &Path,
        issuer_trust_file: &Path,
        signer_trust_file: &Path,
    ) -> Result<String, AgentdError> {
        let request_bytes = read_owner_file(request_file, self)?;
        let request: EvidencePublicationRequestV1 = serde_json::from_slice(&request_bytes)?;
        if request.schema_version != 1 {
            return Err(recovery_required("unsupported publication request schema"));
        }
        let descriptor_bytes = read_owner_file(descriptor_file, self)?;
        let config: EvidenceProductionConfigV1 = serde_json::from_slice(&descriptor_bytes)?;
        config.validate(self)?;
        let roles = [request_file, descriptor_file, issuer_trust_file, signer_trust_file];
        if roles.into_iter().collect::<BTreeSet<_>>().len() != roles.len() {
            return Err(recovery_required("publication control files must be role-distinct"));
        }
        let home = codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&self.home_root)?;
        let sqlite = codex_state::SqliteConfig::from_sqlite_home(home);
        let store = HeptaEvidenceStore::open_existing_runtime(&sqlite)
            .await
            .map_err(evidence_error)?;
        let result = execute_publication_request(
            self,
            &store,
            &config,
            &EvidencePublicationFiles {
                descriptor_bytes: &descriptor_bytes,
                descriptor_file,
                issuer_trust_file,
                signer_trust_file,
            },
            request.request,
        )
        .await;
        store.close().await;
        result
    }
}

struct EvidencePublicationFiles<'a> {
    descriptor_bytes: &'a [u8],
    descriptor_file: &'a Path,
    issuer_trust_file: &'a Path,
    signer_trust_file: &'a Path,
}

async fn execute_publication_request(
    identity: &AgentdIdentity,
    store: &HeptaEvidenceStore,
    config: &EvidenceProductionConfigV1,
    files: &EvidencePublicationFiles<'_>,
    action: EvidencePublicationActionV1,
) -> Result<String, AgentdError> {
    use codex_hepta_evidence::EvidenceFrontierHistoryRangeV1;

    let EvidencePublicationFiles {
        descriptor_bytes, descriptor_file, issuer_trust_file, signer_trust_file,
    } = *files;

    // An existing accepted digest is the root of this continuation. Selecting a
    // different private signer file cannot establish a replacement authority.
    let accepted = store.latest_accepted_frontier(&config.store_id).await
        .map_err(evidence_error)?
        .ok_or_else(|| recovery_required("publication cannot bootstrap frontier authority"))?;
    if accepted.backend_identity_sha256 != config.backend_identity_sha256 {
        return Err(recovery_required("publication backend differs from accepted backend"));
    }
    let mut backend = LockedFileEvidenceFrontierBackend::open_external(
        &config.external_backend_root,
        config.backend_identity_sha256.clone(),
        &identity.home_root,
    ).map_err(backend_error)?;
    let history = backend.get_history(
        &config.store_id,
        EvidenceFrontierHistoryRangeV1::new(accepted.frontier_generation, accepted.frontier_generation)
            .map_err(backend_error)?,
    ).map_err(backend_error)?;
    let [predecessor] = history.as_slice() else {
        return Err(recovery_required("accepted frontier is missing from external history"));
    };
    if evidence_recovery_frontier_v2_sha256(predecessor).map_err(evidence_error)?
        != accepted.frontier_sha256
    {
        return Err(recovery_required("external history conflicts with accepted frontier"));
    }
    let signer_bytes = read_external_private_file(
        signer_trust_file, &config.external_backend_root, identity, MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let signer_trust = EvidenceFrontierSignerTrustV2::parse(&signer_bytes)?;
    if Sha256Digest::for_bytes(&signer_bytes) != predecessor.frontier_signer_registry_sha256 {
        return Err(recovery_required("publication cannot replace the admitted signer registry"));
    }
    signer_trust.verify(predecessor)?;
    require_authenticated_snapshot(predecessor)?;
    let issuer = VerifiedEvidenceTrustSnapshot::load_owner_registry(
        store, issuer_trust_file, identity.agent_id.as_str(),
        Some(&predecessor.issuer_trust_registry_sha256),
    ).map_err(evidence_error)?;
    if !issuer.is_monotonic() || issuer.registry_generation() == 0 {
        return Err(recovery_required("publication requires monotonic issuer trust"));
    }
    let exact_bytes = read_external_private_file(
        &config.exact_source_receipt_file, &config.external_backend_root, identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let merge_bytes = read_external_private_file(
        &config.merge_candidate_receipt_file, &config.external_backend_root, identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let source = validate_qualification_receipts(&exact_bytes, &merge_bytes)?;
    let receipts = qualification_receipt_set_sha256(
        &Sha256Digest::for_bytes(&exact_bytes), &Sha256Digest::for_bytes(&merge_bytes),
    );
    if predecessor.source_commit != source.source_commit
        || predecessor.source_tree != source.source_tree
        || predecessor.qualification_receipt_sha256 != receipts
        || predecessor.build_artifact_sha256 != current_executable_sha256()?
    {
        return Err(recovery_required("publication cannot replace source, qualification or executable"));
    }
    let owner_identity = format!("{}:{}", identity.agent_id.as_str(), identity.spawn_generation);
    let owner_id = format!("evidence.publisher:{}", Sha256Digest::for_bytes(owner_identity.as_bytes()).as_str());
    let lease = store.claim_publication_owner(&owner_id, current_time_millis()?, 120_000)
        .await.map_err(evidence_error)?;
    match action {
        EvidencePublicationActionV1::Prepare { maximum_intents } => {
            let batch = store.prepare_publication_batch(&lease, current_time_millis()?, maximum_intents)
                .await.map_err(evidence_error)?;
            Ok(serde_json::to_string(&batch)?)
        }
        EvidencePublicationActionV1::Publish { batch_id, frontier_file } => {
            let batch = store.publication_batch(&batch_id).await.map_err(evidence_error)?
                .ok_or_else(|| recovery_required("publication batch does not exist"))?;
            let proposal_bytes = read_external_private_file(
                &frontier_file, &config.external_backend_root, identity,
                MAX_EXTERNAL_CONTROL_FILE_BYTES,
            )?;
            let proposed: EvidenceRecoveryFrontierV2 = serde_json::from_slice(&proposal_bytes)?;
            proposed.validate_structure().map_err(evidence_error)?;
            require_authenticated_snapshot(&proposed)?;
            validate_publication_continuation(&batch, predecessor, &proposed)?;
            signer_trust.verify(&proposed)?;
            let now = current_time_millis()?;
            if proposed.created_at_unix_ms > now.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS)
                || now.saturating_sub(proposed.created_at_unix_ms) > config.frontier_max_age_ms
            {
                return Err(recovery_required("publication frontier is outside its freshness window"));
            }
            let backup_bytes = read_external_private_file(
                &config.backup_publication_receipt_file, &config.external_backend_root,
                identity, MAX_EXTERNAL_CONTROL_FILE_BYTES,
            )?;
            if Sha256Digest::for_bytes(&backup_bytes) != proposed.backup_publication_sha256 {
                return Err(recovery_required("publication backup witness digest differs"));
            }
            let backup: EvidenceBackupPublicationReceiptV1 = serde_json::from_slice(&backup_bytes)?;
            validate_backup_publication(&backup, &proposed, now, config.frontier_max_age_ms)?;
            let digest = evidence_recovery_frontier_v2_sha256(&proposed).map_err(evidence_error)?;
            // The exact operation identity is durable BEFORE any CAS can run.
            store.mark_publication_dispatched(
                &lease, &batch_id, &digest, &config.backend_identity_sha256, current_time_millis()?,
            ).await.map_err(evidence_error)?;
            if read_owner_file(descriptor_file, identity)?.as_slice() != descriptor_bytes
                || read_external_private_file(signer_trust_file, &config.external_backend_root,
                    identity, MAX_EXTERNAL_CONTROL_FILE_BYTES)? != signer_bytes
            {
                return Err(recovery_required("publication controls changed before dispatch"));
            }
            // Recovery re-fsyncs a matching stored record. A latest read alone
            // is never converted into a successful durability acknowledgement.
            let result = match backend.recover_durable_acknowledgement(
                &config.store_id, proposed.frontier_generation, &digest,
            ) {
                Ok(Some(ack)) => Ok(ack),
                Ok(None) => backend.compare_and_swap(
                    &config.store_id, batch.expected_frontier_generation, &proposed,
                ),
                Err(error) => Err(error),
            };
            let acknowledgement = match result {
                Ok(acknowledgement) => acknowledgement,
                Err(error) => {
                    // A failed local status update must not erase the durable
                    // Dispatching fence or replace the original backend error.
                    let status_result = store.mark_publication_indeterminate(
                        &lease, &batch_id, current_time_millis()?,
                    ).await;
                    return Err(recovery_required(&format!(
                        "publication unresolved: {error}; durable-status update: {status_result:?}"
                    )));
                }
            };
            // A changed/revoked policy or expired lease after external IO leaves
            // the SAME batch unresolved for a newly authorized reconciler.
            if read_external_private_file(signer_trust_file, &config.external_backend_root,
                identity, MAX_EXTERNAL_CONTROL_FILE_BYTES)? != signer_bytes
                || read_owner_file(descriptor_file, identity)?.as_slice() != descriptor_bytes
            {
                return Err(recovery_required("publication controls changed before acknowledgement"));
            }
            VerifiedEvidenceTrustSnapshot::load_owner_registry(
                store, issuer_trust_file, identity.agent_id.as_str(),
                Some(&predecessor.issuer_trust_registry_sha256),
            ).map_err(evidence_error)?;
            store.acknowledge_publication(&lease, &batch_id, &acknowledgement, current_time_millis()?)
                .await.map_err(evidence_error)?;
            Ok(serde_json::to_string(&acknowledgement)?)
        }
    }
}

fn validate_publication_continuation(
    batch: &codex_hepta_evidence::EvidencePublicationBatchV1,
    predecessor: &EvidenceRecoveryFrontierV2,
    proposed: &EvidenceRecoveryFrontierV2,
) -> Result<(), AgentdError> {
    let predecessor_digest = evidence_recovery_frontier_v2_sha256(predecessor).map_err(evidence_error)?;
    if batch.state != codex_hepta_evidence::EvidencePublicationBatchStateV1::Acknowledged
        && (batch.expected_frontier_generation != Some(predecessor.frontier_generation)
            || batch.expected_frontier_sha256.as_ref() != Some(&predecessor_digest)
            || batch.expected_backend_identity_sha256.as_ref()
                != Some(&predecessor.backend_identity_sha256))
    {
        return Err(recovery_required("publication predecessor differs from its durable preparation"));
    }
    if batch.store_id != predecessor.store_id
        || proposed.store_id != batch.store_id
        || proposed.frontier_generation != batch.proposed_frontier_generation
        || proposed.snapshot != batch.snapshot
        || proposed.source_commit != predecessor.source_commit
        || proposed.source_tree != predecessor.source_tree
        || proposed.issuer_trust_registry_sha256 != predecessor.issuer_trust_registry_sha256
        || proposed.frontier_signer_registry_sha256 != predecessor.frontier_signer_registry_sha256
        || proposed.signer_policy_generation != predecessor.signer_policy_generation
        || proposed.build_artifact_sha256 != predecessor.build_artifact_sha256
        || proposed.qualification_receipt_sha256 != predecessor.qualification_receipt_sha256
        || proposed.backend_identity_sha256 != predecessor.backend_identity_sha256
    {
        return Err(recovery_required("publication is not an exact admitted-domain continuation"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "evidence_publication_driver_tests.rs"]
mod publication_driver_tests;
