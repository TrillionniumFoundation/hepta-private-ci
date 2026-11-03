use super::*;

use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::FederationGrantRequest;
use crate::FederationGrantScope;
use crate::MemoryDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

struct MutateAfterRead<'a> {
    transport: ProductReaderTransport<'a>,
    owner: &'a CognitiveStore,
    owner_access: &'a CognitiveAccess,
    capability: &'a FederationCapability,
    grant: &'a FederationGrantRequest,
    regrant: bool,
}

impl FederationTransportV2 for MutateAfterRead<'_> {
    fn send_once<'a>(&'a self, query: &'a FederatedQueryV2) -> FederationTransportFuture<'a> {
        Box::pin(async move {
            let response = self.transport.send_once(query).await?;
            let FederationTransportResultV2::Terminal(terminal) = &response else {
                panic!("actual memory read must finish before authority mutation");
            };
            assert_eq!(terminal.items.len(), 1);
            self.owner
                .revoke_federated_recall(self.owner_access, self.capability, 151)
                .await
                .expect("commit revoke after real read");
            if self.regrant {
                self.owner
                    .grant_federated_recall(self.owner_access, self.grant)
                    .await
                    .expect("commit new generation after real read");
            }
            Ok(response)
        })
    }
}

async fn check_postflight_mutation(regrant: bool) {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(240);
    let consumer_id = agent_id(241);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let owner_access = CognitiveAccess::agent_private(owner_id);
    let citation = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "pool-postflight-source",
                "Actual orbital memory evidence.",
            ),
        )
        .await
        .expect("source");
    owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "pool-postflight-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Actual orbital memory evidence.",
                    citation,
                ),
            },
        )
        .await
        .expect("memory");
    let consumer_workspace = workspace("pool-postflight");
    let grant = FederationGrantRequest {
        consumer_agent_id: consumer_id.clone(),
        scope: FederationGrantScope::new(CognitiveScope::AgentPrivate, consumer_workspace.clone()),
        effective_at_unix_seconds: 100,
        expires_at_unix_seconds: 1_000,
    };
    let capability = owner
        .grant_federated_recall(&owner_access, &grant)
        .await
        .expect("grant");
    let reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("discover")
        .pop()
        .expect("reader");
    let access = FederationConsumerAccess::new(consumer_id.clone(), consumer_workspace);
    let request = RetrievalRequest::new("orbital", 150);
    let logical_start_ms = 150_000;
    let started_at = Instant::now();
    let (query, lease) = build_product_query_and_lease(
        &reader,
        &access,
        &request,
        logical_start_ms,
        logical_start_ms
            + u64::try_from(PRODUCT_FEDERATION_TOTAL_BUDGET.as_millis()).expect("budget"),
    )
    .expect("bound query");
    let captured = Arc::new(Mutex::new(None));
    let transport = MutateAfterRead {
        transport: ProductReaderTransport {
            reader: &reader,
            access: &access,
            request: &request,
            captured: Arc::clone(&captured),
        },
        owner: &owner,
        owner_access: &owner_access,
        capability: &capability,
        grant: &grant,
        regrant,
    };
    let authority = ProductReaderAuthority {
        owner_layout: &owner_layout,
        consumer_agent_id: &consumer_id,
        reader: &reader,
        logical_start_ms,
        started_at,
    };
    let control = ProductAttemptControl {
        logical_start_ms,
        started_at,
    };
    let result = execute_once(
        &transport,
        &authority,
        &control,
        logical_start_ms,
        query,
        &lease,
    )
    .await
    .expect("postflight must observe the committed change");
    assert_eq!(
        result.validity,
        if regrant {
            FederatedValidityV2::StaleGeneration
        } else {
            FederatedValidityV2::Revoked
        }
    );
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert!(result.items.is_empty());
    assert!(result.authority_observation_digest.is_some());
    assert!(result.remote_response_digest.is_some());
    assert!(!result.authority.grants_any());
    assert_eq!(
        captured
            .lock()
            .expect("capture")
            .as_ref()
            .expect("real read")
            .candidates
            .len(),
        1
    );
}

#[tokio::test]
async fn federation_pool_product_postflight_observes_revoke_after_real_read() {
    check_postflight_mutation(false).await;
}

#[tokio::test]
async fn federation_pool_product_postflight_observes_regrant_after_real_read() {
    check_postflight_mutation(true).await;
}
