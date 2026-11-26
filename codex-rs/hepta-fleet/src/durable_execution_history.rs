//! Historical holds are never deleted, including stopped executions. Absence
//! of an active PID is weaker than absence of every pre-spawn admission.
use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::durable_rows::validate_identity;
use crate::durable_schema::sqlx_error;

impl DurableFleetStore {
    /// Query the complete indexed admission history, including stopped holds.
    pub async fn principal_has_execution_history(
        &self,
        principal: &str,
    ) -> Result<bool, DurableFleetError> {
        validate_identity(principal, "execution principal")?;
        let invalid: bool = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM fleet_execution_holds INDEXED BY fleet_execution_invalid_principal_idx WHERE json_type(context_json, '$.principal_id') IS NOT 'text')")
            .fetch_one(&self.pool).await.map_err(sqlx_error)?;
        if invalid {
            return Err(DurableFleetError::Corrupt(
                "execution history principal is missing or malformed".into(),
            ));
        }
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM fleet_execution_holds INDEXED BY fleet_execution_history_principal_idx WHERE json_extract(context_json, '$.principal_id') = ?)")
            .bind(principal)
            .fetch_one(&self.pool)
            .await
            .map_err(sqlx_error)
    }
}
