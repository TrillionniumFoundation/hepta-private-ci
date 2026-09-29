//! Host-selected bounded writer policy. Defaults are engineering settings, not
//! a claim that a target host meets any throughput or latency objective.

use std::time::Duration;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeWriterLimits {
    pub ordinary_queue_capacity: usize,
    pub terminal_queue_capacity: usize,
    pub reply_timeout: Duration,
    pub shutdown_timeout: Duration,
}

impl Default for NativeWriterLimits {
    fn default() -> Self {
        Self {
            ordinary_queue_capacity: crate::actor_mailbox::DEFAULT_QUEUE_CAPACITY,
            terminal_queue_capacity: crate::actor_mailbox::DEFAULT_TERMINAL_CAPACITY,
            reply_timeout: Duration::from_secs(30),
            shutdown_timeout: Duration::from_secs(30),
        }
    }
}

impl NativeWriterLimits {
    pub(crate) fn validate(self) -> bool {
        let maximum = Duration::from_secs(3600);
        !self.reply_timeout.is_zero()
            && self.reply_timeout <= maximum
            && !self.shutdown_timeout.is_zero()
            && self.shutdown_timeout <= maximum
    }
}
