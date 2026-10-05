//! Shared process-local row-window bookkeeping, never durable effect authority.

use super::*;

#[derive(Clone, Copy)]
pub(super) enum RecoveryScanTable {
    DispatchOutcomes,
    Occurrences,
}

impl RecoveryScanTable {
    pub(super) fn endpoint_queries(self) -> (&'static str, &'static str) {
        match self {
            RecoveryScanTable::DispatchOutcomes => (
                "SELECT rowid FROM automation_dispatch_outcomes ORDER BY rowid LIMIT 1",
                "SELECT rowid FROM automation_dispatch_outcomes ORDER BY rowid DESC LIMIT 1",
            ),
            RecoveryScanTable::Occurrences => (
                "SELECT rowid FROM automation_occurrence_lifecycle ORDER BY rowid LIMIT 1",
                "SELECT rowid FROM automation_occurrence_lifecycle ORDER BY rowid DESC LIMIT 1",
            ),
        }
    }
}

#[derive(Debug)]
pub(super) struct RecoveryScanCursor {
    store_identity: Arc<()>,
    pub(super) after: i64,
    through: Option<i64>,
}

impl RecoveryScanCursor {
    pub(super) fn for_store(store: &AutomationStore) -> Self {
        Self {
            store_identity: Arc::clone(&store.uncertainty_scan_identity),
            after: 0,
            through: None,
        }
    }

    pub(super) fn verify_store(&self, store: &AutomationStore) -> Result<(), AutomationError> {
        if Arc::ptr_eq(&self.store_identity, &store.uncertainty_scan_identity) {
            Ok(())
        } else {
            Err(AutomationError::AccessDenied)
        }
    }

    pub(super) async fn high_water(
        &self,
        tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
        table: RecoveryScanTable,
    ) -> Result<Option<i64>, AutomationError> {
        if let Some(through) = self.through {
            return Ok(Some(through));
        }
        let (first_query, last_query) = table.endpoint_queries();
        let first = sqlx::query_scalar::<_, i64>(first_query)
            .fetch_optional(&mut **tx)
            .await
            .map_err(unavailable)?;
        if first.is_some_and(|rowid| rowid <= 0) {
            return Err(AutomationError::Corrupt);
        }
        sqlx::query_scalar::<_, i64>(last_query)
            .fetch_optional(&mut **tx)
            .await
            .map_err(unavailable)
    }

    pub(super) fn reset(&mut self) {
        self.after = 0;
        self.through = None;
    }

    // Call only after the read snapshot has committed successfully.
    pub(super) fn advance(&mut self, last_scanned: i64, through: i64) {
        if last_scanned == through {
            self.reset();
        } else {
            self.after = last_scanned;
            self.through = Some(through);
        }
    }
}
