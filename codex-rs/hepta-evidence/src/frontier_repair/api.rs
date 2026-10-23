impl HeptaEvidenceStore {
    /// Revalidate the complete repair schema, canonical operation rows and
    /// immutable event chains. A product repair publisher must call this before
    /// it attaches any external repair capability.
    pub async fn verify_frontier_repair_ledger(&self) -> Result<(), EvidenceError> {
        verify_frontier_repair_storage(&self.pool).await
    }
}
