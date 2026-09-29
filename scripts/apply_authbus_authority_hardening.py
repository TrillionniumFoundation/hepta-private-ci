#!/usr/bin/env python3
from pathlib import Path
import re
import json

ROOT = Path(__file__).resolve().parents[1]


def path(rel: str) -> Path:
    return ROOT / rel


def read(rel: str) -> str:
    return path(rel).read_text(encoding="utf-8")


def write(rel: str, content: str) -> None:
    target = path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    text = read(rel)
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{rel}: expected one exact match, found {count} for {old[:100]!r}"
        )
    write(rel, text.replace(old, new, 1))


def regex_once(rel: str, pattern: str, replacement: str, flags: int = 0) -> None:
    text = read(rel)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(
            f"{rel}: expected one regex match, found {count} for {pattern[:120]!r}"
        )
    write(rel, updated)


# 1. The low-level store/host become crate-private. Public users receive one
# owner and explicit least-authority ports.
replace_once(
    "codex-rs/hepta-authbus/Cargo.toml",
    'thiserror = { workspace = true }\n',
    'thiserror = { workspace = true }\n'
    'tokio = { workspace = true, features = ["sync"] }\n',
)
replace_once(
    "codex-rs/hepta-authbus/src/lib.rs",
    "mod host;\n",
    "mod host;\nmod owner;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/lib.rs",
    "pub use authority_store::AuthBusAuthorityStore;\npub use host::AuthBusAuthorityHost;\n",
    "pub(crate) use authority_store::AuthBusAuthorityStore;\n"
    "pub(crate) use host::AuthBusAuthorityHost;\n"
    "pub use owner::AuthBusAdminPort;\n"
    "pub use owner::AuthBusAuthorityOwner;\n"
    "pub use owner::AuthBusEffectPort;\n"
    "pub use owner::AuthBusReadPort;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/lib.rs",
    "pub use settlement::SettlementIssuerRegistration;\n",
    "",
)

# 2. Writer lease failures are explicit stable error classes.
replace_once(
    "codex-rs/hepta-authbus/src/authority.rs",
    '    #[error("AuthBus authority checkpoint file is unsafe or unavailable")]\n'
    '    UnsafeCheckpoint,\n',
    '    #[error("another AuthBus authority writer owns the checkpoint lease")]\n'
    '    WriterLeaseHeld,\n'
    '    #[error("AuthBus authority writer lease was lost or replaced")]\n'
    '    WriterLeaseLost,\n'
    '    #[error("AuthBus authority checkpoint file is unsafe or unavailable")]\n'
    '    UnsafeCheckpoint,\n',
)

# 3. Checkpoint publication has one serialized publisher. A test-only fault
# hook qualifies the crash window after external replacement and before local
# promotion.
replace_once(
    "codex-rs/hepta-authbus/src/host.rs",
    "use std::path::PathBuf;\n",
    "use std::path::PathBuf;\n\n"
    "#[cfg(test)]\n"
    "use std::sync::atomic::AtomicBool;\n"
    "#[cfg(test)]\n"
    "use std::sync::atomic::Ordering;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/host.rs",
    "use crate::SettlementIssuerRegistration;\n",
    "",
)
replace_once(
    "codex-rs/hepta-authbus/src/host.rs",
    "pub struct AuthBusAuthorityHost {\n"
    "    store: AuthBusAuthorityStore,\n"
    "    checkpoint: AuthorityCheckpointFile,\n"
    "}\n",
    "pub(crate) struct AuthBusAuthorityHost {\n"
    "    store: AuthBusAuthorityStore,\n"
    "    checkpoint: AuthorityCheckpointFile,\n"
    "    #[cfg(test)]\n"
    "    fail_after_external_replace: AtomicBool,\n"
    "}\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/host.rs",
    "        let host = Self { store, checkpoint };\n",
    "        let host = Self {\n"
    "            store,\n"
    "            checkpoint,\n"
    "            #[cfg(test)]\n"
    "            fail_after_external_replace: AtomicBool::new(false),\n"
    "        };\n",
)
regex_once(
    "codex-rs/hepta-authbus/src/host.rs",
    r"    pub async fn sync_checkpoint\(&self\) -> Result<\(\), AuthBusAuthorityError> \{.*?\n    \}\n\n    async fn finish",
    '''    pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        let external = self.checkpoint.read()?;
        if let Some(next) = self.store.reconcile_authority_checkpoint(external).await? {
            self.checkpoint.replace(external, next)?;
            #[cfg(test)]
            if self
                .fail_after_external_replace
                .swap(false, Ordering::SeqCst)
            {
                return Err(AuthBusAuthorityError::Storage(
                    "injected crash after external checkpoint publication".to_owned(),
                ));
            }
            self.store
                .advance_authority_checkpoint(external.generation, next)
                .await?;
        }
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn fail_after_external_replace_once(&self) {
        self.fail_after_external_replace
            .store(true, Ordering::SeqCst);
    }

    async fn finish''',
    re.S,
)
regex_once(
    "codex-rs/hepta-authbus/src/host.rs",
    r"\n    pub async fn settlement_issuer\(.*?\n    \}\n",
    "\n",
    re.S,
)
replace_once(
    "codex-rs/hepta-authbus/src/host.rs",
    "    pub async fn settle(\n"
    "        &self,\n"
    "        issuer: &SettlementIssuerRegistration,\n"
    "        evidence: &SignedSettlementEvidence,\n"
    "        time: TrustedTimeSample,\n"
    "    ) -> Result<Settlement, AuthBusAuthorityError> {\n"
    "        let result = self.store.settle(issuer, evidence, time).await;\n",
    "    pub async fn settle(\n"
    "        &self,\n"
    "        evidence: &SignedSettlementEvidence,\n"
    "        time: TrustedTimeSample,\n"
    "    ) -> Result<Settlement, AuthBusAuthorityError> {\n"
    "        let result = self.store.settle(evidence, time).await;\n",
)

# 4. Settlement resolves the registered key and lifecycle inside the same
# SQLite writer transaction. No caller-provided registration can select a key.
regex_once(
    "codex-rs/hepta-authbus/src/settlement.rs",
    r"\npub struct SettlementIssuerRegistration \{.*?\n\}\n",
    "\n",
    re.S,
)
replace_once(
    "codex-rs/hepta-authbus/src/settlement.rs",
    "        issuer: &SettlementIssuerRegistration,\n",
    "        issuer: &crate::IssuerRecord,\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/settlement.rs",
    "        if self.claims.issuer_id != issuer.issuer_id || self.claims.key_epoch != issuer.key_epoch {\n",
    "        if issuer.purpose != crate::IssuerPurpose::Settlement\n"
    "            || self.claims.issuer_id != issuer.issuer_id\n"
    "            || self.claims.key_epoch != issuer.key_epoch\n"
    "        {\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/settlement.rs",
    "        if issuer.revoked {\n",
    "        if issuer.state != crate::IssuerLifecycleState::Active {\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/trust_store.rs",
    "use crate::SettlementIssuerRegistration;\n",
    "",
)
regex_once(
    "codex-rs/hepta-authbus/src/trust_store.rs",
    r"\n    pub async fn settlement_issuer\(.*?\n    \}\n",
    "\n",
    re.S,
)
replace_once(
    "codex-rs/hepta-authbus/src/trust_store.rs",
    "async fn load_issuer(\n",
    "pub(crate) async fn load_issuer(\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/settlement_store.rs",
    "use crate::SettlementIssuerRegistration;\n",
    "",
)
replace_once(
    "codex-rs/hepta-authbus/src/settlement_store.rs",
    "use crate::PolicyEffect;\n",
    "use crate::IssuerPurpose;\nuse crate::PolicyEffect;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/settlement_store.rs",
    "use crate::quota_store::load_reservation;\n",
    "use crate::quota_store::load_reservation;\n"
    "use crate::trust_store::load_issuer;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/settlement_store.rs",
    "    pub async fn settle(\n"
    "        &self,\n"
    "        issuer: &SettlementIssuerRegistration,\n"
    "        evidence: &SignedSettlementEvidence,\n",
    "    pub async fn settle(\n"
    "        &self,\n"
    "        evidence: &SignedSettlementEvidence,\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/settlement_store.rs",
    "        let authenticated = evidence.authenticate(\n"
    "            issuer,\n",
    "        let issuer = load_issuer(\n"
    "            &mut tx,\n"
    "            IssuerPurpose::Settlement,\n"
    "            &evidence.claims.issuer_id,\n"
    "            evidence.claims.key_epoch,\n"
    "        )\n"
    "        .await?;\n"
    "        let authenticated = evidence.authenticate(\n"
    "            &issuer,\n",
)

# Avoid writing the same trusted-time row twice in one logical operation.
replace_once(
    "codex-rs/hepta-authbus/src/authority_store.rs",
    "        if sample.source_revision == prior.source_revision && sample != &prior {\n"
    "            return Err(AuthBusAuthorityError::TimeConflict);\n"
    "        }\n",
    "        if sample.source_revision == prior.source_revision && sample != &prior {\n"
    "            return Err(AuthBusAuthorityError::TimeConflict);\n"
    "        }\n"
    "        if sample == &prior {\n"
    "            return Ok(());\n"
    "        }\n",
)

# 5. Rewrite focused settlement tests to prove registry-selected keys.
settlement_tests = read("codex-rs/hepta-authbus/src/settlement_store_tests.rs")
settlement_tests = settlement_tests.replace(
    "use crate::PolicyDecision;\n",
    "use crate::IssuerPurpose;\n"
    "use crate::IssuerSpec;\n"
    "use crate::PolicyDecision;\n",
    1,
)
settlement_tests, count = re.subn(
    r"\nfn issuer\(key: &SigningKey\) -> SettlementIssuerRegistration \{.*?\n\}\n",
    '''
async fn enroll_settlement(
    store: &AuthBusAuthorityStore,
    key: &SigningKey,
) -> IssuerRecord {
    store
        .enroll_issuer(
            IssuerPurpose::Settlement,
            IssuerSpec {
                issuer_id: id("issuer:settlement"),
                key_epoch: Generation::new(1).expect("generation"),
                verifying_key: key.verifying_key(),
            },
        )
        .await
        .expect("enroll settlement issuer")
}
''',
    settlement_tests,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit("settlement tests: issuer helper drift")
settlement_tests = re.sub(
    r"(    let key = SigningKey::from_bytes\(&\[[0-9]+; 32\]\);\n)(    let signed =)",
    r"\1    enroll_settlement(&store, &key).await;\n\2",
    settlement_tests,
)
settlement_tests = re.sub(
    r"\.settle\(&issuer\(&key\), &signed,",
    ".settle(&signed,",
    settlement_tests,
)
settlement_tests = re.sub(
    r"\.settle\(&issuer\(&key\), &changed,",
    ".settle(&changed,",
    settlement_tests,
)
settlement_tests += r'''

#[tokio::test]
async fn settlement_rejects_a_signature_not_registered_in_the_owner_transaction() {
    let (_root, store, _decision, reservation) = configured().await;
    let dispatched = store
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            reservation.effect_digest,
            sample(5, 1_500),
        )
        .await
        .expect("mark dispatch");
    let registered = SigningKey::from_bytes(&[44; 32]);
    enroll_settlement(&store, &registered).await;
    let forged = SigningKey::from_bytes(&[45; 32]);
    let signed = evidence(&forged, &dispatched, SettlementStatus::Completed, 5, 1_600);
    assert!(matches!(
        store.settle(&signed, sample(6, 1_600)).await,
        Err(AuthBusAuthorityError::InvalidSettlementSignature)
    ));
}

#[tokio::test]
async fn settlement_reloads_and_enforces_current_issuer_revocation() {
    let (_root, store, _decision, reservation) = configured().await;
    let dispatched = store
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            reservation.effect_digest,
            sample(5, 1_500),
        )
        .await
        .expect("mark dispatch");
    let key = SigningKey::from_bytes(&[46; 32]);
    let record = enroll_settlement(&store, &key).await;
    store
        .revoke_issuer(
            IssuerPurpose::Settlement,
            &record.issuer_id,
            record.key_epoch,
            record.revision,
        )
        .await
        .expect("revoke issuer");
    let signed = evidence(&key, &dispatched, SettlementStatus::Completed, 5, 1_600);
    assert!(matches!(
        store.settle(&signed, sample(6, 1_600)).await,
        Err(AuthBusAuthorityError::SettlementIssuerRevoked)
    ));
}
'''
write("codex-rs/hepta-authbus/src/settlement_store_tests.rs", settlement_tests)

# 6. Bao receives only the effect port; it cannot enroll issuers or mutate policy.
replace_once(
    "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
    "use codex_hepta_authbus::AuthBusAuthorityHost;\n",
    "use codex_hepta_authbus::AuthBusEffectPort;\n",
)
text = read("codex-rs/hepta-bao-adapter/src/https_consumer.rs")
count = text.count("authbus: &AuthBusAuthorityHost,")
if count != 2:
    raise SystemExit(f"Bao host port occurrences drifted: {count}")
text = text.replace("authbus: &AuthBusAuthorityHost,", "authbus: &AuthBusEffectPort<'_>,")
issuer_block = '''    let issuer = match authbus
        .settlement_issuer(&signed.claims.issuer_id, signed.claims.key_epoch)
        .await
    {
        Ok(issuer) => issuer,
        Err(error) => {
            return Err(BaoAuthBusError::SettlementPending {
                reservation_id: reservation.reservation_id.clone(),
                receipt,
                control_error: error.to_string(),
            });
        }
    };
    if let Err(error) = authbus.settle(&issuer, &signed, time).await {
'''
if text.count(issuer_block) != 1:
    raise SystemExit("Bao settlement issuer block drift")
text = text.replace(
    issuer_block,
    "    if let Err(error) = authbus.settle(&signed, time).await {\n",
    1,
)
write("codex-rs/hepta-bao-adapter/src/https_consumer.rs", text)

bao_tests = read("codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs")
old_imports = (
    "use codex_hepta_authbus::AuthBusAuthorityHost;\n"
    "use codex_hepta_authbus::AuthBusAuthorityStore;\n"
)
if bao_tests.count(old_imports) != 1:
    raise SystemExit("Bao test owner imports drift")
bao_tests = bao_tests.replace(
    old_imports,
    "use codex_hepta_authbus::AuthBusAuthorityOwner;\n",
    1,
)
start = bao_tests.index("async fn authbus_host(")
end = bao_tests.index("#[tokio::test]\nasync fn authbus_product_path", start)
helper = r'''async fn authbus_host(
    client: &BaoClient,
    request: &BaoReadRequest,
    now: u64,
) -> Result<
    (
        tempfile::TempDir,
        tempfile::TempDir,
        AuthBusAuthorityOwner,
        AuthBusEvidence,
        BaoAuthBusAdmission,
    ),
    TestError,
> {
    let database_root = tempfile::tempdir()?;
    let checkpoint_root = tempfile::tempdir()?;
    std::fs::set_permissions(database_root.path(), std::fs::Permissions::from_mode(0o700))?;
    std::fs::set_permissions(
        checkpoint_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let database = database_root.path().join("authbus-authority.sqlite");
    let checkpoint = checkpoint_root
        .path()
        .join("authbus-authority-checkpoint.json");

    let owner = AuthBusAuthorityOwner::bootstrap_new(
        &database,
        checkpoint,
        "bao-product-owner",
    )
    .await?;
    let admin = owner.admin();
    let effects = owner.effects();
    let mut evidence = AuthBusEvidence::new(now);
    admin
        .enroll_issuer(IssuerPurpose::TrustedTime, evidence.time_spec())
        .await?;
    admin
        .enroll_issuer(IssuerPurpose::Settlement, evidence.settlement_spec())
        .await?;

    let binding = client.binding(request)?;
    let scope = Digest32::from_array(binding.scope_sha256);
    let time = effects
        .observe_trusted_time_attestation(&evidence.trusted_time()?)
        .await?;
    let policy = admin
        .create_policy(
            PolicySpec {
                policy_id: StableId::new("policy:bao-read")?,
                principal: StableId::new(request.subject_id.clone())?,
                action: StableId::new("action:bao-read")?,
                scope_digest: scope,
                effect: PolicyEffect::Allow,
                not_before_ms: now.saturating_sub(1_000),
                expires_at_ms: now + 60_000,
            },
            time,
        )
        .await?;
    let time = effects
        .observe_trusted_time_attestation(&evidence.trusted_time()?)
        .await?;
    let quota = admin
        .create_quota(
            QuotaSpec {
                quota_key: StableId::new("quota:bao-read")?,
                principal: policy.principal,
                scope_digest: scope,
                unit: StableId::new("unit:provider-request")?,
                period_id: StableId::new("period:test")?,
                limit: 1,
            },
            time,
        )
        .await?;
    let admission = BaoAuthBusAdmission {
        policy_revision: 1,
        quota_key: quota.quota_key,
        expected_quota_revision: 1,
        operation_id: StableId::new("operation:bao-product")?,
        amount: 1,
        expires_at_ms: now + 30_000,
    };
    Ok((database_root, checkpoint_root, owner, evidence, admission))
}

'''
bao_tests = bao_tests[:start] + helper + bao_tests[end:]
bao_tests = bao_tests.replace(
    "    let (authority, grant, _authority_dir) = grant(&client, &request).unwrap();\n\n"
    "    let receipt = client",
    "    let (authority, grant, _authority_dir) = grant(&client, &request).unwrap();\n"
    "    let effects = authbus.effects();\n\n"
    "    let receipt = client",
    1,
)
bao_tests = bao_tests.replace(
    "    let (authority, grant, _authority_dir) = grant(&client, &request).unwrap();\n\n"
    "    let result = client",
    "    let (authority, grant, _authority_dir) = grant(&client, &request).unwrap();\n"
    "    let effects = authbus.effects();\n\n"
    "    let result = client",
    1,
)
bao_tests = bao_tests.replace(
    "            &authbus,\n            &admission,",
    "            &effects,\n            &admission,",
)
bao_tests = bao_tests.replace(
    "authbus.quota_snapshot",
    "authbus.read().quota_snapshot",
)
write("codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs", bao_tests)

# 7. Qualification now executes the real verifier and replay window. Its full
# sources are committed beside this migration script.
replace_once(
    "codex-rs/hepta-authbus-p1-3-qualification/Cargo.toml",
    'codex-hepta-authbus = { path = "../hepta-authbus" }\n',
    'codex-hepta-authbus = { path = "../hepta-authbus" }\n'
    'ed25519-dalek = { workspace = true }\n',
)

print(
    json.dumps(
        {
            "status": "AUTHBUS_AUTHORITY_HARDENING_GENERATED",
            "owner": "AuthBusAuthorityOwner",
            "publicPorts": ["admin", "effects", "read"],
            "settlementIssuerResolution": "same_transaction_registry_lookup",
            "qualification": "real_verifier_execution",
        },
        sort_keys=True,
    )
)
