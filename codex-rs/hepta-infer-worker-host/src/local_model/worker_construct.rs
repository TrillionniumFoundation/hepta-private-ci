impl<D, O, C> DurableLocalWorker<D, O, C>
where
    D: LocalModelDriver,
    O: TrustedResourceObserver,
    C: TrustedClock,
{
    pub fn new(
        worker_id: String,
        generation: u64,
        driver: Arc<D>,
        observer: Arc<O>,
        clock: C,
        resources: ResourceManager,
    ) -> Result<Self, Error> {
        validate_identity(&worker_id, "worker")?;
        if generation == 0 || resources.snapshot()?.generation != generation {
            return Err(Error::InvalidGrant("worker generation"));
        }
        Ok(Self {
            worker_id,
            generation,
            driver,
            observer,
            clock,
            resources,
            models: Arc::new(Mutex::new(BTreeMap::new())),
        })
    }

    pub fn resources(&self) -> &ResourceManager {
        &self.resources
    }

}
