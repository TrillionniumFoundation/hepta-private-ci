//! Authenticated configuration and signing material for the ordinary loader tests.

use super::super::*;
use super::NOW;
use super::support::Service;
use super::support::frontier_service;
use super::support::key;
use super::support::write_private;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

pub(super) struct PqFixture {
    clock: Service,
    pub(super) frontier: Option<Service>,
    pub(super) now: Arc<AtomicU64>,
    issuer: PqNativeSigningKey,
    feed_signer: PqNativeSigningKey,
    contract_signer: PqNativeSigningKey,
    pub(super) head: FinalUseRevocations,
    pub(super) config: Value,
    pub(super) config_path: PathBuf,
    pub(super) feed_path: PathBuf,
    // Keep the service sockets and durable frontier until both threads stop.
    pub(super) root: tempfile::TempDir,
}

impl PqFixture {
    pub(super) fn http(uri: &str, scope: &Sha256Digest) -> anyhow::Result<Self> {
        let root = tempfile::tempdir()?;
        let private_root = root.path().canonicalize()?;
        let now = Arc::new(AtomicU64::new(NOW + 5));
        let time = Arc::clone(&now);
        let clock = Service::start(
            &private_root,
            "clock.sock",
            /*seed*/ 74,
            move |operation| {
                Ok(match operation {
                    PqTrustOperationV2::ClockNow => PqTrustOutcomeV2::Clock {
                        unix_ms: time.load(Ordering::SeqCst),
                    },
                    PqTrustOperationV2::FrontierLoad { .. }
                    | PqTrustOperationV2::FrontierCompareAndSet { .. }
                    | PqTrustOperationV2::LearningFrontierLoad { .. }
                    | PqTrustOperationV2::LearningFrontierCompareAndSet { .. } => {
                        PqTrustOutcomeV2::Unavailable
                    }
                })
            },
        )?;
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let frontier = frontier_service(
            &private_root,
            FinalUseFrontier::for_initial_head_with_profile(
                &head,
                FinalUseAuthenticationProfile::MlDsa65V2,
            )?,
        )?;
        let (issuer, issuer_pin) = key(/*seed*/ 71)?;
        let (feed_signer, feed_pin) = key(/*seed*/ 72)?;
        let (contract_signer, contract_pin) = key(/*seed*/ 73)?;
        let provider = HttpProviderEffectConfig {
            dispatch_url: format!("{uri}/dispatch"),
            lookup_url_template: format!("{uri}/status/{{key}}"),
            headers: HeaderMap::new(),
            timeout: Duration::from_secs(5),
            contract_id: "pq-http-fixture".to_string(),
            attestation: None,
        };
        let digest = provider.contract_sha256().map_err(anyhow::Error::msg)?;
        let config_path = private_root.join("effects.json");
        let feed_path = private_root.join("feed.json");
        let config = serde_json::json!({
            "schema_version": 4, "authentication_profile": "ml_dsa65_v2",
            "provider_scope": "provider/fixture-v1", "destination_id": "provider:fixture",
            "final_use_scope_sha256": scope.as_str(),
            "provider": { "provider_kind": "http-v1", "dispatch_url": provider.dispatch_url,
                "lookup_url_template": provider.lookup_url_template, "headers": {}, "timeout_ms": 5000 },
            "contract_id": provider.contract_id, "contract_sha256": digest.as_str(),
            "contract_authority_epoch": 9, "contract_signature": [], "contract_key": pin_json(&contract_pin),
            "final_use": { "signer_id": "pq-issuer", "issuer_keys": [pin_json(&issuer_pin)],
                "head": head, "revocation_distributor_id": "pq-feed", "revocation_keys": [pin_json(&feed_pin)],
                "signed_revocations_file": feed_path, "external_clock": clock.config_json(),
                "external_frontier": frontier.config_json() },
        });
        let mut fixture = Self {
            root,
            clock,
            frontier: Some(frontier),
            now,
            issuer,
            feed_signer,
            contract_signer,
            head,
            config,
            config_path,
            feed_path,
        };
        fixture.sign_contract(&digest)?;
        fixture.publish_feed(&fixture.feed(fixture.head.clone(), NOW - 1000, NOW + 60_000)?)?;
        Ok(fixture)
    }

    pub(super) fn sign_contract(&mut self, digest: &Sha256Digest) -> anyhow::Result<()> {
        self.config["contract_sha256"] = serde_json::json!(digest.as_str());
        let message = HttpProviderEffectContractAttestation::statement_for_pq(
            self.config["contract_id"].as_str().expect("contract id"),
            digest,
            /*authority_epoch*/ 9,
        );
        self.config["contract_signature"] =
            serde_json::json!(self.contract_signer.sign_exact_message(&message)?.to_vec());
        self.write_config()
    }

    pub(super) fn write_config(&self) -> anyhow::Result<()> {
        write_private(&self.config_path, &serde_json::to_vec(&self.config)?)
    }

    pub(super) fn feed(
        &self,
        head: FinalUseRevocations,
        issued: u64,
        expires: u64,
    ) -> anyhow::Result<SignedFinalUseRevocationUpdate> {
        let update = FinalUseRevocationUpdate::new_pq("pq-feed".to_string(), head, issued, expires);
        let signature = self
            .feed_signer
            .sign_exact_message(&update.signing_bytes()?)?
            .to_vec();
        Ok(SignedFinalUseRevocationUpdate { update, signature })
    }

    pub(super) fn publish_feed(
        &self,
        signed: &SignedFinalUseRevocationUpdate,
    ) -> anyhow::Result<()> {
        write_private(&self.feed_path, &serde_json::to_vec(signed)?)
    }

    pub(super) fn grant(
        &self,
        intent: &AuthorizedEffectIntent,
        expires: u64,
    ) -> anyhow::Result<SignedFinalUseGrant> {
        self.grant_at(intent, NOW - 1000, expires)
    }

    pub(super) fn grant_at(
        &self,
        intent: &AuthorizedEffectIntent,
        not_before: u64,
        expires: u64,
    ) -> anyhow::Result<SignedFinalUseGrant> {
        let grant = FinalUseGrant {
            schema_version: 2,
            signer_id: "pq-issuer".to_string(),
            authority_epoch: 9,
            grant_id: "pq-http-grant".to_string(),
            nonce: [92; 32],
            binding: intent.final_use_binding()?,
            not_before_unix_ms: not_before,
            expires_at_unix_ms: expires,
        };
        let signature = self
            .issuer
            .sign_exact_message(&grant.signing_bytes()?)?
            .to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }

    pub(super) fn trust_requests(&self) -> usize {
        self.clock.requests.load(Ordering::SeqCst)
            + self
                .frontier
                .as_ref()
                .map_or(0, |service| service.requests.load(Ordering::SeqCst))
    }
}

fn pin_json(pin: &PqAuthorityTrustKey) -> Value {
    serde_json::json!({ "key_id": pin.key_id, "public_key_id": pin.public_key_id,
        "public_key_spki": pin.public_key_spki, "not_before_authority_epoch": pin.not_before_authority_epoch,
        "not_after_authority_epoch": pin.not_after_authority_epoch })
}
