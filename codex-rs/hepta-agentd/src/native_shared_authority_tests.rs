//! Native attachment derives its authority from the original destination
//! registry. These tests use the real recovered writer and FinalUse state;
//! only the independent issuer and the destination effect are fixtures.

use std::path::Path;

use codex_hepta_contracts::FinalUseError;
use codex_hepta_memory::{ProductionDispatchFuture, ProductionDispatchRequest,
    ProductionOutboxTarget, ProductionQueuedReceipt, ProductionTargetOutcome,
    ProductionWriterError};
use codex_hepta_operations::OperationIntentV1;
use pretty_assertions::assert_eq;

use super::*;

struct CountingTarget {
    destination: String,
    calls: AtomicUsize,
}

impl CountingTarget {
    fn new(destination: &str) -> Self {
        Self { destination: destination.to_owned(), calls: AtomicUsize::new(0) }
    }
}

impl ProductionOutboxTarget for CountingTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async { ProductionTargetOutcome::Committed { receipt: "fixture:committed".to_owned() } })
    }
}

impl FinalUseProductionOutboxTarget for CountingTarget {
    fn destination_id(&self) -> &str { &self.destination }
}

fn fixture_authority(directory: &Path, key: &SigningKey, signer: &str) -> Result<FinalUseAuthority> {
    fs::create_dir(directory)?;
    #[cfg(unix)]
    fs::set_permissions(directory, fs::Permissions::from_mode(0o700))?;
    Ok(FinalUseAuthority::open_state_dir(directory, signer.to_owned(),
        key.verifying_key().to_bytes(), FinalUseRevocations {
            authority_epoch: 17, revision: 1, revoked_grant_ids: BTreeSet::new(),
        })?)
}

struct RegisteredAuthority {
    host: AgentdProductionWriterHost,
    issuer: Arc<FixtureIssuer>,
    authority: FinalUseAuthority,
    source: Arc<CountingTarget>,
    config: AgentdConfig,
    registry: FleetRegistry,
    temporary: tempfile::TempDir,
}

impl RegisteredAuthority {
    async fn new() -> Result<Self> {
        let (temporary, config, registry, recovered) = original_writer_fixture(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c83")?).await?;
        let issuer = Arc::new(FixtureIssuer { key: SigningKey::from_bytes(&[61; 32]),
            state: std::sync::Weak::new(), grants: AtomicUsize::new(0),
            cancel_at_grant: AtomicBool::new(false), before_grant_return: std::sync::Mutex::new(None) });
        let authority = fixture_authority(&temporary.path().join("original-final-use"),
            &issuer.key, "native-test-issuer")?;
        let source = Arc::new(CountingTarget::new("destination:z-original"));
        let host = recovered.attach_target(authority.clone(), source.clone(), issuer.clone())?;
        Ok(Self { host, issuer, authority, source, config, registry, temporary })
    }

    async fn signed_operation(&self, operation_id: &str, destination: &str)
        -> Result<(ProductionQueuedReceipt, FinalUseBinding, SignedFinalUseGrant)> {
        let writer = self.host.writer();
        let payload = "{\"kind\":\"shared-authority-fixture\"}";
        let operation = OperationIntentV1::new(StableId::new(operation_id)?,
            StableId::new(writer.owner_agent_id().as_str())?, StableId::new(destination)?,
            Digest32::of_bytes(payload.as_bytes()), Digest32::of_bytes(b"original-authority-test-scope"),
            Generation::new(1)?, /*expected_predecessor*/ None)?;
        let queued = writer.prepare_operation(operation, "fixture.shared-authority", payload).await?;
        let binding = writer.final_use_binding(&queued, destination).await?;
        let signed = self.issuer.signed_grant(&binding)?;
        Ok((queued, binding, signed))
    }
}

#[tokio::test]
async fn explicit_existing_destination_shares_original_nonce_state_not_map_first() -> Result<()> {
    let fixture = RegisteredAuthority::new().await?;
    let other = fixture_authority(&fixture.temporary.path().join("other-final-use"),
        &SigningKey::from_bytes(&[62; 32]), "other-issuer")?;
    let other_target = Arc::new(CountingTarget::new("destination:a-other"));
    let native = Arc::new(CountingTarget::new("destination:native-shared"));
    assert!(other_target.destination_id() < fixture.source.destination_id());
    let host = fixture.host.clone().attach_additional_target(other.clone(), other_target.clone())?
        .attach_target_with_existing_authority(fixture.source.destination_id(), native.clone())?;
    assert!(Arc::ptr_eq(&fixture.host.writer(), &host.writer()));
    let (queued, binding, signed) = fixture.signed_operation("operation:shared-native",
        native.destination_id()).await?;
    let result = host.dispatch(&signed, &binding, queued).await?;
    assert_eq!(result.state, LocalOutcomeState::Committed);
    assert_eq!((fixture.authority.capacity()?.used_nonces, other.capacity()?.used_nonces,
        native.calls.load(Ordering::SeqCst), other_target.calls.load(Ordering::SeqCst)), (1, 0, 1, 0));

    // A newly signed grant for the original destination cannot reuse a nonce
    // consumed by the sibling, even through the pre-attachment host handle.
    let (queued, binding, mut reused) = fixture.signed_operation("operation:shared-original",
        fixture.source.destination_id()).await?;
    reused.grant.nonce = signed.grant.nonce;
    reused.signature = fixture.issuer.key.sign(&reused.grant.signing_bytes()?).to_bytes().to_vec();
    assert!(matches!(fixture.host.dispatch(&reused, &binding, queued).await,
        Err(AgentdError::ProductionWriter(ProductionWriterError::FinalUse(FinalUseError::AlreadyClaimed)))));
    assert_eq!((fixture.source.calls.load(Ordering::SeqCst), fixture.authority.capacity()?.used_nonces), (0, 1));
    Ok(())
}

#[tokio::test]
async fn original_revocations_reach_both_new_native_destinations() -> Result<()> {
    let fixture = RegisteredAuthority::new().await?;
    let model = Arc::new(CountingTarget::new("destination:native-model"));
    let runtime = Arc::new(CountingTarget::new("destination:native-runtime"));
    let host = fixture.host.clone()
        .attach_target_with_existing_authority(fixture.source.destination_id(), model.clone())?
        .attach_target_with_existing_authority(fixture.source.destination_id(), runtime.clone())?;
    let first = fixture.signed_operation("operation:revoked-model", model.destination_id()).await?;
    let second = fixture.signed_operation("operation:revoked-runtime", runtime.destination_id()).await?;
    fixture.authority.update_revocations(FinalUseRevocations {
        authority_epoch: 17, revision: 2,
        revoked_grant_ids: BTreeSet::from([first.2.grant.grant_id.clone(), second.2.grant.grant_id.clone()]),
    })?;
    for (queued, binding, signed) in [first, second] {
        assert!(matches!(host.dispatch(&signed, &binding, queued).await,
            Err(AgentdError::ProductionWriter(ProductionWriterError::FinalUse(FinalUseError::Revoked)))));
    }
    assert_eq!((model.calls.load(Ordering::SeqCst), runtime.calls.load(Ordering::SeqCst),
        fixture.source.calls.load(Ordering::SeqCst), fixture.authority.capacity()?.used_nonces), (0, 0, 0, 0));
    assert_eq!(fixture.authority.revocation_head()?.revision, 2);
    Ok(())
}

#[tokio::test]
async fn unknown_native_authority_source_fails_before_runtime_initialization() -> Result<()> {
    let fixture = RegisteredAuthority::new().await?;
    let state = Arc::new(AgentdState::new(fixture.config.identity().clone(),
        fixture.registry.clone(), /*event_capacity*/ 8)?);
    let callbacks = Arc::new(AtomicUsize::new(0));
    for source in ["", "destination:unregistered"] {
        let attached = callbacks.clone();
        let config = AgentdNativeRuntimeConfig {
            model: NativeResponsesTargetConfig { responses_url: "http://127.0.0.1:9/v1/responses".to_owned(),
                bearer: None, idle_timeout: Duration::from_secs(1), max_request_bytes: 8192, max_stream_bytes: 8192 },
            http: Arc::new(HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault)),
            runtime_destination: "destination:native-runtime".to_owned(),
            // No runtime environment is configured. An unknown authority must
            // be rejected before runtime_config, health or store preparation.
            required_hosts: Vec::new(), max_tool_output_bytes: 4096,
            policy_generation: Generation::new(1)?, final_use_authority_destination: source.to_owned(),
            compiler: Arc::new(NoToolCompiler), hosted_turn: None,
            attach: Box::new(move |_| { attached.fetch_add(1, Ordering::SeqCst); Ok(()) }),
        };
        let error = config.attach_to(&state, Arc::new(fixture.host.clone())).await.err()
            .context("unknown authority source was accepted")?;
        assert!(error.to_string().contains(&format!("native final-use authority source {source:?} is not registered")));
    }
    assert_eq!((fixture.host.destination_count(), fixture.issuer.grants.load(Ordering::SeqCst),
        fixture.authority.capacity()?.used_nonces, callbacks.load(Ordering::SeqCst)), (1, 0, 0, 0));
    Ok(())
}
