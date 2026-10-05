//! The paired product owner samples its own clock at each effect boundary.
//! A public caller cannot provide a historical timestamp or a replacement clock.
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;

use crate::AuthenticatedPairedRegistrationV1;
use crate::PairedSupervisedErrorV1;

pub(crate) struct PairedHostClockV1 {
    last: Option<u64>,
    #[cfg(test)]
    fixture_times: Option<std::collections::VecDeque<u64>>,
}

impl PairedHostClockV1 {
    pub(crate) fn system() -> Self {
        Self {
            last: None,
            #[cfg(test)]
            fixture_times: None,
        }
    }

    #[cfg(test)]
    pub(crate) fn fixture(times: &[u64]) -> Self {
        assert!(!times.is_empty());
        Self {
            last: None,
            fixture_times: Some(times.iter().copied().collect()),
        }
    }

    fn now(&mut self) -> Result<u64, PairedSupervisedErrorV1> {
        #[cfg(test)]
        if let Some(times) = self.fixture_times.as_mut() {
            return Ok(if times.len() > 1 {
                times.pop_front().unwrap()
            } else {
                *times.front().unwrap()
            });
        }
        let elapsed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| PairedSupervisedErrorV1::Binding("paired actual host clock"))?;
        u64::try_from(elapsed.as_millis()).map_err(|_| PairedSupervisedErrorV1::Arithmetic)
    }

    pub(crate) fn sample_registered(
        &mut self,
        trust: &ActivatedLearningTrustV1,
        registration: &AuthenticatedPairedRegistrationV1,
    ) -> Result<u64, PairedSupervisedErrorV1> {
        let now = self.now()?;
        if self.last.is_some_and(|last| now < last) || !trust.is_current_at(now) {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired actual host clock or root distribution not current",
            ));
        }
        self.last = Some(now);
        registration.verify_current(trust.verifier(), now)?;
        Ok(now)
    }
}
