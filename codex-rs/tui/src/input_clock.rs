//! Keep input timing on the real clock, with an instance-owned clock for fixtures.

use std::time::Instant;

/// Supplies the same input time to startup lookahead and composer paste handling.
///
/// Production instances are zero-sized and always read `Instant::now()`. Tests
/// may clone one controlled instance across both layers without changing clocks
/// in other composers, tasks, or terminal rendering.
#[derive(Clone, Default)]
pub(crate) struct InputClock {
    #[cfg(test)]
    controlled: Option<std::sync::Arc<std::sync::Mutex<Instant>>>,
}

impl InputClock {
    pub(crate) fn now(&self) -> Instant {
        #[cfg(test)]
        if let Some(instant) = &self.controlled {
            return *instant.lock().expect("input fixture clock poisoned");
        }
        Instant::now()
    }

    #[cfg(test)]
    pub(crate) fn frozen() -> Self {
        Self {
            controlled: Some(std::sync::Arc::new(std::sync::Mutex::new(Instant::now()))),
        }
    }

    #[cfg(test)]
    pub(crate) fn advance(&self, duration: std::time::Duration) {
        let mut instant = self
            .controlled
            .as_ref()
            .expect("advance only a controlled input clock")
            .lock()
            .expect("input fixture clock poisoned");
        *instant += duration;
    }
}
