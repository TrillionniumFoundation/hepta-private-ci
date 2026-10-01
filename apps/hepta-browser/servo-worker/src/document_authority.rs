//! Single-use document observations and navigation-specific completion evidence.
//!
//! This state is separate from Servo so its fail-closed rules can be exercised
//! without a renderer. The embedder supplies canonical URLs and document digests.

const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct PageObservation {
    pub(crate) page_generation: u64,
    pub(crate) document_digest: String,
    pub(crate) origin: String,
    url: String,
    navigation_epoch: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct NavigationAttempt {
    epoch: u64,
    target: String,
    source_url: String,
}

#[derive(Clone, Copy)]
pub(crate) enum LoadPhase {
    Started,
    InProgress,
    Complete,
}

struct PendingNavigation {
    attempt: NavigationAttempt,
    awaiting_request: bool,
    started: bool,
    completed: bool,
}

#[derive(Default)]
pub(crate) struct DocumentAuthority {
    page_generation: u64,
    pub(crate) navigation_epoch: u64,
    exhausted: bool,
    effect_started: bool,
    observation: Option<PageObservation>,
    pending_navigation: Option<PendingNavigation>,
}

impl DocumentAuthority {
    pub(crate) fn observe(
        &mut self,
        url: &str,
        origin: &str,
        digest: impl FnOnce(u64, u64) -> String,
    ) -> Result<PageObservation, String> {
        if self.exhausted || self.page_generation >= MAX_SAFE_INTEGER {
            return Err("document observation generation exhausted".to_string());
        }
        if self
            .pending_navigation
            .as_ref()
            .is_some_and(|pending| !pending.completed)
        {
            return Err("navigation completion has not been observed".to_string());
        }
        self.page_generation += 1;
        let observation = PageObservation {
            page_generation: self.page_generation,
            document_digest: digest(self.page_generation, self.navigation_epoch),
            origin: origin.to_string(),
            url: url.to_string(),
            navigation_epoch: self.navigation_epoch,
        };
        self.observation = Some(observation.clone());
        Ok(observation)
    }

    pub(crate) fn bootstrap_allowed(&self, url: &str) -> bool {
        !self.exhausted && !self.effect_started && self.page_generation == 0 && url == "about:blank"
    }

    pub(crate) fn validate_observation(
        &self,
        page_generation: u64,
        document_digest: &str,
        current_url: &str,
    ) -> Result<(), String> {
        if !self.exhausted
            && self.observation.as_ref().is_some_and(|observation| {
                observation.page_generation == page_generation
                    && observation.document_digest == document_digest
                    && observation.url == current_url
                    && observation.navigation_epoch == self.navigation_epoch
            })
        {
            Ok(())
        } else {
            Err("worker document observation is stale or mismatched".to_string())
        }
    }

    pub(crate) fn consume_observation(&mut self) {
        self.effect_started = true;
        self.observation = None;
    }

    pub(crate) fn begin_navigation(
        &mut self,
        target: &str,
        source_url: &str,
    ) -> Result<NavigationAttempt, String> {
        self.invalidate_navigation()?;
        let attempt = NavigationAttempt {
            epoch: self.navigation_epoch,
            target: target.to_string(),
            source_url: source_url.to_string(),
        };
        self.pending_navigation = Some(PendingNavigation {
            attempt: attempt.clone(),
            awaiting_request: true,
            started: false,
            completed: false,
        });
        Ok(attempt)
    }

    pub(crate) fn navigation_requested(&mut self, target: &str) -> Result<(), String> {
        self.observation = None;
        if let Some(pending) = self.pending_navigation.as_mut()
            && pending.awaiting_request
            && pending.attempt.target == target
        {
            pending.awaiting_request = false;
            return Ok(());
        }
        self.invalidate_navigation()
    }

    pub(crate) fn url_changed(&mut self, url: &str) {
        self.observation = None;
        if self
            .pending_navigation
            .as_ref()
            .is_none_or(|pending| pending.attempt.target != url)
        {
            let _ = self.invalidate_navigation();
        }
    }

    pub(crate) fn load_changed(&mut self, phase: LoadPhase, url: &str) {
        self.observation = None;
        match phase {
            LoadPhase::Started => {
                if let Some(pending) = self.pending_navigation.as_mut()
                    && !pending.started
                {
                    pending.started = true;
                } else {
                    let _ = self.invalidate_navigation();
                }
            }
            LoadPhase::InProgress => {}
            LoadPhase::Complete => {
                if let Some(pending) = self.pending_navigation.as_mut()
                    && pending.started
                    && pending.attempt.target == url
                {
                    pending.completed = true;
                    pending.awaiting_request = false;
                }
            }
        }
    }

    pub(crate) fn navigation_complete(
        &self,
        attempt: &NavigationAttempt,
        url: &str,
        phase: LoadPhase,
    ) -> bool {
        !self.exhausted
            && matches!(phase, LoadPhase::Complete)
            && self.navigation_epoch == attempt.epoch
            && attempt.target == url
            // WebView completion callbacks expose no request identity. An
            // unchanged URL cannot distinguish a reload from an old callback.
            && attempt.target != attempt.source_url
            && self.pending_navigation.as_ref().is_some_and(|pending| {
                pending.attempt == *attempt && pending.started && pending.completed
            })
    }

    fn invalidate_navigation(&mut self) -> Result<(), String> {
        self.observation = None;
        self.pending_navigation = None;
        if self.exhausted || self.navigation_epoch >= MAX_SAFE_INTEGER {
            self.exhausted = true;
            return Err("navigation evidence generation exhausted".to_string());
        }
        self.navigation_epoch += 1;
        Ok(())
    }
}

#[cfg(test)]
#[path = "document_authority_tests.rs"]
mod tests;
