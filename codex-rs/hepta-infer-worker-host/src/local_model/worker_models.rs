impl<D, O, C> DurableLocalWorker<D, O, C>
where
    D: LocalModelDriver,
    O: TrustedResourceObserver,
    C: TrustedClock,
{
    pub async fn load_model(
        &self,
        grant: &VerifiedResourceGrant,
        manifest: ModelManifestEvidence,
    ) -> Result<AttestedModelHandle, Error> {
        let now_ms = self.clock.now_ms()?;
        grant.validate_live(now_ms, &self.worker_id, self.generation)?;
        let manifest = grant.verify_manifest(manifest)?;
        {
            let models = self.models.lock().map_err(|_| Error::LockPoisoned)?;
            if models.contains_key(&manifest.manifest.model_id) {
                return Err(Error::ModelAlreadyLoaded);
            }
        }
        let reservation = self.resources.reserve_model(
            &manifest.manifest.model_id,
            manifest.manifest.declared_weight_bytes,
            grant.claims.maximum_aggregate_memory_bytes,
        )?;
        let evidence = self.driver.load(&manifest, grant).await?;
        let provisional = attest_driver_handle(&manifest, grant, evidence)?;
        let observed = match self
            .observer
            .observe(provisional.handle_id(), None)
            .await
        {
            Ok(observed) => observed,
            Err(error) => {
                self.retain_repair_required(reservation, manifest, provisional)?;
                return Err(error.into());
            }
        };
        let handle = match attest_host_load(
            &provisional,
            &manifest,
            grant,
            self.generation,
            &observed,
        ) {
            Ok(handle) => handle,
            Err(error) => {
                self.retain_repair_required(reservation, manifest, provisional)?;
                return Err(error);
            }
        };
        if let Err(error) = reservation.commit(
            handle.handle_id.clone(),
            handle.observed_weight_bytes,
        ) {
            let _ = self.driver.unload(&handle).await;
            return Err(error);
        }
        self.models
            .lock()
            .map_err(|_| Error::LockPoisoned)?
            .insert(
                handle.model_id.clone(),
                LoadedModel {
                    manifest,
                    handle: handle.clone(),
                    state: LoadedModelState::Ready,
                    active_operations: BTreeSet::new(),
                },
            );
        Ok(handle)
    }

    pub async fn unload_model(&self, model_id: &str) -> Result<(), Error> {
        let handle = {
            let mut models = self.models.lock().map_err(|_| Error::LockPoisoned)?;
            let model = models
                .get_mut(model_id)
                .ok_or(Error::ModelNotLoaded)?;
            if model.state == LoadedModelState::RepairRequired {
                return Err(Error::RepairRequired);
            }
            if model.state != LoadedModelState::Ready
                || !model.active_operations.is_empty()
            {
                return Err(Error::ModelBusy);
            }
            model.state = LoadedModelState::Unloading;
            model.handle.clone()
        };
        self.resources.begin_unload(model_id)?;
        let unloaded = self.driver.unload(&handle).await;
        let success = if let Ok(unloaded) = unloaded {
            if unloaded.terminal_observed
                && unloaded.released_memory_bytes >= handle.observed_weight_bytes
            {
                self.observer
                    .observe(handle.handle_id(), None)
                    .await
                    .is_ok_and(|host| !host.present)
            } else {
                false
            }
        } else {
            false
        };
        if !success {
            self.mark_model_repair(model_id)?;
            return Err(Error::RepairRequired);
        }
        self.resources
            .complete_unload(model_id, handle.handle_id())?;
        self.models
            .lock()
            .map_err(|_| Error::LockPoisoned)?
            .remove(model_id);
        Ok(())
    }

    fn mark_model_repair(&self, model_id: &str) -> Result<(), Error> {
        self.resources.mark_repair_required(model_id)?;
        if let Some(model) = self
            .models
            .lock()
            .map_err(|_| Error::LockPoisoned)?
            .get_mut(model_id)
        {
            model.state = LoadedModelState::RepairRequired;
        }
        Ok(())
    }

    fn retain_repair_required(
        &self,
        reservation: super::ModelReservation,
        manifest: VerifiedModelManifest,
        handle: AttestedModelHandle,
    ) -> Result<(), Error> {
        reservation.commit(
            handle.handle_id.clone(),
            manifest.manifest.declared_weight_bytes,
        )?;
        self.resources
            .mark_repair_required(&manifest.manifest.model_id)?;
        self.models
            .lock()
            .map_err(|_| Error::LockPoisoned)?
            .insert(
                manifest.manifest.model_id.clone(),
                LoadedModel {
                    manifest,
                    handle,
                    state: LoadedModelState::RepairRequired,
                    active_operations: BTreeSet::new(),
                },
            );
        Ok(())
    }
}
