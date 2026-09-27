"""Apply the reviewed recovery slice, failing on unexpected predecessor source.
This bootstrap is removed after plain Rust/SQL sources have been committed.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
def replace(path, before, after):
    p = ROOT / path
    text = p.read_text()
    if text.count(before) != 1:
        raise RuntimeError(f"unexpected predecessor: {path}: {before[:70]!r}")
    p.write_text(text.replace(before, after, 1))

def create(path, text):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise RuntimeError(f"refusing overwrite: {path}")
    p.write_text(text)

create("codex-rs/hepta-authbus/migrations/0005_operation_admission_fence.sql", """-- Absence is sealed under the same SQLite write transaction as reserve.
CREATE TABLE authbus_operation_admission_fence (
    operation_id TEXT PRIMARY KEY,
    effect_digest BLOB NOT NULL CHECK(length(effect_digest) = 32)
) WITHOUT ROWID;
CREATE TRIGGER authbus_admission_fence_no_update
BEFORE UPDATE ON authbus_operation_admission_fence
BEGIN SELECT RAISE(ABORT, 'immutable operation admission fence'); END;
CREATE TRIGGER authbus_admission_fence_no_delete
BEFORE DELETE ON authbus_operation_admission_fence
BEGIN SELECT RAISE(ABORT, 'cannot forget operation admission fence'); END;
CREATE TRIGGER authbus_admission_fence_no_reservation
BEFORE INSERT ON authbus_operation_admission_fence
WHEN EXISTS(SELECT 1 FROM authbus_quota_reservation WHERE operation_id = NEW.operation_id)
 OR EXISTS(SELECT 1 FROM authbus_quota_reservation_archive WHERE operation_id = NEW.operation_id)
BEGIN SELECT RAISE(ABORT, 'operation already has a reservation'); END;
CREATE TRIGGER authbus_reservation_admission_fenced
BEFORE INSERT ON authbus_quota_reservation
WHEN EXISTS(SELECT 1 FROM authbus_operation_admission_fence WHERE operation_id = NEW.operation_id)
BEGIN SELECT RAISE(ABORT, 'operation admission is fenced'); END;
CREATE TRIGGER authbus_dirty_admission_fence AFTER INSERT ON authbus_operation_admission_fence
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
""")

p = ROOT / "codex-rs/hepta-authbus/src/operation_lookup.rs"
s = p.read_text()
a = s.index("        let current:")
b = s.index("\n    }\n}", a)
s = s[:a] + """        let mut tx = crate::authority_store::begin(&self.pool).await?;
        let result = crate::quota_store::load_reservation_by_operation(&mut tx, operation_id).await?;
        tx.commit().await.map_err(storage)?;
        Ok(result)""" + s[b:]
addition = """
    /// Seal non-admission under reserve's SQLite write transaction. None is a
    /// durable fence, not a read-only absence. Existing reservations are returned
    /// unchanged so recovery can observe/cancel the original reservation.
    pub async fn seal_unreserved_operation(
        &self,
        operation_id: &StableId,
        effect_digest: codex_hepta_types::Digest32,
    ) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
        if effect_digest.is_zero() {
            return Err(AuthBusAuthorityError::InvalidInput("empty operation effect"));
        }
        let mut tx = crate::authority_store::begin(&self.pool).await?;
        if let Some(existing) = crate::quota_store::load_reservation_by_operation(&mut tx, operation_id).await? {
            if existing.effect_digest != effect_digest {
                return Err(AuthBusAuthorityError::IdempotencyConflict);
            }
            tx.commit().await.map_err(storage)?;
            return Ok(Some(existing));
        }
        let existing: Option<Vec<u8>> = sqlx::query_scalar(
            "SELECT effect_digest FROM authbus_operation_admission_fence WHERE operation_id = ?",
        ).bind(operation_id.as_str()).fetch_optional(&mut *tx).await.map_err(storage)?;
        if let Some(existing) = existing {
            if existing.as_slice() != effect_digest.as_array() {
                return Err(AuthBusAuthorityError::IdempotencyConflict);
            }
        } else {
            let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_operation_admission_fence")
                .fetch_one(&mut *tx).await.map_err(storage)?;
            if count >= 65_536 {
                return Err(AuthBusAuthorityError::CapacityExceeded);
            }
            sqlx::query("INSERT INTO authbus_operation_admission_fence(operation_id, effect_digest) VALUES (?, ?)")
                .bind(operation_id.as_str()).bind(effect_digest.as_array().as_slice())
                .execute(&mut *tx).await.map_err(storage)?;
        }
        tx.commit().await.map_err(storage)?;
        Ok(None)
    }
"""
pos = s.index("\n}\n\n#[cfg(test)]")
p.write_text(s[:pos] + addition + s[pos:])
replace("codex-rs/hepta-authbus/src/quota_store.rs", "async fn load_reservation_by_operation(", "pub(crate) async fn load_reservation_by_operation(")
replace("codex-rs/hepta-authbus/src/quota_store.rs", "        let policy = load_policy_by_id(&mut tx, decision.policy_id()).await?;", """        let sealed: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_operation_admission_fence WHERE operation_id = ?",
        ).bind(request.operation_id.as_str()).fetch_one(&mut *tx).await.map_err(storage)?;
        if sealed != 0 {
            return Err(AuthBusAuthorityError::IdempotencyConflict);
        }
        let policy = load_policy_by_id(&mut tx, decision.policy_id()).await?;""")
replace("codex-rs/hepta-authbus/src/host.rs", "    /// Find the unique hot or archived reservation for an operation identity.", """    /// Publish the non-admission fence through the existing checkpoint owner.
    pub async fn seal_unreserved_operation(
        &self,
        operation_id: &StableId,
        effect_digest: Digest32,
    ) -> Result<Option<QuotaReservation>, AuthBusAuthorityError> {
        let result = self.store.seal_unreserved_operation(operation_id, effect_digest).await;
        self.finish(result).await
    }

    /// Find the unique hot or archived reservation for an operation identity.""")
replace("codex-rs/hepta-authbus/src/recovery.rs", "    Ok(Digest32::of_bytes(&bytes))\n}", """    // Empty migration preserves the previous checkpoint digest. Every actual
    // admission fence participates in the independently published frontier.
    let seals: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_operation_admission_fence")
        .fetch_one(&mut **tx).await.map_err(storage)?;
    if seals != 0 {
        append_rows(tx, &mut bytes, "operation_admission_fence",
            "SELECT operation_id||'|'||hex(effect_digest) FROM authbus_operation_admission_fence ORDER BY operation_id").await?;
    }
    Ok(Digest32::of_bytes(&bytes))
}""")
create("codex-rs/hepta-bao-adapter/src/operation_execution.rs", """//! Registry-shared live operation exclusion; no mutex is held across an await.
//! Cancellation releases this guard. The durable AuthBus seal separately fences
//! a late reserve commit, so exclusion is never mistaken for persistent proof.
use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};
use crate::LeaseRegistryErrorV1;

#[derive(Default)]
pub(crate) struct OperationExecutionSet {
    active: Arc<Mutex<BTreeSet<String>>>,
}
impl OperationExecutionSet {
    pub(crate) fn enter(&self, id: &str) -> Result<OperationExecutionGuard, LeaseRegistryErrorV1> {
        let mut active = self.active.lock().map_err(|_| LeaseRegistryErrorV1::Fenced)?;
        if active.contains(id) {
            return Err(LeaseRegistryErrorV1::WriterBusy);
        }
        if active.len() >= 4096 {
            return Err(LeaseRegistryErrorV1::CapacityExceeded);
        }
        active.insert(id.to_owned());
        Ok(OperationExecutionGuard { active: Arc::clone(&self.active), id: id.to_owned() })
    }
}
pub(crate) struct OperationExecutionGuard {
    active: Arc<Mutex<BTreeSet<String>>>,
    id: String,
}
impl Drop for OperationExecutionGuard {
    fn drop(&mut self) {
        if let Ok(mut active) = self.active.lock() {
            active.remove(&self.id);
        }
    }
}
#[cfg(test)]
#[path = "operation_execution_tests.rs"]
mod tests;
""")
create("codex-rs/hepta-bao-adapter/src/operation_execution_tests.rs", """use super::*;
#[test]
fn concurrent_same_operation_is_busy_and_drop_releases_only_its_identity() {
    let executions = OperationExecutionSet::default();
    let first = executions.enter("operation:a").unwrap();
    let second = executions.enter("operation:b").unwrap();
    assert!(matches!(executions.enter("operation:a"), Err(LeaseRegistryErrorV1::WriterBusy)));
    drop(first);
    let again = executions.enter("operation:a").unwrap();
    assert!(matches!(executions.enter("operation:b"), Err(LeaseRegistryErrorV1::WriterBusy)));
    drop((again, second));
    assert!(executions.active.lock().unwrap().is_empty());
}
#[test]
fn unwind_releases_operation_without_poisoning_registry() {
    let executions = OperationExecutionSet::default();
    let result = std::panic::catch_unwind(|| {
        let _guard = executions.enter("operation:unwind").unwrap();
        panic!("synthetic callback panic");
    });
    assert!(result.is_err());
    assert!(executions.enter("operation:unwind").is_ok());
}
""")
replace("codex-rs/hepta-bao-adapter/src/lib.rs", "mod final_use_host;", "mod final_use_host;\nmod operation_execution;")
replace("codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs", "pub struct DurableLeaseRegistryV1 {", "pub struct DurableLeaseRegistryV1 {\n    executions: crate::operation_execution::OperationExecutionSet,")
replace("codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs", "        Ok(Self {\n            path,", "        Ok(Self {\n            executions: Default::default(),\n            path,")
replace("codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs", "    pub fn open(path: impl Into<PathBuf>)", """    pub(crate) fn enter_consumption_execution(&self, id: &str) -> Result<crate::operation_execution::OperationExecutionGuard, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        self.executions.enter(id)
    }

    pub fn open(path: impl Into<PathBuf>)""")
p = ROOT / "codex-rs/hepta-bao-adapter/src/final_use_host.rs"
s = p.read_text()
old = "        let operation_id = admission.operation_id.as_str();"
assert s.count(old) == 1
s = s.replace(old, old + """
        let _execution = registry.lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .enter_consumption_execution(operation_id)
            .map_err(BaoProductHostError::Store)?;""", 1)
old = "    ) -> Result<BaoSecretReceipt, BaoProductHostError> {\n        let mut row = registry"
assert s.count(old) == 1
s = s.replace(old, """    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let _execution = registry.lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .enter_consumption_execution(operation_id)
            .map_err(BaoProductHostError::Store)?;
        let mut row = registry""", 1)
a = s.index("        if authbus\n", s.index("    async fn close_unreserved_failure_if_proved"))
b = s.index("        let evidence = Digest32::of_bytes(", a)
s = s[:a] + """        let row = registry.lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id).map_err(BaoProductHostError::Store)?;
        if row.state != BaoConsumptionStateV1::Claimed {
            return Ok(None);
        }
        if authbus.seal_unreserved_operation(&operation, Digest32::from_array(row.effect_sha256))
            .await.map_err(|error| BaoProductHostError::AuthBus(error.into()))?.is_some() {
            return Ok(None);
        }
""" + s[b:]
old = "            None => authbus\n                .reservation_by_operation(&stable_operation)"
assert s.count(old) == 1
s = s.replace(old, "            None => authbus\n                .seal_unreserved_operation(&stable_operation, Digest32::from_array(row.effect_sha256))", 1)
p.write_text(s)

p = ROOT / "codex-rs/hepta-authbus/src/operation_lookup_tests.rs"
s = p.read_text()
a = s.index('    let root = tempfile::tempdir()')
b = s.index('    let operation_id = id("operation:lookup");', a)
setup = s[a:b]
s += """
async fn admission_fixture() -> (tempfile::TempDir, AuthBusAuthorityStore, crate::PolicyDecision, ReservationRequest) {
""" + setup + """
    let request = ReservationRequest {
        quota_key: quota.quota_key,
        operation_id: id("operation:admission-race"),
        amount: 1,
        effect_digest: Digest32::of_bytes(b"admission-race-effect"),
        expected_quota_revision: quota.revision,
        expires_at_ms: 10_000,
    };
    (root, store, decision, request)
}
#[tokio::test]
async fn sealed_absence_is_idempotent_durable_and_rejects_late_reserve() {
    let (root, store, decision, request) = admission_fixture().await;
    let before = store.authority_frontier_digest().await.unwrap();
    assert_eq!(store.seal_unreserved_operation(&request.operation_id, request.effect_digest).await.unwrap(), None);
    let sealed = store.authority_frontier_digest().await.unwrap();
    assert_ne!(before, sealed);
    assert_eq!(store.seal_unreserved_operation(&request.operation_id, request.effect_digest).await.unwrap(), None);
    assert_eq!(store.authority_frontier_digest().await.unwrap(), sealed);
    assert!(matches!(store.seal_unreserved_operation(&request.operation_id, Digest32::of_bytes(b"changed")).await,
        Err(AuthBusAuthorityError::IdempotencyConflict)));
    drop(store);
    let store = AuthBusAuthorityStore::open(&root.path().join("authority.sqlite")).await.unwrap();
    assert!(matches!(store.reserve(&decision, request, time(4, 1_400)).await,
        Err(AuthBusAuthorityError::IdempotencyConflict)));
}
#[tokio::test]
async fn admission_seal_returns_original_reservation_without_cancelling_it() {
    let (_root, store, decision, request) = admission_fixture().await;
    let operation = request.operation_id.clone();
    let effect = request.effect_digest;
    let reservation = store.reserve(&decision, request, time(4, 1_400)).await.unwrap();
    assert_eq!(store.seal_unreserved_operation(&operation, effect).await.unwrap(), Some(reservation));
}
#[tokio::test]
async fn concurrent_seal_and_reserve_have_one_serializable_outcome() {
    for _ in 0..12 {
        let (_root, store, decision, request) = admission_fixture().await;
        let operation = request.operation_id.clone();
        let effect = request.effect_digest;
        let (reserved, sealed) = tokio::join!(
            store.reserve(&decision, request, time(4, 1_400)),
            store.seal_unreserved_operation(&operation, effect),
        );
        match (reserved, sealed.unwrap()) {
            (Ok(reservation), Some(observed)) => assert_eq!(reservation, observed),
            (Err(AuthBusAuthorityError::IdempotencyConflict), None) => {},
            other => panic!("non-serializable admission outcome: {other:?}"),
        }
    }
}
#[tokio::test]
async fn admission_seal_cannot_be_removed_or_rebound_by_sql() {
    let (_root, store, _decision, request) = admission_fixture().await;
    store.seal_unreserved_operation(&request.operation_id, request.effect_digest).await.unwrap();
    for sql in [
        "DELETE FROM authbus_operation_admission_fence",
        "UPDATE authbus_operation_admission_fence SET effect_digest = zeroblob(32)",
    ] {
        assert!(sqlx::query(sql).execute(&store.pool).await.is_err());
    }
}
"""
p.write_text(s)
p = ROOT / "docs/modules/secrets.heptabao/MODULE_MANIFEST_V1.json"
m = json.loads(p.read_text())
for row in m["recoveryStates"]:
    if row["state"] == "Claimed":
        row["recovery"] = "atomically seal absent AuthBus admission for the exact operation/effect or bind the original reservation; SELECT absence is not proof"
for row in m["sourceAnchors"]:
    if row["path"].endswith("operation_lookup.rs"):
        row["mustContain"] = ["reservation_by_operation", "seal_unreserved_operation", "authbus_operation_admission_fence"]
p.write_text(json.dumps(m, indent=2) + "\n")
print("Applied serializable admission fence, registry single flight, and native regressions.")
