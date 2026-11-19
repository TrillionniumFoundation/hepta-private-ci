use super::*;
use crate::ObjectiveAdmissionQuery;
use crate::ObjectiveAdmissionUnknownReason as Unknown;
use crate::ObjectiveJournalAnchor;
use crate::ObjectivePublicationOutcome;

fn identity(root: &Path) -> AgentdIdentity {
    let agent_id = codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
        .expect("agent");
    let fleet = codex_hepta_paths::HeptaFleetRoot::parse(root.join("fleet")).expect("fleet");
    let layout = fleet.layout().agent(&agent_id);
    AgentdIdentity {
        agent_id,
        spawn_generation: 7,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace: root.to_path_buf(),
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
        layout,
    }
}

fn retained(owner: &AgentdIdentity, name: &str) -> (ObjectiveAdmissionQuery, RunStartRecordV1) {
    let mut record = record(
        name,
        /*sequence*/ 7,
        RunStartObjectiveDispositionV1::Compiled,
    );
    let request = AuthBusObjectiveIngress {
        issuer_id: "issuer.objective".into(),
        key_epoch: 1,
        message_id: format!("message.{name}"),
        sequence: 7,
        expires_at_ms: 1,
        signature_hex: "07".repeat(64),
        body: AuthBusObjectiveBody {
            spawn_generation: 1,
            run_id: name.into(),
            objective_revision: 1,
            source_envelope_json: "{\"retained\":true}".into(),
            runtime_body_digest: digest("runtime").to_string(),
            preference_state_digest: digest("preference").to_string(),
            model_tuple_digest: digest("model").to_string(),
            prompt_registry_digest: digest("prompt").to_string(),
            artifact_set_digest: digest("artifact").to_string(),
            authority_epoch: 7,
        },
    };
    let claims = objective_claims(
        owner,
        &request,
        &objective_body_payload(&request.body).expect("payload"),
    )
    .expect("claims");
    record.authentication = RunStartAuthenticationV1 {
        issuer_id: claims.issuer_id,
        key_epoch: claims.key_epoch.get(),
        message_id: claims.message_id,
        sequence: claims.sequence,
        expires_at_ms: claims.expires_at_ms,
        scope_digest: claims.scope_digest,
        signed_body_digest: claims.payload_digest,
        signature: [7; 64],
    };
    (
        ObjectiveAdmissionQuery {
            request,
            anchor: None,
        },
        record,
    )
}

#[test]
fn expired_historical_request_matches_after_reopen_without_changing_journal() {
    let owner_root = tempfile::tempdir().expect("owner");
    let owner = identity(owner_root.path());
    let (query, record) = retained(&owner, "run.history");
    let (journal_root, state) = state_with(record);
    let publication = state
        .read_publication(&owner, digest("profile"), query.clone())
        .expect("publication");
    drop(state);
    let path = journal_root.path().join("journal");
    let before = std::fs::read(&path).expect("before");
    let journal = DurableRunStartJournal::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .expect("journal"),
        digest("binding"),
        /*max_records*/ 16,
        RunStartRecovery::Unacknowledged,
    )
    .expect("reopen");
    let state = ObjectiveHostState {
        highest_sequences: replay_frontier(&journal).expect("frontier"),
        journal,
    };
    assert_eq!(
        state.read_publication(&owner, digest("profile"), query),
        Ok(publication)
    );
    drop(state);
    assert_eq!(std::fs::read(path).expect("after"), before);
}

#[test]
fn history_requires_every_retained_authentication_and_body_field() {
    let root = tempfile::tempdir().expect("owner");
    let owner = identity(root.path());
    let (query, record) = retained(&owner, "run.history");
    let (_journal, state) = state_with(record);
    let original = serde_json::to_value(&query).expect("query json");
    for path in [
        "/request/issuer_id",
        "/request/key_epoch",
        "/request/message_id",
        "/request/sequence",
        "/request/expires_at_ms",
        "/request/signature_hex",
        "/request/body/spawn_generation",
        "/request/body/run_id",
        "/request/body/objective_revision",
        "/request/body/source_envelope_json",
        "/request/body/runtime_body_digest",
        "/request/body/preference_state_digest",
        "/request/body/model_tuple_digest",
        "/request/body/prompt_registry_digest",
        "/request/body/artifact_set_digest",
        "/request/body/authority_epoch",
    ] {
        let mut changed = original.clone();
        let field = changed.pointer_mut(path).expect("field");
        *field = match field {
            serde_json::Value::Number(value) => serde_json::json!(value.as_u64().expect("u64") + 1),
            serde_json::Value::String(value)
                if path.ends_with("digest") || path.ends_with("signature_hex") =>
            {
                serde_json::json!("a".repeat(value.len()))
            }
            serde_json::Value::String(value) => serde_json::json!(format!("{value}x")),
            _ => panic!("unexpected field"),
        };
        assert_eq!(
            state.read_publication(
                &owner,
                digest("profile"),
                serde_json::from_value(changed).expect("changed query")
            ),
            Err(Unknown::NoMatchingPublication),
            "{path}"
        );
    }
    assert_eq!(
        state.read_publication(&owner, digest("other profile"), query),
        Err(Unknown::NoMatchingPublication)
    );
}

#[test]
fn trusted_anchor_must_exist_match_and_cover_publication() {
    let root = tempfile::tempdir().expect("owner");
    let owner = identity(root.path());
    let (mut first_query, first) = retained(&owner, "run.first");
    let (mut second_query, second) = retained(&owner, "run.second");
    let (_journal, mut state) = state_with(first);
    let first_publication = state
        .journal
        .publication(&id("run.first"))
        .expect("lookup")
        .expect("first");
    let second_publication = state
        .journal
        .append(state.journal.head_digest(), second)
        .expect("second");
    first_query.anchor = Some(ObjectiveJournalAnchor {
        sequence: second_publication.sequence,
        chain_digest: second_publication.chain_digest.to_string(),
    });
    assert_eq!(
        state
            .read_publication(&owner, digest("profile"), first_query.clone())
            .expect("covered")
            .publication_digest,
        first_publication.record_digest.to_string()
    );
    second_query.anchor = Some(ObjectiveJournalAnchor {
        sequence: first_publication.sequence,
        chain_digest: first_publication.chain_digest.to_string(),
    });
    assert_eq!(
        state.read_publication(&owner, digest("profile"), second_query),
        Err(Unknown::PublicationOutsideAnchor)
    );
    for (sequence, chain_digest, expected) in [
        (0, second_publication.chain_digest, Unknown::InvalidQuery),
        (3, second_publication.chain_digest, Unknown::AnchorMissing),
        (2, digest("wrong chain"), Unknown::AnchorMismatch),
    ] {
        first_query.anchor = Some(ObjectiveJournalAnchor {
            sequence,
            chain_digest: chain_digest.to_string(),
        });
        assert_eq!(
            state.read_publication(&owner, digest("profile"), first_query.clone()),
            Err(expected)
        );
    }
}

#[test]
fn abstention_and_conflict_remain_distinct_historical_publications() {
    let root = tempfile::tempdir().expect("owner");
    let owner = identity(root.path());
    let (abstain_query, mut abstain) = retained(&owner, "run.abstain");
    abstain.disposition = RunStartObjectiveDispositionV1::ExplicitAbstain;
    let (_journal, mut state) = state_with(abstain.clone());
    let (conflict_query, conflict) = retained(&owner, "run.conflict");
    let receipt = b"owner conflict".to_vec();
    state
        .journal
        .append_conflict(
            state.journal.head_digest(),
            codex_hepta_learning_ledger::RunStartConflictRecordV1 {
                authentication: conflict.authentication,
                admission: conflict.admission,
                run_id: conflict.snapshot.run_id,
                runtime_body_digest: conflict.runtime_body_digest,
                conflict_digest: Digest32::of_bytes(&receipt),
                conflict_receipt_bytes: receipt.clone(),
            },
        )
        .expect("conflict");
    assert_eq!(
        state
            .read_publication(&owner, digest("profile"), abstain_query)
            .expect("abstain")
            .outcome,
        ObjectivePublicationOutcome::ExplicitAbstain {
            objective_digest: abstain.snapshot.objective_digest.to_string(),
            hard_constraint_digest: abstain.snapshot.hard_constraint_digest.to_string()
        }
    );
    assert_eq!(
        state
            .read_publication(&owner, digest("profile"), conflict_query)
            .expect("conflict")
            .outcome,
        ObjectivePublicationOutcome::Conflict {
            conflict_digest: Digest32::of_bytes(&receipt).to_string()
        }
    );
}
