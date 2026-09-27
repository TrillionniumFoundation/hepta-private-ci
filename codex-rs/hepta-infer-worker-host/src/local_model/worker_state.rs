impl<D, O, C> DurableLocalWorker<D, O, C>
where
    D: LocalModelDriver,
    O: TrustedResourceObserver,
    C: TrustedClock,
{
    fn loaded_model(
        &self,
        model_id: &str,
        grant: &VerifiedResourceGrant,
    ) -> Result<LoadedModel, Error> {
        let models = self.models.lock().map_err(|_| Error::LockPoisoned)?;
        let model = models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if model.state != LoadedModelState::Ready
            || model.handle.model_id != grant.claims.model_id
            || model.handle.model_digest != grant.claims.model_digest
            || model.handle.weights_digest != grant.claims.weights_digest
            || model.handle.runtime_digest != grant.claims.runtime_digest
            || model.handle.device_id != grant.claims.device_id
            || model.handle.device_digest != grant.claims.device_digest
        {
            return Err(Error::InvalidManifest("loaded tuple mismatch"));
        }
        Ok(model.clone())
    }

    fn mark_active(
        &self,
        model_id: &str,
        operation_id: &str,
    ) -> Result<(), Error> {
        let mut models = self.models.lock().map_err(|_| Error::LockPoisoned)?;
        let model = models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if model.state != LoadedModelState::Ready {
            return Err(Error::ModelBusy);
        }
        model.active_operations.insert(operation_id.to_string());
        Ok(())
    }

    fn finish_active(
        &self,
        model_id: &str,
        operation_id: &str,
    ) -> Result<(), Error> {
        let mut models = self.models.lock().map_err(|_| Error::LockPoisoned)?;
        let model = models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        model.active_operations.remove(operation_id);
        Ok(())
    }
}
