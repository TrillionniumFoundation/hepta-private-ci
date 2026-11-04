//! Controlled PQ study trust retained through training, install and ordinary use.
//! The durable signed floor is a test service, not deployment qualification.
use super::*;
use crate::authority_trust_unix::PqTrustOperationV2;
use crate::authority_trust_unix::PqTrustOutcomeV2;
use crate::authority_trust_unix::UnixPqAuthorityClock;
use crate::authority_trust_unix::UnixPqLearningTrustFrontier;
use crate::authority_trust_unix::UnixPqTrustEndpointConfig;
use crate::authority_trust_unix::tests::TestService;
use crate::authority_trust_unix::tests::signed;
use codex_hepta_contracts::AuthorityClock;
use std::sync::Arc;

pub(super) struct PqStudyAuthority {
    pub activated: ledger::ActivatedLearningTrustV1,
    pub clock: Arc<UnixPqAuthorityClock>,
    pub frontier: Arc<UnixPqLearningTrustFrontier>,
    root: ledger::LearningTrustRootV1,
    distribution: ledger::SignedLearningTrustDistributionV1,
    clock_service: TestService,
    frontier_service: TestService,
}

impl PqStudyAuthority {
    pub fn start(
        directory: &Path,
        binding: Digest32,
        trust: ledger::LearningEvidenceTrustV1,
        from: u64,
        until: u64,
    ) -> TestResult<Self> {
        fs::create_dir(directory)?;
        let directory = directory.canonicalize()?;
        let key =
            FixtureSigningKey::new(LearningAuthenticationProfile::MlDsa65V2, /*seed*/ 61)?;
        let root = ledger::LearningTrustRootV1 {
            root_id: id("controlled-neural-test-root"),
            scope_digest: trust.scope_digest,
            verifying_key: key.verifying_key(),
            valid_from: from,
            expires_at: until,
            revoked_at: None,
        };
        let mut distribution = ledger::SignedLearningTrustDistributionV1 {
            distribution: ledger::LearningTrustDistributionV1 {
                distribution_id: id("controlled-neural-test-distribution"),
                generation: 1,
                effective_at: from,
                trust,
            },
            root_id: root.root_id.clone(),
            issued_at: from,
            expires_at: until,
            signature: key.signature_template(),
        };
        distribution.signature = key.sign(&distribution.signing_bytes()?)?;
        let activated = ledger::activate_learning_trust(
            &root,
            distribution.clone(),
            /*previous*/ None,
            from,
        )?;
        let path = directory.join("learning-frontier.json");
        fs::write(
            &path,
            serde_json::to_vec(&ledger::learning_trust_frontier(&activated))?,
        )?;
        File::open(&path)?.sync_all()?;
        File::open(&directory)?.sync_all()?;
        let owner = format!("hepta-learning-trust:{binding}");
        let base = roles::micros() / 1_000;
        let started = Instant::now();
        let clock_service = TestService::start_with_lifetime(
            &directory,
            "clock.sock",
            /*seed*/ 95,
            Duration::from_secs(3_600),
            move |request, key| {
                let outcome = match &request.operation {
                    PqTrustOperationV2::ClockNow => PqTrustOutcomeV2::Clock {
                        unix_ms: base
                            .checked_add(u64::try_from(started.elapsed().as_millis())?)
                            .ok_or("study authority clock overflow")?,
                    },
                    PqTrustOperationV2::LearningFrontierLoad { .. }
                    | PqTrustOperationV2::LearningFrontierCompareAndSet { .. }
                    | PqTrustOperationV2::FrontierLoad { .. }
                    | PqTrustOperationV2::FrontierCompareAndSet { .. } => {
                        PqTrustOutcomeV2::Unavailable
                    }
                };
                signed(request, outcome, key)
            },
        )
        .map_err(issuer_error)?;
        let frontier_service = TestService::start_with_lifetime(
            &directory,
            "frontier.sock",
            /*seed*/ 96,
            Duration::from_secs(3_600),
            move |request, key| {
                let outcome = match &request.operation {
                    PqTrustOperationV2::LearningFrontierLoad { owner_id } if owner_id == &owner => {
                        PqTrustOutcomeV2::LearningFrontier {
                            value: serde_json::from_slice(&fs::read(&path)?)?,
                        }
                    }
                    PqTrustOperationV2::ClockNow
                    | PqTrustOperationV2::LearningFrontierLoad { .. }
                    | PqTrustOperationV2::LearningFrontierCompareAndSet { .. }
                    | PqTrustOperationV2::FrontierLoad { .. }
                    | PqTrustOperationV2::FrontierCompareAndSet { .. } => {
                        PqTrustOutcomeV2::Unavailable
                    }
                };
                signed(request, outcome, key)
            },
        )
        .map_err(issuer_error)?;
        let clock = Arc::new(UnixPqAuthorityClock::new(clock_service.config.clone())?);
        let frontier = Arc::new(UnixPqLearningTrustFrontier::new(
            frontier_service.config.clone(),
        )?);
        let now = clock
            .now_unix_ms()?
            .checked_mul(1_000)
            .ok_or("study clock overflow")?;
        let activated = ledger::activate_learning_trust(
            &root,
            distribution.clone(),
            /*previous*/ None,
            now,
        )?
        .with_trust_frontier(binding, frontier.clone())?;
        Ok(Self {
            activated,
            clock,
            frontier,
            root,
            distribution,
            clock_service,
            frontier_service,
        })
    }

    pub fn descriptor(&self) -> Value {
        json!({
            "root_id": self.root.root_id.as_str(), "root_scope_digest": self.root.scope_digest.to_string(),
            "root_verifying_key": cognitive_process_wire::LearningKey::from(self.root.verifying_key.clone()),
            "root_valid_from": self.root.valid_from, "root_expires_at": self.root.expires_at,
            "root_revoked_at": self.root.revoked_at,
            "distribution_id": self.distribution.distribution.distribution_id.as_str(),
            "generation": self.distribution.distribution.generation,
            "effective_at": self.distribution.distribution.effective_at,
            "issued_at": self.distribution.issued_at, "expires_at": self.distribution.expires_at,
            "signature": cognitive_process_wire::LearningSignature::from(self.distribution.signature.clone()),
            "clock": endpoint(&self.clock_service.config), "frontier": endpoint(&self.frontier_service.config),
        })
    }
}

fn endpoint(config: &UnixPqTrustEndpointConfig) -> Value {
    json!({
        "socket_path": config.socket_path, "peer_uid": config.peer_uid,
        "service_id": config.service_id, "key_generation": config.key_generation,
        "public_key_id": config.public_key_id, "public_key_spki": config.public_key_spki,
        "timeout_ms": config.timeout_ms,
    })
}
