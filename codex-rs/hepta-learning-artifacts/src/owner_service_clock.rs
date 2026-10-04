use super::LearningArtifactOwnerServiceError;

/// Invocation-local nondecreasing samples from the already selected host clock.
/// This does not provision a clock or attest its trust. The request timestamp
/// remains the admission floor; durable identities never include new samples.
pub(super) struct PublicationClock<'a> {
    floor: u64,
    source: &'a mut dyn FnMut() -> Result<u64, LearningArtifactOwnerServiceError>,
}

impl<'a> PublicationClock<'a> {
    pub(super) fn new(
        floor: u64,
        source: &'a mut dyn FnMut() -> Result<u64, LearningArtifactOwnerServiceError>,
    ) -> Self {
        Self { floor, source }
    }

    pub(super) fn sample(&mut self) -> Result<u64, LearningArtifactOwnerServiceError> {
        let now = (self.source)()?;
        if now < self.floor {
            return Err(LearningArtifactOwnerServiceError::ClockRegression);
        }
        self.floor = now;
        Ok(now)
    }
}
