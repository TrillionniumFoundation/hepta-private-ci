use std::time::Duration;
use std::time::Instant;

/// Maximum automatic restart attempts before an operator-visible stop/degraded state.
///
/// The runtime.supervisor dossier caps restart attempts at three per recovery window.
pub(crate) const RESTART_ATTEMPT_BUDGET: u32 = 3;
pub(crate) const RESTART_RECOVERY_WINDOW: Duration = Duration::from_secs(300);
pub(crate) const RESTART_BACKOFF_MIN: Duration = Duration::from_millis(250);
pub(crate) const RESTART_BACKOFF_MAX: Duration = Duration::from_secs(30);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RestartSchedule {
    Retry { attempt: u32, retry_at: Instant },
    Exhausted { attempts: u32 },
}

pub(crate) fn schedule_restart(
    attempt: &mut u32,
    window_started_at: &mut Option<Instant>,
    now: Instant,
) -> RestartSchedule {
    let window_expired = window_started_at
        .and_then(|started| now.checked_duration_since(started))
        .is_some_and(|elapsed| elapsed >= RESTART_RECOVERY_WINDOW);
    if window_started_at.is_none() || window_expired {
        *window_started_at = Some(now);
        *attempt = 0;
    }

    if *attempt >= RESTART_ATTEMPT_BUDGET {
        return RestartSchedule::Exhausted { attempts: *attempt };
    }

    *attempt = attempt.saturating_add(1);
    let shift = attempt.saturating_sub(1).min(7);
    let delay = RESTART_BACKOFF_MIN
        .checked_mul(1_u32 << shift)
        .unwrap_or(RESTART_BACKOFF_MAX)
        .min(RESTART_BACKOFF_MAX);
    let retry_at = now.checked_add(delay).unwrap_or(now);
    RestartSchedule::Retry {
        attempt: *attempt,
        retry_at,
    }
}

pub(crate) fn clear_restart_budget(attempt: &mut u32, window_started_at: &mut Option<Instant>) {
    *attempt = 0;
    *window_started_at = None;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn restart_schedule_is_exponential_and_stops_after_three_attempts() {
        let now = Instant::now();
        let mut attempts = 0;
        let mut window = None;

        let first = schedule_restart(&mut attempts, &mut window, now);
        let second = schedule_restart(&mut attempts, &mut window, now);
        let third = schedule_restart(&mut attempts, &mut window, now);
        let exhausted = schedule_restart(&mut attempts, &mut window, now);

        assert_eq!(
            first,
            RestartSchedule::Retry {
                attempt: 1,
                retry_at: now + RESTART_BACKOFF_MIN,
            }
        );
        assert_eq!(
            second,
            RestartSchedule::Retry {
                attempt: 2,
                retry_at: now + RESTART_BACKOFF_MIN * 2,
            }
        );
        assert_eq!(
            third,
            RestartSchedule::Retry {
                attempt: 3,
                retry_at: now + RESTART_BACKOFF_MIN * 4,
            }
        );
        assert_eq!(
            exhausted,
            RestartSchedule::Exhausted {
                attempts: RESTART_ATTEMPT_BUDGET,
            }
        );
    }

    #[test]
    fn restart_schedule_resets_after_recovery_window() {
        let now = Instant::now();
        let mut attempts = RESTART_ATTEMPT_BUDGET;
        let mut window = Some(now);
        let after_window = now + RESTART_RECOVERY_WINDOW;

        assert_eq!(
            schedule_restart(&mut attempts, &mut window, after_window),
            RestartSchedule::Retry {
                attempt: 1,
                retry_at: after_window + RESTART_BACKOFF_MIN,
            }
        );
    }
}
