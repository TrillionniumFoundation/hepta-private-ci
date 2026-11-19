#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + "\n" + addition.strip() + "\n")


# Runtime dependency for the per-host async mutation gate.
replace_once(
    "codex-rs/hepta-authbus/Cargo.toml",
    "sqlx = { workspace = true }\nthiserror = { workspace = true }",
    "sqlx = { workspace = true }\nthiserror = { workspace = true }\ntokio = { workspace = true, features = [\"sync\"] }",
)

# Preserve the physical dispatch boundary independently from later state changes.
replace_once(
    "codex-rs/hepta-authbus/src/quota.rs",
    "    pub created_at_ms: u64,\n    pub updated_at_ms: u64,\n    pub dispatch_digest: Option<Digest32>,",
    "    pub created_at_ms: u64,\n    pub updated_at_ms: u64,\n    pub dispatched_at_ms: Option<u64>,\n    pub dispatch_digest: Option<Digest32>,",
)

# Settlement must resolve the issuer from the persistent owner in the same transaction.
replace_once(
    "codex-rs/hepta-authbus/src/trust_store.rs",
    "async fn load_issuer(\n",
    "pub(crate) async fn load_issuer(\n",
)

settlement = "codex-rs/hepta-authbus/src/settlement.rs"
replace_once(
    settlement,
    "use crate::AuthBusAuthorityError;\nuse crate::push_id;",
    "use crate::AuthBusAuthorityError;\nuse crate::IssuerLifecycleState;\nuse crate::IssuerPurpose;\nuse crate::IssuerRecord;\nuse crate::push_id;",
)
replace_once(
    settlement,
    "        issuer: &SettlementIssuerRegistration,",
    "        issuer: &IssuerRecord,",
)
replace_once(
    settlement,
    "        if self.claims.issuer_id != issuer.issuer_id || self.claims.key_epoch != issuer.key_epoch {\n            return Err(AuthBusAuthorityError::SettlementIssuerMismatch);\n        }",
    "        if issuer.purpose != IssuerPurpose::Settlement\n            || self.claims.issuer_id != issuer.issuer_id\n            || self.claims.key_epoch != issuer.key_epoch\n        {\n            return Err(AuthBusAuthorityError::SettlementIssuerMismatch);\n        }",
)
replace_once(
    settlement,
    "        if issuer.revoked {\n            return Err(AuthBusAuthorityError::SettlementIssuerRevoked);\n        }",
    "        if issuer.state != IssuerLifecycleState::Active {\n            return Err(AuthBusAuthorityError::SettlementIssuerRevoked);\n        }",
)

settlement_store = "codex-rs/hepta-authbus/src/settlement_store.rs"
replace_once(
    settlement_store,
    "use crate::AuthBusAuthorityStore;\nuse crate::PolicyEffect;",
    "use crate::AuthBusAuthorityStore;\nuse crate::IssuerPurpose;\nuse crate::PolicyEffect;",
)
replace_once(
    settlement_store,
    "use crate::quota_store::load_quota;\nuse crate::quota_store::load_reservation;",
    "use crate::quota_store::load_quota;\nuse crate::quota_store::load_reservation;\nuse crate::trust_store::load_issuer;",
)
replace_once(
    settlement_store,
    dedent(
        """
        reservation.state = ReservationState::DispatchAttempted;
        reservation.dispatch_digest = Some(dispatch_digest);
        reservation.revision = next_revision(reservation.revision)?;
        reservation.updated_at_ms = time.wall_time_ms;
        sqlx::query(
            "UPDATE authbus_quota_reservation SET state = 'dispatch_attempted',
             dispatch_digest = ?, revision = ?, updated_at_ms = ? WHERE reservation_id = ?",
        )
        .bind(dispatch_digest.as_array().as_slice())
        .bind(u64_bytes(reservation.revision).as_slice())
        .bind(u64_bytes(reservation.updated_at_ms).as_slice())
        .bind(reservation_id.as_str())
        """
    ).strip(),
    dedent(
        """
        reservation.state = ReservationState::DispatchAttempted;
        reservation.dispatched_at_ms = Some(time.wall_time_ms);
        reservation.dispatch_digest = Some(dispatch_digest);
        reservation.revision = next_revision(reservation.revision)?;
        reservation.updated_at_ms = time.wall_time_ms;
        sqlx::query(
            "UPDATE authbus_quota_reservation SET state = 'dispatch_attempted',
             dispatched_at_ms = ?, dispatch_digest = ?, revision = ?, updated_at_ms = ?
             WHERE reservation_id = ?",
        )
        .bind(u64_bytes(time.wall_time_ms).as_slice())
        .bind(dispatch_digest.as_array().as_slice())
        .bind(u64_bytes(reservation.revision).as_slice())
        .bind(u64_bytes(reservation.updated_at_ms).as_slice())
        .bind(reservation_id.as_str())
        """
    ).strip(),
)
replace_once(
    settlement_store,
    dedent(
        """
        let authenticated = evidence.authenticate(
            issuer,
            &reservation.reservation_id,
            &reservation.operation_id,
            time.wall_time_ms,
        )?;
        if authenticated.claims().observed_at_ms < reservation.updated_at_ms {
            return Err(AuthBusAuthorityError::InvalidSettlementEvidence);
        }
        """
    ).strip(),
    dedent(
        """
        if issuer.issuer_id != evidence.claims.issuer_id
            || issuer.key_epoch != evidence.claims.key_epoch
        {
            return Err(AuthBusAuthorityError::SettlementIssuerMismatch);
        }
        let registered = load_issuer(
            &mut tx,
            IssuerPurpose::Settlement,
            &evidence.claims.issuer_id,
            evidence.claims.key_epoch,
        )
        .await?;
        let authenticated = evidence.authenticate(
            &registered,
            &reservation.reservation_id,
            &reservation.operation_id,
            time.wall_time_ms,
        )?;
        let dispatched_at_ms = reservation.dispatched_at_ms.ok_or(
            AuthBusAuthorityError::CorruptState("missing reservation dispatch time"),
        )?;
        if authenticated.claims().observed_at_ms < dispatched_at_ms {
            return Err(AuthBusAuthorityError::InvalidSettlementEvidence);
        }
        """
    ).strip(),
)

quota_store = "codex-rs/hepta-authbus/src/quota_store.rs"
replace_once(
    quota_store,
    "                  revision, expires_at_ms, created_at_ms, updated_at_ms, dispatch_digest,\n                  terminal_evidence, observed_cost, settlement_digest, archived_at_ms)\n                 SELECT reservation_id, operation_id, quota_key, period_id, principal, amount,\n                        effect_digest, policy_id, policy_revision, policy_decision_digest, state,\n                        revision, expires_at_ms, created_at_ms, updated_at_ms, dispatch_digest,\n                        terminal_evidence, observed_cost, settlement_digest, ?",
    "                  revision, expires_at_ms, created_at_ms, updated_at_ms, dispatched_at_ms,\n                  dispatch_digest, terminal_evidence, observed_cost, settlement_digest, archived_at_ms)\n                 SELECT reservation_id, operation_id, quota_key, period_id, principal, amount,\n                        effect_digest, policy_id, policy_revision, policy_decision_digest, state,\n                        revision, expires_at_ms, created_at_ms, updated_at_ms, dispatched_at_ms,\n                        dispatch_digest, terminal_evidence, observed_cost, settlement_digest, ?",
)
replace_once(
    quota_store,
    "        updated_at_ms: nonzero_u64(row, \"updated_at_ms\")?,\n        dispatch_digest: optional_digest(row, \"dispatch_digest\")?,",
    "        updated_at_ms: nonzero_u64(row, \"updated_at_ms\")?,\n        dispatched_at_ms: optional_u64(row, \"dispatched_at_ms\")?,\n        dispatch_digest: optional_digest(row, \"dispatch_digest\")?,",
)
replace_once(
    quota_store,
    dedent(
        """
        if reservation.policy_decision_digest.is_zero()
            || reservation.effect_digest.is_zero()
            || reservation.updated_at_ms < reservation.created_at_ms
        {
            return Err(AuthBusAuthorityError::CorruptState(
                "invalid quota reservation record",
            ));
        }
        """
    ).strip(),
    dedent(
        """
        let dispatched_state = matches!(
            reservation.state,
            ReservationState::DispatchAttempted
                | ReservationState::Indeterminate
                | ReservationState::Settled
                | ReservationState::Released
        );
        let invalid_dispatch_time = match reservation.dispatched_at_ms {
            Some(dispatched_at_ms) => {
                !dispatched_state
                    || dispatched_at_ms < reservation.created_at_ms
                    || dispatched_at_ms > reservation.updated_at_ms
            }
            None => dispatched_state,
        };
        if reservation.policy_decision_digest.is_zero()
            || reservation.effect_digest.is_zero()
            || reservation.updated_at_ms < reservation.created_at_ms
            || invalid_dispatch_time
        {
            return Err(AuthBusAuthorityError::CorruptState(
                "invalid quota reservation record",
            ));
        }
        """
    ).strip(),
)

recovery = "codex-rs/hepta-authbus/src/recovery.rs"
text = read(recovery)
old = "hex(updated_at_ms)||'|'||COALESCE(hex(dispatch_digest),'-')||'|'||"
new = "hex(updated_at_ms)||'|'||COALESCE(hex(dispatched_at_ms),'-')||'|'||\n            COALESCE(hex(dispatch_digest),'-')||'|'||"
if text.count(old) != 2:
    raise SystemExit(f"{recovery}: expected two frontier replacements, found {text.count(old)}")
write(recovery, text.replace(old, new))

# Serialize each mutation through durable checkpoint publication. Reads remain concurrent.
host = "codex-rs/hepta-authbus/src/host.rs"
replace_once(
    host,
    "use serde::Deserialize;\nuse serde::Serialize;",
    "use serde::Deserialize;\nuse serde::Serialize;\nuse tokio::sync::Mutex;",
)
replace_once(
    host,
    "pub struct AuthBusAuthorityHost {\n    store: AuthBusAuthorityStore,\n    checkpoint: AuthorityCheckpointFile,\n}",
    "pub struct AuthBusAuthorityHost {\n    store: AuthBusAuthorityStore,\n    checkpoint: AuthorityCheckpointFile,\n    mutation_gate: Mutex<()>,\n}",
)
replace_once(
    host,
    "        let host = Self { store, checkpoint };",
    "        let host = Self {\n            store,\n            checkpoint,\n            mutation_gate: Mutex::new(()),\n        };",
)
replace_once(
    host,
    dedent(
        """
        pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
            let external = self.checkpoint.read()?;
            if let Some(next) = self.store.reconcile_authority_checkpoint(external).await? {
                self.checkpoint.replace(external, next)?;
                self.store
                    .advance_authority_checkpoint(external.generation, next)
                    .await?;
            }
            Ok(())
        }
        """
    ).strip(),
    dedent(
        """
        pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
            let _guard = self.mutation_gate.lock().await;
            self.sync_checkpoint_locked().await
        }

        async fn sync_checkpoint_locked(&self) -> Result<(), AuthBusAuthorityError> {
            let external = self.checkpoint.read()?;
            if let Some(next) = self.store.reconcile_authority_checkpoint(external).await? {
                self.checkpoint.replace(external, next)?;
                self.store
                    .advance_authority_checkpoint(external.generation, next)
                    .await?;
            }
            Ok(())
        }
        """
    ).strip(),
)
replace_once(
    host,
    "        self.sync_checkpoint().await?;\n        result",
    "        self.sync_checkpoint_locked().await?;\n        result",
)
host_text = read(host)
prefix, separator, suffix = host_text.partition("\n#[derive(Deserialize, Serialize)]")
if not separator:
    raise SystemExit(f"{host}: checkpoint document boundary missing")
mutation_count = prefix.count("        let result = ")
if mutation_count < 10:
    raise SystemExit(f"{host}: expected mutation wrappers, found {mutation_count}")
prefix = prefix.replace(
    "        let result = ",
    "        let _guard = self.mutation_gate.lock().await;\n        let result = ",
)
write(host, prefix + separator + suffix)
append_once(
    host,
    'path = "host_tests.rs"',
    dedent(
        """
        #[cfg(all(test, unix))]
        #[path = "host_tests.rs"]
        mod tests;
        """
    ),
)

write(
    "codex-rs/hepta-authbus/migrations/0005_dispatch_time.sql",
    dedent(
        """
        -- Bind settlement ordering to the physical dispatch boundary rather than
        -- to later local state updates such as Indeterminate reconciliation.
        ALTER TABLE authbus_quota_reservation
            ADD COLUMN dispatched_at_ms BLOB
            CHECK (dispatched_at_ms IS NULL OR length(dispatched_at_ms) = 8);
        ALTER TABLE authbus_quota_reservation_archive
            ADD COLUMN dispatched_at_ms BLOB
            CHECK (dispatched_at_ms IS NULL OR length(dispatched_at_ms) = 8);

        UPDATE authbus_quota_reservation
        SET dispatched_at_ms = updated_at_ms
        WHERE state IN ('dispatch_attempted', 'indeterminate', 'settled', 'released');
        UPDATE authbus_quota_reservation_archive
        SET dispatched_at_ms = updated_at_ms
        WHERE state IN ('settled', 'released');

        -- Adding the field changes the semantic frontier for every retained row,
        -- including undispatched terminal history where the value is NULL.
        UPDATE authbus_authority_checkpoint_dirty
        SET dirty = 1
        WHERE singleton = 1 AND (
            EXISTS (SELECT 1 FROM authbus_quota_reservation)
            OR EXISTS (SELECT 1 FROM authbus_quota_reservation_archive)
        );

        CREATE TRIGGER authbus_reservation_dispatch_time_insert
        BEFORE INSERT ON authbus_quota_reservation
        WHEN (
            NEW.state IN ('dispatch_attempted', 'indeterminate', 'settled', 'released')
            AND NEW.dispatched_at_ms IS NULL
        ) OR (
            NEW.state IN ('held', 'expired', 'cancelled')
            AND NEW.dispatched_at_ms IS NOT NULL
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid AuthBus reservation dispatch time');
        END;

        CREATE TRIGGER authbus_reservation_dispatch_time_update
        BEFORE UPDATE ON authbus_quota_reservation
        WHEN (
            NEW.state IN ('dispatch_attempted', 'indeterminate', 'settled', 'released')
            AND NEW.dispatched_at_ms IS NULL
        ) OR (
            NEW.state IN ('held', 'expired', 'cancelled')
            AND NEW.dispatched_at_ms IS NOT NULL
        ) OR (
            OLD.dispatched_at_ms IS NOT NULL
            AND NEW.dispatched_at_ms IS NOT OLD.dispatched_at_ms
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid AuthBus reservation dispatch time');
        END;

        CREATE TRIGGER authbus_reservation_archive_dispatch_time
        BEFORE INSERT ON authbus_quota_reservation_archive
        WHEN (
            NEW.state IN ('settled', 'released') AND NEW.dispatched_at_ms IS NULL
        ) OR (
            NEW.state IN ('expired', 'cancelled') AND NEW.dispatched_at_ms IS NOT NULL
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid archived AuthBus reservation dispatch time');
        END;
        """
    ).lstrip(),
)

write(
    "codex-rs/hepta-authbus/src/host_tests.rs",
    dedent(
        r'''
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        use std::os::unix::fs::PermissionsExt;
        use std::path::PathBuf;
        use std::sync::Arc;

        use codex_hepta_types::Generation;
        use codex_hepta_types::StableId;
        use ed25519_dalek::SigningKey;
        use tempfile::TempDir;

        use super::*;
        use crate::IssuerPurpose;
        use crate::IssuerSpec;

        async fn fixture(
            owner_id: &str,
        ) -> (TempDir, TempDir, PathBuf, PathBuf, AuthBusAuthorityHost) {
            let database_root = tempfile::tempdir().expect("database tempdir");
            let checkpoint_root = tempfile::tempdir().expect("checkpoint tempdir");
            std::fs::set_permissions(
                database_root.path(),
                std::fs::Permissions::from_mode(0o700),
            )
            .expect("database permissions");
            std::fs::set_permissions(
                checkpoint_root.path(),
                std::fs::Permissions::from_mode(0o700),
            )
            .expect("checkpoint permissions");
            let database = database_root.path().join("authbus.sqlite");
            let checkpoint = checkpoint_root.path().join("authbus-checkpoint.json");

            let raw = AuthBusAuthorityStore::open(&database)
                .await
                .expect("open raw store");
            let frontier = raw
                .authority_frontier_digest()
                .await
                .expect("frontier digest");
            raw.pool.close().await;
            let document = serde_json::json!({
                "schema_version": 1,
                "owner_id": owner_id,
                "generation": 1,
                "digest": frontier.to_string(),
            });
            let mut file = std::fs::OpenOptions::new()
                .create_new(true)
                .write(true)
                .mode(0o600)
                .open(&checkpoint)
                .expect("create checkpoint");
            serde_json::to_writer(&mut file, &document).expect("write checkpoint");
            file.flush().expect("flush checkpoint");
            file.sync_all().expect("sync checkpoint");

            let host = AuthBusAuthorityHost::open(&database, checkpoint.clone(), owner_id)
                .await
                .expect("open host");
            (database_root, checkpoint_root, database, checkpoint, host)
        }

        fn spec(index: u8) -> IssuerSpec {
            IssuerSpec {
                issuer_id: StableId::new(format!("issuer:parallel:{index}"))
                    .expect("issuer id"),
                key_epoch: Generation::new(1).expect("issuer epoch"),
                verifying_key: SigningKey::from_bytes(&[index; 32]).verifying_key(),
            }
        }

        #[tokio::test]
        async fn concurrent_mutations_share_one_checkpoint_protocol() {
            let (_database_root, _checkpoint_root, _database, _checkpoint, host) =
                fixture("authbus-concurrent-owner").await;
            let host = Arc::new(host);
            let mut tasks = Vec::new();
            for index in 1..=12 {
                let host = Arc::clone(&host);
                tasks.push(tokio::spawn(async move {
                    host.enroll_issuer(IssuerPurpose::Message, spec(index)).await
                }));
            }
            for task in tasks {
                task.await.expect("join mutation").expect("mutation");
            }
            let external = host.checkpoint.read().expect("external checkpoint");
            assert_eq!(
                host.store
                    .authority_checkpoint()
                    .await
                    .expect("local checkpoint"),
                Some(external)
            );
            for index in 1..=12 {
                host.message_issuer(
                    &StableId::new(format!("issuer:parallel:{index}")).unwrap(),
                    Generation::new(1).unwrap(),
                )
                .await
                .expect("issuer remains readable");
            }
        }

        #[tokio::test]
        async fn externally_published_checkpoint_is_promoted_after_ack_loss_and_reopen() {
            let (database_root, checkpoint_root, database, checkpoint, host) =
                fixture("authbus-ack-loss-owner").await;
            let enrolled = host
                .store
                .enroll_issuer(IssuerPurpose::Message, spec(41))
                .await
                .expect("commit owner mutation");
            let current = host.checkpoint.read().expect("current external checkpoint");
            let pending = host
                .store
                .reconcile_authority_checkpoint(current)
                .await
                .expect("compute pending checkpoint")
                .expect("dirty frontier");
            host.checkpoint
                .replace(current, pending)
                .expect("publish external checkpoint");
            drop(host);

            let reopened = AuthBusAuthorityHost::open(
                &database,
                checkpoint,
                "authbus-ack-loss-owner",
            )
            .await
            .expect("reopen after lost local acknowledgement");
            assert_eq!(
                reopened
                    .store
                    .authority_checkpoint()
                    .await
                    .expect("local checkpoint"),
                Some(pending)
            );
            reopened
                .message_issuer(&enrolled.issuer_id, enrolled.key_epoch)
                .await
                .expect("published mutation survives reopen");
            drop(reopened);
            drop(checkpoint_root);
            drop(database_root);
        }

        #[tokio::test]
        async fn failed_external_publish_leaves_recoverable_dirty_state() {
            let (_database_root, checkpoint_root, database, checkpoint, host) =
                fixture("authbus-publish-failure-owner").await;
            std::fs::set_permissions(
                checkpoint_root.path(),
                std::fs::Permissions::from_mode(0o500),
            )
            .expect("make checkpoint directory read only");
            let result = host
                .enroll_issuer(IssuerPurpose::Message, spec(42))
                .await;
            std::fs::set_permissions(
                checkpoint_root.path(),
                std::fs::Permissions::from_mode(0o700),
            )
            .expect("restore checkpoint permissions");
            assert!(result.is_err(), "external publish unexpectedly succeeded");

            host.sync_checkpoint()
                .await
                .expect("retry pending checkpoint publication");
            drop(host);
            let reopened = AuthBusAuthorityHost::open(
                &database,
                checkpoint,
                "authbus-publish-failure-owner",
            )
            .await
            .expect("reopen after recovered publication");
            reopened
                .message_issuer(
                    &StableId::new("issuer:parallel:42").unwrap(),
                    Generation::new(1).unwrap(),
                )
                .await
                .expect("committed mutation remains available");
        }
        '''
    ).lstrip(),
)

# Settlement regression coverage for owner-bound trust and dispatch-time ordering.
tests = "codex-rs/hepta-authbus/src/settlement_store_tests.rs"
replace_once(
    tests,
    "use crate::ReservationRequest;\nuse crate::SettlementEvidenceClaims;",
    "use crate::ReservationRequest;\nuse crate::IssuerSpec;\nuse crate::SettlementEvidenceClaims;",
)
replace_once(
    tests,
    "fn issuer(key: &SigningKey) -> SettlementIssuerRegistration {",
    dedent(
        """
        async fn enroll_issuer(store: &AuthBusAuthorityStore, key: &SigningKey) -> crate::IssuerRecord {
            store
                .enroll_issuer(
                    crate::IssuerPurpose::Settlement,
                    IssuerSpec {
                        issuer_id: id("issuer:settlement"),
                        key_epoch: Generation::new(1).expect("generation"),
                        verifying_key: key.verifying_key(),
                    },
                )
                .await
                .expect("enroll settlement issuer")
        }

        fn issuer(key: &SigningKey) -> SettlementIssuerRegistration {
        """
    ).strip(),
)
for needle in [
    "    let key = SigningKey::from_bytes(&[9; 32]);\n    let signed = evidence",
    "    let key = SigningKey::from_bytes(&[10; 32]);\n    let signed = evidence",
    "    let key = SigningKey::from_bytes(&[33; 32]);\n    let signed = evidence",
]:
    replacement = needle.replace("\n    let signed", "\n    let _issuer_record = enroll_issuer(&store, &key).await;\n    let signed")
    replace_once(tests, needle, replacement)
replace_once(
    tests,
    "    assert_eq!(\n        store\n            .settle(&issuer(&key), &signed, sample(7, 1_700))",
    "    let registered = store\n        .issuer_record(\n            crate::IssuerPurpose::Settlement,\n            &id(\"issuer:settlement\"),\n            Generation::new(1).unwrap(),\n        )\n        .await\n        .expect(\"registered issuer\");\n    store\n        .revoke_issuer(\n            crate::IssuerPurpose::Settlement,\n            &registered.issuer_id,\n            registered.key_epoch,\n            registered.revision,\n        )\n        .await\n        .expect(\"revoke after terminal commit\");\n    assert_eq!(\n        store\n            .settle(&issuer(&key), &signed, sample(7, 1_700))",
)
append_once(
    tests,
    "late_evidence_uses_dispatch_time_not_indeterminate_update_time",
    dedent(
        r'''
        #[tokio::test]
        async fn late_evidence_uses_dispatch_time_not_indeterminate_update_time() {
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
            let indeterminate = store
                .mark_indeterminate(
                    &reservation.reservation_id,
                    dispatched.revision,
                    sample(6, 1_700),
                )
                .await
                .expect("mark indeterminate");
            assert_eq!(indeterminate.dispatched_at_ms, Some(1_500));
            assert_eq!(indeterminate.updated_at_ms, 1_700);

            let key = SigningKey::from_bytes(&[44; 32]);
            let _issuer_record = enroll_issuer(&store, &key).await;
            let signed = evidence(&key, &dispatched, SettlementStatus::Completed, 5, 1_600);
            let settled = store
                .settle(&issuer(&key), &signed, sample(7, 1_800))
                .await
                .expect("late evidence after indeterminate transition");
            assert_eq!(settled.state, ReservationState::Settled);
        }

        #[tokio::test]
        async fn evidence_observed_before_dispatch_is_rejected() {
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
            let key = SigningKey::from_bytes(&[45; 32]);
            let _issuer_record = enroll_issuer(&store, &key).await;
            let signed = evidence(&key, &dispatched, SettlementStatus::Completed, 5, 1_499);
            assert!(matches!(
                store
                    .settle(&issuer(&key), &signed, sample(6, 1_600))
                    .await,
                Err(AuthBusAuthorityError::InvalidSettlementEvidence)
            ));
        }

        #[tokio::test]
        async fn cached_pre_revocation_registration_cannot_authorize_new_settlement() {
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
            let record = enroll_issuer(&store, &key).await;
            let cached = issuer(&key);
            store
                .revoke_issuer(
                    crate::IssuerPurpose::Settlement,
                    &record.issuer_id,
                    record.key_epoch,
                    record.revision,
                )
                .await
                .expect("revoke settlement issuer");
            let signed = evidence(&key, &dispatched, SettlementStatus::Completed, 5, 1_600);
            assert!(matches!(
                store.settle(&cached, &signed, sample(6, 1_600)).await,
                Err(AuthBusAuthorityError::SettlementIssuerRevoked)
            ));
        }

        #[tokio::test]
        async fn issuer_enrolled_for_wrong_purpose_cannot_settle() {
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
            let key = SigningKey::from_bytes(&[47; 32]);
            store
                .enroll_issuer(
                    crate::IssuerPurpose::Message,
                    IssuerSpec {
                        issuer_id: id("issuer:settlement"),
                        key_epoch: Generation::new(1).unwrap(),
                        verifying_key: key.verifying_key(),
                    },
                )
                .await
                .expect("enroll wrong-purpose issuer");
            let signed = evidence(&key, &dispatched, SettlementStatus::Completed, 5, 1_600);
            assert!(matches!(
                store
                    .settle(&issuer(&key), &signed, sample(6, 1_600))
                    .await,
                Err(AuthBusAuthorityError::IssuerMissing)
            ));
        }
        '''
    ),
)

# Restart must retain the physical dispatch boundary.
recovery_tests = "codex-rs/hepta-authbus/src/recovery_tests.rs"
replace_once(
    recovery_tests,
    "    let dispatched = store\n        .mark_dispatch_attempted(",
    "    let dispatched = store\n        .mark_dispatch_attempted(",
)
replace_once(
    recovery_tests,
    "        .await\n        .unwrap();\n    drop(store);\n\n    let reopened = AuthBusAuthorityStore::open(&path).await.unwrap();",
    "        .await\n        .unwrap();\n    assert_eq!(dispatched.dispatched_at_ms, Some(2_400));\n    drop(store);\n\n    let reopened = AuthBusAuthorityStore::open(&path).await.unwrap();",
)
replace_once(
    recovery_tests,
    "    assert_eq!(recovered.state, ReservationState::Indeterminate);",
    "    assert_eq!(recovered.state, ReservationState::Indeterminate);\n    assert_eq!(recovered.dispatched_at_ms, Some(2_400));",
)

# Recreate the historical signed-outbox crash window on the canonical evidence owner.
outbox_tests = "codex-rs/hepta-evidence/src/authbus_outbox_tests.rs"
append_once(
    outbox_tests,
    "externally_published_pending_checkpoint_promotes_after_reopen",
    dedent(
        r'''
        #[tokio::test]
        async fn externally_published_pending_checkpoint_promotes_after_reopen() {
            let temp = TempDir::new().unwrap();
            let sqlite = config(temp.path());
            let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
            let current = ReplayCheckpoint {
                generation: 1,
                digest: first.authbus_replay_frontier_digest().await.unwrap(),
            };
            first
                .initialize_authbus_restore_checkpoint(current)
                .await
                .unwrap();
            let delivery = enqueue(&first, 1).await;
            let pending = first
                .pending_authbus_restore_checkpoint()
                .await
                .unwrap()
                .expect("outbox mutation stages a successor checkpoint");
            assert_eq!(pending.generation, current.generation + 1);
            first.pool.close().await;

            // The external witness was durably replaced before the local
            // acknowledgement committed. Startup must promote that exact pending
            // successor rather than treating the old local generation as current.
            let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
            assert_eq!(
                reopened
                    .reconcile_authbus_restore_checkpoint(pending)
                    .await
                    .unwrap(),
                None
            );
            assert_eq!(
                reopened.authbus_restore_checkpoint().await.unwrap(),
                Some(pending)
            );
            assert_eq!(
                reopened
                    .pending_authbus_restore_checkpoint()
                    .await
                    .unwrap(),
                None
            );
            assert_eq!(
                reopened
                    .authbus_delivery_status(delivery.delivery_id)
                    .await
                    .unwrap()
                    .state,
                AuthBusDeliveryState::Queued
            );
        }
        '''
    ),
)

# Technical documentation: state the new owner and recovery semantics explicitly.
append_once(
    "docs/modules/auth.authbus/TECHNICAL.md",
    "## Correctness closure: settlement trust, dispatch time, and checkpoint serialization",
    dedent(
        """
        ## Correctness closure: settlement trust, dispatch time, and checkpoint serialization

        The authority owner applies three additional invariants:

        1. A settlement transition resolves the settlement issuer from
           `authbus_issuer_registry` inside the same `BEGIN IMMEDIATE` transaction that
           reads and updates the reservation. The public issuer registration argument is
           compatibility metadata only; its public key and cached revocation bit are not
           authority. A first terminal transition requires a currently active settlement
           issuer with the exact signed issuer ID and key epoch. After a terminal result is
           committed, an exact receipt retry remains queryable even if the issuer is later
           revoked; a previously unresolved effect cannot be newly settled by that revoked
           epoch.
        2. `dispatched_at_ms` is persisted once when `Held -> DispatchAttempted` commits.
           Settlement observation time is compared with this physical effect boundary, not
           with `updated_at_ms`, which may advance later when the reservation becomes
           `Indeterminate`. The dispatch timestamp is immutable, participates in the
           authority frontier, survives archive/restart, and is absent on never-dispatched
           `Held`, `Expired`, and `Cancelled` rows.
        3. One `AuthBusAuthorityHost` serializes every authoritative mutation through the
           complete SQLite commit -> external checkpoint replacement -> local checkpoint
           promotion protocol. Reads remain concurrent. A failed external publication
           leaves a committed dirty frontier that can be retried; startup promotes an exact
           externally published successor when the local acknowledgement was lost.

        The signed-delivery evidence owner has a regression for the corresponding crash
        cut: enqueue and pending replay checkpoint commit, the external witness advances,
        the process exits before local promotion, and reopen promotes the same generation
        without losing the queued delivery.
        """
    ),
)
append_once(
    "docs/lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md",
    "### 2026-09-25 correctness candidate",
    dedent(
        """
        ### 2026-09-25 correctness candidate

        The current candidate keeps the existing AuthBus authority architecture and closes
        four correctness gaps without introducing a parallel facade:

        - persistent settlement issuer lookup and revocation checking occur in the owner
          settlement transaction;
        - reservation records distinguish immutable physical dispatch time from later local
          state update time;
        - the named authority host serializes mutation and independent checkpoint
          publication as one protocol;
        - signed outbox recovery now has an explicit external-published/local-ack-lost
          reopen regression.

        `productionImplementation`, product execution proof, independent acceptance,
        activation, and release remain false until exact-head, deterministic merge-candidate,
        target-host, and external review gates complete.
        """
    ),
)
append_once(
    "qualification/module-execution-dossiers/detail/auth.authbus.md",
    "## 2026-09-25 correctness convergence candidate",
    dedent(
        """
        ## 2026-09-25 correctness convergence candidate

        This candidate binds settlement trust to the persistent issuer registry in the same
        transaction, persists an immutable dispatch timestamp, serializes the named host's
        mutation/checkpoint protocol, and adds crash/restart regressions for authority and
        signed-outbox checkpoint promotion. Repository-controlled verification is recorded
        by the pull request checks for the exact candidate; no skipped step is treated as a
        pass, and production/activation/release claims remain false.
        """
    ),
)

# Replace the stale three-operation navigation map with the actual owner/caller paths.
map_path = ROOT / "docs/modules/auth.authbus/IMPLEMENTATION_MAP.json"
implementation_map = json.loads(map_path.read_text(encoding="utf-8"))
implementation_map.update(
    {
        "productCallerState": "composed_candidate_pending_exact_execution",
        "productionWriterState": "named_authbus_authority_host_candidate",
        "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
        "observedSourcePaths": [
            "codex-rs/Cargo.lock",
            "codex-rs/Cargo.toml",
            "codex-rs/hepta-authbus",
            "codex-rs/hepta-authbus-p1-3-qualification",
        ],
        "productCallers": [
            {
                "sourcePath": "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
                "nativeSymbol": "consume_kv_v2_with_authbus",
                "state": "named_product_effect_path_candidate_pending_exact_execution",
            },
            {
                "sourcePath": "codex-rs/hepta-agentd/src/authbus_ingress.rs",
                "nativeSymbol": "submit",
                "state": "signed_text_ingress_and_checkpoint_host_candidate",
            },
        ],
        "operations": [
            {
                "operation": "authenticate",
                "nativeSymbol": "authenticate",
                "sourcePath": "codex-rs/hepta-authbus/src/signed.rs",
                "state": "source_implemented_product_composed_candidate",
                "authority": "none",
                "tests": ["codex-rs/hepta-authbus/src/signed_tests.rs"],
                "sourcePathExists": True,
                "designOperation": "authenticate",
                "mappingClass": "owner_native",
                "delegatedCallees": [],
            },
            {
                "operation": "manage_issuer_lifecycle",
                "nativeSymbol": "enroll_issuer",
                "sourcePath": "codex-rs/hepta-authbus/src/trust_store.rs",
                "state": "persistent_owner_candidate",
                "authority": "none",
                "tests": ["codex-rs/hepta-authbus/src/trust_store_tests.rs"],
                "sourcePathExists": True,
                "designOperation": "manage_issuer_lifecycle",
                "mappingClass": "owner_native",
                "delegatedCallees": [],
            },
            {
                "operation": "authorize",
                "nativeSymbol": "authorize",
                "sourcePath": "codex-rs/hepta-authbus/src/authority_store.rs",
                "state": "persistent_owner_candidate",
                "authority": "none",
                "tests": ["codex-rs/hepta-authbus/src/authority_store_tests.rs"],
                "sourcePathExists": True,
                "designOperation": "authorize",
                "mappingClass": "owner_native",
                "delegatedCallees": [],
            },
            {
                "operation": "reserve_quota",
                "nativeSymbol": "reserve",
                "sourcePath": "codex-rs/hepta-authbus/src/quota_store.rs",
                "state": "persistent_owner_candidate",
                "authority": "none",
                "tests": ["codex-rs/hepta-authbus/src/quota_store_tests.rs"],
                "sourcePathExists": True,
                "designOperation": "reserve_quota",
                "mappingClass": "owner_native",
                "delegatedCallees": [],
            },
            {
                "operation": "mark_dispatch_attempted",
                "nativeSymbol": "mark_dispatch_attempted",
                "sourcePath": "codex-rs/hepta-authbus/src/settlement_store.rs",
                "state": "persistent_physical_boundary_candidate",
                "authority": "none",
                "tests": ["codex-rs/hepta-authbus/src/settlement_store_tests.rs"],
                "sourcePathExists": True,
                "designOperation": "mark_dispatch_attempted",
                "mappingClass": "owner_native",
                "delegatedCallees": [],
            },
            {
                "operation": "settle",
                "nativeSymbol": "settle",
                "sourcePath": "codex-rs/hepta-authbus/src/settlement_store.rs",
                "state": "persistent_owner_bound_trust_candidate",
                "authority": "none",
                "tests": ["codex-rs/hepta-authbus/src/settlement_store_tests.rs"],
                "sourcePathExists": True,
                "designOperation": "settle",
                "mappingClass": "owner_native",
                "delegatedCallees": ["codex-rs/hepta-authbus/src/trust_store.rs"],
            },
            {
                "operation": "publish_authority_checkpoint",
                "nativeSymbol": "sync_checkpoint",
                "sourcePath": "codex-rs/hepta-authbus/src/host.rs",
                "state": "serialized_named_host_candidate",
                "authority": "none",
                "tests": ["codex-rs/hepta-authbus/src/host_tests.rs"],
                "sourcePathExists": True,
                "designOperation": "publish_authority_checkpoint",
                "mappingClass": "owner_native",
                "delegatedCallees": ["codex-rs/hepta-authbus/src/recovery.rs"],
            },
            {
                "operation": "enqueue_authbus_message",
                "nativeSymbol": "enqueue_authbus_message",
                "sourcePath": "codex-rs/hepta-evidence/src/authbus_outbox.rs",
                "state": "durable_signed_outbox_product_candidate",
                "authority": "none",
                "tests": ["codex-rs/hepta-evidence/src/authbus_outbox_tests.rs"],
                "sourcePathExists": True,
                "designOperation": "enqueue_authbus_message",
                "mappingClass": "delegated_persistent_owner",
                "delegatedCallees": ["codex-rs/hepta-agentd/src/authbus_ingress.rs"],
            },
            {
                "operation": "reconcile_authbus_restore_checkpoint",
                "nativeSymbol": "reconcile_authbus_restore_checkpoint",
                "sourcePath": "codex-rs/hepta-evidence/src/authbus_recovery.rs",
                "state": "external_witness_recovery_candidate",
                "authority": "none",
                "tests": [
                    "codex-rs/hepta-evidence/src/authbus_recovery_tests.rs",
                    "codex-rs/hepta-evidence/src/authbus_outbox_tests.rs",
                ],
                "sourcePathExists": True,
                "designOperation": "reconcile_authbus_restore_checkpoint",
                "mappingClass": "delegated_persistent_owner",
                "delegatedCallees": ["codex-rs/hepta-agentd/src/authbus_checkpoint.rs"],
            },
        ],
        "repositoryControlledGaps": [
            "Run and retain exact-candidate focused package, strict lint, product composition, and deterministic synthetic-merge verification before changing productExecutionProved.",
            "Retain a single named AuthBusAuthorityHost per authority database/checkpoint owner and qualify target-host filesystem durability and operator recovery procedures.",
        ],
        "externalEvidenceGates": [
            "independent semantic and security review",
            "target-host filesystem, SQLite and crash-cut qualification",
            "operator acceptance, canary, promotion and release",
        ],
    }
)
implementation_map["productionImplementation"] = False
implementation_map["claimBoundary"] = {
    "nativeSourceMappingComplete": True,
    "sourceRootPresent": True,
    "productionImplementation": False,
    "productExecutionProved": False,
    "independentAcceptance": False,
    "activation": False,
    "release": False,
    "implementedOperationMappingComplete": True,
}
map_path.write_text(json.dumps(implementation_map, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print("auth.authbus convergence patch applied")
