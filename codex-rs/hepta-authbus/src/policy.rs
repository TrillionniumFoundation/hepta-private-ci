use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::Acquire;
use sqlx::Row;
use sqlx::SqlitePool;

const POLICY_DB_FILENAME: &str = "hepta_auth_policy_1.sqlite";
const MAX_POLICY_RULES: usize = 4_096;
const MAX_POLICY_REVISIONS: i64 = 1_024;
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct PolicyRuleV1 {
    pub principal_id: StableId,
    pub action_id: StableId,
    pub resource_id: StableId,
    pub allowed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyRevisionDraftV1 {
    pub revision: Revision,
    pub source_digest: Digest32,
    pub rules: Vec<PolicyRuleV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyDecisionV1 {
    pub revision: Revision,
    pub policy_digest: Digest32,
    pub principal_id: StableId,
    pub action_id: StableId,
    pub resource_id: StableId,
    pub allowed: bool,
    pub decision_digest: Digest32,
}

#[derive(Debug)]
pub enum PolicyError {
    Invalid(String),
    Unavailable(String),
    Corrupt(String),
    NotConfigured,
    StaleRevision {
        expected: Revision,
        current: Revision,
    },
    Conflict(String),
    CapacityExceeded,
}

impl fmt::Display for PolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid auth policy: {message}"),
            Self::Unavailable(message) => write!(formatter, "auth policy unavailable: {message}"),
            Self::Corrupt(message) => write!(formatter, "auth policy corrupt: {message}"),
            Self::NotConfigured => formatter.write_str("auth policy is not configured"),
            Self::StaleRevision { expected, current } => write!(
                formatter,
                "auth policy revision is stale: expected {}, current {}",
                expected.get(),
                current.get()
            ),
            Self::Conflict(message) => write!(formatter, "auth policy conflict: {message}"),
            Self::CapacityExceeded => formatter.write_str("auth policy capacity exceeded"),
        }
    }
}

impl std::error::Error for PolicyError {}

#[derive(Clone, Debug)]
pub struct AuthPolicyStore {
    pool: SqlitePool,
    path: PathBuf,
}

impl AuthPolicyStore {
    pub async fn open(root: &Path) -> Result<Self, PolicyError> {
        tokio::fs::create_dir_all(root).await.map_err(unavailable)?;
        let home = AbsolutePathBuf::try_from(root.to_path_buf())
            .map_err(|error| PolicyError::Invalid(error.to_string()))?;
        let path = root.join(POLICY_DB_FILENAME);
        let pool = SqliteConfig::from_sqlite_home(home)
            .open_durable_evidence_pool(&path)
            .await
            .map_err(unavailable)?;
        if let Err(error) = MIGRATOR.run(&pool).await {
            pool.close().await;
            return Err(PolicyError::Unavailable(error.to_string()));
        }
        if let Err(error) = verify_store(&pool).await {
            pool.close().await;
            return Err(error);
        }
        Ok(Self { pool, path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    pub async fn publish_revision(
        &self,
        draft: PolicyRevisionDraftV1,
    ) -> Result<Digest32, PolicyError> {
        let normalized = normalize_draft(draft)?;
        let policy_digest = policy_digest(
            normalized.revision,
            normalized.source_digest,
            &normalized.rules,
        );
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;

        let current = sqlx::query(
            "SELECT revision, policy_digest FROM auth_policy_current WHERE singleton=1",
        )
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;

        if let Some(current) = current {
            let current_revision = revision(
                current
                    .try_get::<i64, _>("revision")
                    .map_err(unavailable)?,
            )?;
            let current_digest = parse_digest(
                &current
                    .try_get::<String, _>("policy_digest")
                    .map_err(unavailable)?,
                "current policy",
            )?;
            if current_revision == normalized.revision {
                if current_digest != policy_digest {
                    return Err(PolicyError::Conflict(
                        "revision reused with changed policy".to_string(),
                    ));
                }
                verify_revision_tx(
                    &mut transaction,
                    normalized.revision,
                    policy_digest,
                    normalized.source_digest,
                    &normalized.rules,
                )
                .await?;
                transaction.commit().await.map_err(unavailable)?;
                return Ok(policy_digest);
            }
            if normalized.revision <= current_revision {
                return Err(PolicyError::StaleRevision {
                    expected: normalized.revision,
                    current: current_revision,
                });
            }
        }

        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM auth_policy_revisions")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if count >= MAX_POLICY_REVISIONS {
            return Err(PolicyError::CapacityExceeded);
        }

        sqlx::query(
            "INSERT INTO auth_policy_revisions
             (revision, policy_digest, source_digest, rule_count)
             VALUES (?, ?, ?, ?)",
        )
        .bind(to_i64(normalized.revision.get(), "policy revision")?)
        .bind(policy_digest.to_string())
        .bind(normalized.source_digest.to_string())
        .bind(i64::try_from(normalized.rules.len()).map_err(invalid)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;

        for rule in &normalized.rules {
            sqlx::query(
                "INSERT INTO auth_policy_rules
                 (revision, principal_id, action_id, resource_id, allowed)
                 VALUES (?, ?, ?, ?, ?)",
            )
            .bind(to_i64(normalized.revision.get(), "policy revision")?)
            .bind(rule.principal_id.as_str())
            .bind(rule.action_id.as_str())
            .bind(rule.resource_id.as_str())
            .bind(if rule.allowed { 1_i64 } else { 0_i64 })
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
        }

        sqlx::query(
            "INSERT INTO auth_policy_current(singleton, revision, policy_digest)
             VALUES (1, ?, ?)
             ON CONFLICT(singleton) DO UPDATE SET
               revision=excluded.revision,
               policy_digest=excluded.policy_digest",
        )
        .bind(to_i64(normalized.revision.get(), "policy revision")?)
        .bind(policy_digest.to_string())
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;

        transaction.commit().await.map_err(unavailable)?;
        Ok(policy_digest)
    }

    pub async fn authorize(
        &self,
        principal_id: &StableId,
        action_id: &StableId,
        resource_id: &StableId,
        expected_revision: Revision,
    ) -> Result<PolicyDecisionV1, PolicyError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let current = sqlx::query(
            "SELECT revision, policy_digest FROM auth_policy_current WHERE singleton=1",
        )
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?
        .ok_or(PolicyError::NotConfigured)?;
        let current_revision = revision(
            current
                .try_get::<i64, _>("revision")
                .map_err(unavailable)?,
        )?;
        if current_revision != expected_revision {
            return Err(PolicyError::StaleRevision {
                expected: expected_revision,
                current: current_revision,
            });
        }
        let digest = parse_digest(
            &current
                .try_get::<String, _>("policy_digest")
                .map_err(unavailable)?,
            "current policy",
        )?;
        let allowed: Option<i64> = sqlx::query_scalar(
            "SELECT allowed FROM auth_policy_rules
             WHERE revision=? AND principal_id=? AND action_id=? AND resource_id=?",
        )
        .bind(to_i64(current_revision.get(), "policy revision")?)
        .bind(principal_id.as_str())
        .bind(action_id.as_str())
        .bind(resource_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)?;

        let allowed = match allowed {
            Some(0) | None => false,
            Some(1) => true,
            Some(_) => return Err(corrupt("policy allowed flag is outside 0/1")),
        };
        Ok(PolicyDecisionV1 {
            revision: current_revision,
            policy_digest: digest,
            principal_id: principal_id.clone(),
            action_id: action_id.clone(),
            resource_id: resource_id.clone(),
            allowed,
            decision_digest: decision_digest(
                current_revision,
                digest,
                principal_id,
                action_id,
                resource_id,
                allowed,
            ),
        })
    }

    pub async fn current_revision(&self) -> Result<Option<Revision>, PolicyError> {
        let value: Option<i64> =
            sqlx::query_scalar("SELECT revision FROM auth_policy_current WHERE singleton=1")
                .fetch_optional(&self.pool)
                .await
                .map_err(unavailable)?;
        value.map(revision).transpose()
    }
}

fn normalize_draft(mut draft: PolicyRevisionDraftV1) -> Result<PolicyRevisionDraftV1, PolicyError> {
    if draft.source_digest.is_zero() {
        return Err(PolicyError::Invalid(
            "source digest must be non-zero".to_string(),
        ));
    }
    if draft.rules.len() > MAX_POLICY_RULES {
        return Err(PolicyError::CapacityExceeded);
    }
    draft.rules.sort();
    if draft.rules.windows(2).any(|pair| {
        pair[0].principal_id == pair[1].principal_id
            && pair[0].action_id == pair[1].action_id
            && pair[0].resource_id == pair[1].resource_id
    }) {
        return Err(PolicyError::Conflict(
            "duplicate principal/action/resource rule".to_string(),
        ));
    }
    Ok(draft)
}

fn policy_digest(revision: Revision, source: Digest32, rules: &[PolicyRuleV1]) -> Digest32 {
    let mut bytes = b"hepta.authbus.policy.v1\0".to_vec();
    bytes.extend_from_slice(&revision.get().to_be_bytes());
    bytes.extend_from_slice(source.as_array());
    bytes.extend_from_slice(
        &u32::try_from(rules.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for rule in rules {
        push_id(&mut bytes, &rule.principal_id);
        push_id(&mut bytes, &rule.action_id);
        push_id(&mut bytes, &rule.resource_id);
        bytes.push(u8::from(rule.allowed));
    }
    Digest32::of_bytes(&bytes)
}

fn decision_digest(
    revision: Revision,
    policy_digest: Digest32,
    principal: &StableId,
    action: &StableId,
    resource: &StableId,
    allowed: bool,
) -> Digest32 {
    let mut bytes = b"hepta.authbus.policy-decision.v1\0".to_vec();
    bytes.extend_from_slice(&revision.get().to_be_bytes());
    bytes.extend_from_slice(policy_digest.as_array());
    push_id(&mut bytes, principal);
    push_id(&mut bytes, action);
    push_id(&mut bytes, resource);
    bytes.push(u8::from(allowed));
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
}

async fn verify_store(pool: &SqlitePool) -> Result<(), PolicyError> {
    let quick: String = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_one(pool)
        .await
        .map_err(unavailable)?;
    if quick != "ok" {
        return Err(corrupt("SQLite quick_check failed"));
    }
    let foreign_keys = sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if !foreign_keys.is_empty() {
        return Err(corrupt("SQLite foreign_key_check failed"));
    }
    let migrations = sqlx::query(
        "SELECT version,description,success,checksum
         FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    if migrations.len() != MIGRATOR.migrations.len() {
        return Err(corrupt("migration ledger does not match current lineage"));
    }
    for (row, migration) in migrations.iter().zip(MIGRATOR.migrations.iter()) {
        let version: i64 = row.try_get("version").map_err(unavailable)?;
        let description: String = row.try_get("description").map_err(unavailable)?;
        let success: bool = row.try_get("success").map_err(unavailable)?;
        let checksum: Vec<u8> = row.try_get("checksum").map_err(unavailable)?;
        if version != migration.version
            || description != migration.description.as_ref()
            || !success
            || checksum.as_slice() != migration.checksum.as_ref()
        {
            return Err(corrupt(
                "migration ledger entry differs from current lineage",
            ));
        }
    }
    let trigger_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_schema
         WHERE type='trigger' AND name IN (
           'auth_policy_revisions_no_update',
           'auth_policy_revisions_no_delete',
           'auth_policy_rules_no_update',
           'auth_policy_rules_no_delete'
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if trigger_count != 4 {
        return Err(corrupt("immutable policy triggers are missing"));
    }

    let revisions = sqlx::query(
        "SELECT revision, policy_digest, source_digest, rule_count
         FROM auth_policy_revisions ORDER BY revision",
    )
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    if revisions.len() > usize::try_from(MAX_POLICY_REVISIONS).map_err(invalid)? {
        return Err(corrupt("policy revision capacity exceeded"));
    }
    for row in &revisions {
        let rev = revision(row.try_get::<i64, _>("revision").map_err(unavailable)?)?;
        let stored_policy = parse_digest(
            &row.try_get::<String, _>("policy_digest")
                .map_err(unavailable)?,
            "policy",
        )?;
        let source = parse_digest(
            &row.try_get::<String, _>("source_digest")
                .map_err(unavailable)?,
            "policy source",
        )?;
        let expected_count = row.try_get::<i64, _>("rule_count").map_err(unavailable)?;
        let rule_rows = sqlx::query(
            "SELECT principal_id, action_id, resource_id, allowed
             FROM auth_policy_rules WHERE revision=?
             ORDER BY principal_id, action_id, resource_id",
        )
        .bind(to_i64(rev.get(), "policy revision")?)
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
        if i64::try_from(rule_rows.len()).map_err(invalid)? != expected_count {
            return Err(corrupt("policy revision rule count mismatch"));
        }
        let mut rules = Vec::with_capacity(rule_rows.len());
        for rule in rule_rows {
            let allowed: i64 = rule.try_get("allowed").map_err(unavailable)?;
            rules.push(PolicyRuleV1 {
                principal_id: StableId::new(
                    rule.try_get::<String, _>("principal_id")
                        .map_err(unavailable)?,
                )
                .map_err(invalid)?,
                action_id: StableId::new(
                    rule.try_get::<String, _>("action_id")
                        .map_err(unavailable)?,
                )
                .map_err(invalid)?,
                resource_id: StableId::new(
                    rule.try_get::<String, _>("resource_id")
                        .map_err(unavailable)?,
                )
                .map_err(invalid)?,
                allowed: match allowed {
                    0 => false,
                    1 => true,
                    _ => return Err(corrupt("policy allowed flag is outside 0/1")),
                },
            });
        }
        if policy_digest(rev, source, &rules) != stored_policy {
            return Err(corrupt("policy digest does not match immutable rules"));
        }
    }

    let current = sqlx::query(
        "SELECT revision, policy_digest FROM auth_policy_current WHERE singleton=1",
    )
    .fetch_optional(pool)
    .await
    .map_err(unavailable)?;
    match (revisions.last(), current) {
        (None, None) => {}
        (Some(latest), Some(current)) => {
            let latest_revision: i64 = latest.try_get("revision").map_err(unavailable)?;
            let latest_digest: String = latest.try_get("policy_digest").map_err(unavailable)?;
            let current_revision: i64 = current.try_get("revision").map_err(unavailable)?;
            let current_digest: String = current.try_get("policy_digest").map_err(unavailable)?;
            if latest_revision != current_revision || latest_digest != current_digest {
                return Err(corrupt("current policy is not the latest immutable revision"));
            }
        }
        _ => return Err(corrupt("current policy pointer is inconsistent")),
    }
    Ok(())
}

async fn verify_revision_tx(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    revision_value: Revision,
    expected_policy: Digest32,
    expected_source: Digest32,
    expected_rules: &[PolicyRuleV1],
) -> Result<(), PolicyError> {
    let row = sqlx::query(
        "SELECT policy_digest,source_digest,rule_count
         FROM auth_policy_revisions WHERE revision=?",
    )
    .bind(to_i64(revision_value.get(), "policy revision")?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .ok_or_else(|| corrupt("current revision row is missing"))?;
    let policy = parse_digest(
        &row.try_get::<String, _>("policy_digest").map_err(unavailable)?,
        "policy",
    )?;
    let source = parse_digest(
        &row.try_get::<String, _>("source_digest").map_err(unavailable)?,
        "policy source",
    )?;
    let count: i64 = row.try_get("rule_count").map_err(unavailable)?;
    if policy != expected_policy
        || source != expected_source
        || count != i64::try_from(expected_rules.len()).map_err(invalid)?
    {
        return Err(corrupt("idempotent policy revision metadata differs"));
    }
    let rows = sqlx::query(
        "SELECT principal_id,action_id,resource_id,allowed
         FROM auth_policy_rules WHERE revision=?
         ORDER BY principal_id,action_id,resource_id",
    )
    .bind(to_i64(revision_value.get(), "policy revision")?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if rows.len() != expected_rules.len() {
        return Err(corrupt("idempotent policy revision rules differ"));
    }
    for (row, expected) in rows.iter().zip(expected_rules) {
        let principal: String = row.try_get("principal_id").map_err(unavailable)?;
        let action: String = row.try_get("action_id").map_err(unavailable)?;
        let resource: String = row.try_get("resource_id").map_err(unavailable)?;
        let allowed: i64 = row.try_get("allowed").map_err(unavailable)?;
        if principal != expected.principal_id.as_str()
            || action != expected.action_id.as_str()
            || resource != expected.resource_id.as_str()
            || allowed != i64::from(expected.allowed)
        {
            return Err(corrupt("idempotent policy revision rule differs"));
        }
    }
    Ok(())
}

fn parse_digest(value: &str, label: &str) -> Result<Digest32, PolicyError> {
    let digest = value
        .parse::<Digest32>()
        .map_err(|error| corrupt(&format!("invalid {label} digest: {error}")))?;
    if digest.is_zero() {
        return Err(corrupt(&format!("zero {label} digest")));
    }
    Ok(digest)
}

fn revision(value: i64) -> Result<Revision, PolicyError> {
    let value = u64::try_from(value).map_err(|_| corrupt("negative policy revision"))?;
    Revision::new(value).map_err(invalid)
}

fn to_i64(value: u64, label: &str) -> Result<i64, PolicyError> {
    i64::try_from(value)
        .map_err(|_| PolicyError::Invalid(format!("{label} exceeds SQLite integer range")))
}

fn unavailable(error: impl fmt::Display) -> PolicyError {
    PolicyError::Unavailable(error.to_string())
}

fn invalid(error: impl fmt::Display) -> PolicyError {
    PolicyError::Invalid(error.to_string())
}

fn corrupt(message: &str) -> PolicyError {
    PolicyError::Corrupt(message.to_string())
}

#[cfg(test)]
#[path = "policy_tests.rs"]
mod tests;
