use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::workspace;

#[tokio::test]
async fn exhausted_grant_history_can_still_be_revoked_and_reopened() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(80);
    let consumer_id = agent_id(81);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let access = CognitiveAccess::agent_private(owner_id.clone());
    let consumer_workspace = workspace("long-running-consumer");
    let scope = FederationGrantScope::new(CognitiveScope::AgentPrivate, consumer_workspace.clone());
    let mut final_grant = None;
    for revision in 1..MAX_FEDERATION_CAPABILITY_REVISIONS {
        let start = i64::try_from(revision).expect("bounded revision") * 2;
        let grant = owner
            .grant_federated_recall(
                &access,
                &FederationGrantRequest {
                    consumer_agent_id: consumer_id.clone(),
                    scope: scope.clone(),
                    effective_at_unix_seconds: start,
                    expires_at_unix_seconds: start + 1,
                },
            )
            .await
            .expect("bounded grant");
        assert_eq!(grant.revision(), revision);
        final_grant = Some(grant);
    }
    let grant = final_grant.expect("last grant");
    let now = grant.effective_at_unix_seconds();
    let consumer_access = FederationConsumerAccess::new(consumer_id.clone(), consumer_workspace);
    let readers = FederatedMemoryReader::discover(&owner_layout, &consumer_id, now)
        .await
        .expect("discover final grant");
    assert_eq!(readers.len(), 1);
    let next_grant = FederationGrantRequest {
        consumer_agent_id: consumer_id.clone(),
        scope,
        effective_at_unix_seconds: now + 2,
        expires_at_unix_seconds: now + 3,
    };
    assert!(matches!(
        owner.grant_federated_recall(&access, &next_grant).await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    assert!(matches!(
        owner
            .revoke_federated_recall(
                &CognitiveAccess::agent_private(consumer_id.clone()),
                &grant,
                now,
            )
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    let revoked = owner
        .revoke_federated_recall(&access, &grant, now)
        .await
        .expect("capacity cannot prevent revocation");
    assert_eq!(revoked.revision, MAX_FEDERATION_CAPABILITY_REVISIONS);
    assert_eq!(
        readers[0]
            .validate_capability(&consumer_access, now)
            .await
            .expect("revalidate"),
        Some(FederationRevalidationDrift::Revoked)
    );
    drop(readers);
    drop(owner);

    let reopened = CognitiveStore::open(&owner_layout).await.expect("reopen");
    let status = reopened
        .federation_capability_status(grant.id())
        .await
        .expect("decode terminal revocation")
        .expect("retained capability");
    assert_eq!(status.state, FederationCapabilityState::Revoked);
    assert_eq!(status.capability.revision(), revoked.revision);
    assert_eq!(
        reopened.list_federation_capabilities(1).await.expect("list"),
        vec![status]
    );
    assert!(matches!(
        reopened.grant_federated_recall(&access, &next_grant).await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    assert!(
        FederatedMemoryReader::discover(&owner_layout, &consumer_id, now)
            .await
            .expect("discover after restart")
            .is_empty()
    );
}
