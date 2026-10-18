//! Instantiate the existing AuthBus owner from protected Root policy and pins.
use crate::BaoAuthBusEvidenceProvider;
use crate::ConsumerPortError;
use crate::runtime_clock::RuntimeEvidence;
use crate::runtime_config::SecretsRuntimeServiceConfig;
use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::AuthBusAuthorityStore;
use codex_hepta_authbus::IssuerLifecycleState;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::PolicySpec;
use codex_hepta_authbus::QuotaSpec;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;

pub(crate) async fn open_authbus(
    config: &SecretsRuntimeServiceConfig,
    evidence: &mut RuntimeEvidence,
) -> Result<AuthBusAuthorityHost, ConsumerPortError> {
    let database_exists = config.authbus_database.try_exists().map_err(unavailable)?;
    let checkpoint_exists = config
        .authbus_checkpoint
        .try_exists()
        .map_err(unavailable)?;
    // Only a completely new owner can bootstrap. An interrupted bootstrap or
    // a missing historical checkpoint is retained for explicit owner recovery.
    if database_exists != checkpoint_exists {
        return Err(ConsumerPortError::Unavailable);
    }
    if !database_exists {
        crate::sqlite_owner::prepare_private_storage(&config.authbus_database)
            .map_err(unavailable)?;
        let store = AuthBusAuthorityStore::open(&config.authbus_database)
            .await
            .map_err(unavailable)?;
        let frontier = store
            .authority_frontier_digest()
            .await
            .map_err(unavailable)?;
        store.close().await;
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
            .open(&config.authbus_checkpoint)
            .map_err(unavailable)?;
        serde_json::to_writer(&mut file, &serde_json::json!({"schema_version":1,"owner_id":config.authbus_owner_id,"generation":1,"digest":frontier.to_string()})).map_err(unavailable)?;
        file.flush().map_err(unavailable)?;
        file.sync_all().map_err(unavailable)?;
        std::fs::File::open(
            config
                .authbus_checkpoint
                .parent()
                .ok_or(ConsumerPortError::Invalid)?,
        )
        .map_err(unavailable)?
        .sync_all()
        .map_err(unavailable)?;
    }
    let host = AuthBusAuthorityHost::open(
        &config.authbus_database,
        config.authbus_checkpoint.clone(),
        &config.authbus_owner_id,
    )
    .await
    .map_err(|error| {
        eprintln!("secrets runtime AuthBus checkpoint open failed: {error}");
        unavailable(error)
    })?;
    let initialized = async {
        enroll_exact(
            &host,
            IssuerPurpose::TrustedTime,
            &config.evidence.authority.issuer_id,
            config.evidence.authority.key_epoch,
            &config.evidence.authority.verifying_key,
        )
        .await?;
        enroll_exact(
            &host,
            IssuerPurpose::Settlement,
            &config.evidence.settlement_issuer_id,
            config.evidence.settlement_key_epoch,
            &config.evidence.settlement_verifying_key,
        )
        .await?;
        let attestation = evidence.trusted_time().map_err(unavailable)?;
        let time = host
            .observe_trusted_time_attestation(&attestation)
            .await
            .map_err(unavailable)?;
        if !database_exists
            && (time.wall_time_ms() < config.policy_not_before_ms
                || time.wall_time_ms() >= config.policy_expires_at_ms)
        {
            return Err(ConsumerPortError::Rejected);
        }
        let subject = StableId::new(&config.request.subject_id).map_err(unavailable)?;
        let scope = Digest32::from_array(config.roles.frozen_binding.scope_sha256);
        let policy = PolicySpec {
            policy_id: StableId::new(&config.policy_id).map_err(unavailable)?,
            principal: subject.clone(),
            action: StableId::new("action:bao-read").map_err(unavailable)?,
            scope_digest: scope,
            effect: PolicyEffect::Allow,
            not_before_ms: config.policy_not_before_ms,
            expires_at_ms: config.policy_expires_at_ms,
        };
        match host.create_policy(policy.clone(), time.clone()).await {
            Ok(_) | Err(AuthBusAuthorityError::AlreadyExists) => {}
            Err(error) => return Err(unavailable(error)),
        }
        let retained = host
            .policy_snapshot(&policy.policy_id)
            .await
            .map_err(unavailable)?;
        if retained.policy_id != policy.policy_id
            || retained.principal != policy.principal
            || retained.action != policy.action
            || retained.scope_digest != policy.scope_digest
            || retained.effect != policy.effect
            || retained.not_before_ms != policy.not_before_ms
            || retained.expires_at_ms != policy.expires_at_ms
        {
            return Err(ConsumerPortError::Conflict);
        }
        // Expired/revoked policy cannot admit new work, but it must not make
        // the original owner's signed ACK/status and settlement inaccessible.
        for peer in config.agents.keys() {
            let spec = QuotaSpec {
                quota_key: config.quota_key(*peer)?,
                principal: subject.clone(),
                scope_digest: scope,
                unit: StableId::new("unit:provider-request").map_err(unavailable)?,
                period_id: StableId::new(&config.quota_period_id).map_err(unavailable)?,
                limit: config.quota_limit,
            };
            match host.create_quota(spec, time.clone()).await {
                Ok(_) | Err(AuthBusAuthorityError::AlreadyExists) => {}
                Err(error) => return Err(unavailable(error)),
            }
            let quota = host
                .quota_snapshot(&config.quota_key(*peer)?)
                .await
                .map_err(unavailable)?;
            if quota.principal != subject
                || quota.scope_digest != scope
                || quota.period_id.as_str() != config.quota_period_id
                || quota.unit.as_str() != "unit:provider-request"
                || quota.limit != config.quota_limit
            {
                return Err(ConsumerPortError::Conflict);
            }
        }
        Ok(())
    }
    .await;
    if let Err(error) = initialized {
        host.close().await;
        return Err(error);
    }
    Ok(host)
}

async fn enroll_exact(
    host: &AuthBusAuthorityHost,
    purpose: IssuerPurpose,
    issuer: &str,
    epoch: u64,
    pin: &[u8; 32],
) -> Result<(), ConsumerPortError> {
    let issuer = StableId::new(issuer).map_err(unavailable)?;
    let epoch = Generation::new(epoch).map_err(unavailable)?;
    let pin = VerifyingKey::from_bytes(pin).map_err(unavailable)?;
    let record = match host.issuer_record(purpose, &issuer, epoch).await {
        Ok(record) => record,
        Err(AuthBusAuthorityError::IssuerMissing) => host
            .enroll_issuer(
                purpose,
                IssuerSpec {
                    issuer_id: issuer.clone(),
                    key_epoch: epoch,
                    verifying_key: pin,
                },
            )
            .await
            .map_err(unavailable)?,
        Err(error) => return Err(unavailable(error)),
    };
    if record.issuer_id != issuer
        || record.key_epoch != epoch
        || record.verifying_key != pin
        || record.purpose != purpose
        || record.state != IssuerLifecycleState::Active
    {
        return Err(ConsumerPortError::Conflict);
    }
    Ok(())
}
impl SecretsRuntimeServiceConfig {
    pub(crate) fn quota_key(&self, peer: u32) -> Result<StableId, ConsumerPortError> {
        let agent = self.agents.get(&peer).ok_or(ConsumerPortError::Rejected)?;
        StableId::new(format!("quota:secrets:{agent}:{}", self.quota_period_id))
            .map_err(unavailable)
    }
}
fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
