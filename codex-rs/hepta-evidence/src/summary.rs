use sqlx::Sqlite;
use sqlx::Transaction;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct GovernanceEvidenceSummary {
    pub decisions: u64,
    pub receipts: u64,
    pub pending_actions: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ProviderEvidenceSummary {
    pub intents: u64,
    pub receipts: u64,
    pub pending_attempts: u64,
    pub indeterminate_attempts: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct EvidenceSummary {
    pub governance: GovernanceEvidenceSummary,
    pub provider: ProviderEvidenceSummary,
}

impl HeptaEvidenceStore {
    /// Reads every supported evidence family from one SQLite read transaction.
    /// This is a diagnostic snapshot, not authority or an anti-rollback root.
    pub async fn summary(&self) -> Result<EvidenceSummary, EvidenceError> {
        let mut transaction = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let summary = EvidenceSummary {
            governance: GovernanceEvidenceSummary {
                decisions: count(
                    &mut transaction,
                    "SELECT COUNT(*) FROM governance_decisions",
                )
                .await?,
                receipts: count(&mut transaction, "SELECT COUNT(*) FROM governance_receipts")
                    .await?,
                pending_actions: count(
                    &mut transaction,
                    "SELECT COUNT(DISTINCT decisions.action_id)
                     FROM governance_decisions AS decisions
                     LEFT JOIN governance_receipts AS receipts
                       ON receipts.action_id = decisions.action_id
                     WHERE receipts.action_id IS NULL",
                )
                .await?,
            },
            provider: ProviderEvidenceSummary {
                intents: count(
                    &mut transaction,
                    "SELECT COUNT(*) FROM provider_invocation_intents",
                )
                .await?,
                receipts: count(
                    &mut transaction,
                    "SELECT COUNT(*) FROM provider_invocation_terminals",
                )
                .await?,
                pending_attempts: count(
                    &mut transaction,
                    "SELECT COUNT(*)
                     FROM provider_invocation_intents AS intents
                     LEFT JOIN provider_invocation_terminals AS terminals
                       ON terminals.attempt_id = intents.attempt_id
                     WHERE terminals.attempt_id IS NULL",
                )
                .await?,
                indeterminate_attempts: count(
                    &mut transaction,
                    "SELECT COUNT(*) FROM provider_invocation_terminals
                     WHERE terminal_kind = 'indeterminate'",
                )
                .await?,
            },
        };
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(summary)
    }
}

async fn count(
    transaction: &mut Transaction<'_, Sqlite>,
    query: &'static str,
) -> Result<u64, EvidenceError> {
    let count: i64 = sqlx::query_scalar(query)
        .fetch_one(&mut **transaction)
        .await
        .map_err(classify_sqlx_error)?;
    u64::try_from(count)
        .map_err(|_| EvidenceError::Corrupt("evidence count is negative".to_string()))
}
