//! Bounded debug-only refusal labels for the original retained-use read.
//!
//! Labels carry no owner identity, nonce, grant, payload, path or authority.
//! Locked callees only save fixed values in this thread's diagnostic scope.
//! Its caller declares the scope before acquiring the original state guard,
//! so stderr output happens after that guard has been released on return.
//! Release builds retain no diagnostic state and emit no output.

use super::FinalUseError;
use std::io::ErrorKind;

#[cfg(debug_assertions)]
use std::cell::Cell;
#[cfg(debug_assertions)]
use std::io::Write;
#[cfg(debug_assertions)]
use std::sync::atomic::AtomicUsize;
#[cfg(debug_assertions)]
use std::sync::atomic::Ordering;

#[cfg(debug_assertions)]
#[derive(Clone, Copy)]
struct Refusal {
    stage: &'static str,
    error: FinalUseError,
    io_kind: Option<ErrorKind>,
}

#[cfg(debug_assertions)]
#[derive(Clone, Copy)]
struct ActiveScope {
    operation: &'static str,
    first_refusal: Option<Refusal>,
}

#[cfg(debug_assertions)]
std::thread_local! {
    static CURRENT: Cell<Option<ActiveScope>> = const { Cell::new(None) };
}

#[cfg(debug_assertions)]
static EMITTED: AtomicUsize = AtomicUsize::new(0);

pub(super) struct RefusalScope {
    #[cfg(debug_assertions)]
    previous: Option<ActiveScope>,
    #[cfg(debug_assertions)]
    active: bool,
}

impl RefusalScope {
    pub(super) fn new(operation: &'static str) -> Self {
        #[cfg(debug_assertions)]
        {
            match CURRENT.try_with(|current| {
                current.replace(Some(ActiveScope {
                    operation,
                    first_refusal: None,
                }))
            }) {
                Ok(previous) => Self {
                    previous,
                    active: true,
                },
                Err(_) => Self {
                    previous: None,
                    active: false,
                },
            }
        }
        #[cfg(not(debug_assertions))]
        {
            let _ = operation;
            Self {}
        }
    }
}

pub(crate) fn record(stage: &'static str, error: FinalUseError, io_kind: Option<ErrorKind>) {
    #[cfg(debug_assertions)]
    {
        let _ = CURRENT.try_with(|current| {
            let Some(mut active) = current.get() else {
                return;
            };
            if active.first_refusal.is_none() {
                active.first_refusal = Some(Refusal {
                    stage,
                    error,
                    io_kind,
                });
                current.set(Some(active));
            }
        });
    }
    #[cfg(not(debug_assertions))]
    {
        let _ = (stage, error, io_kind);
    }
}

impl Drop for RefusalScope {
    fn drop(&mut self) {
        #[cfg(debug_assertions)]
        {
            if !self.active {
                return;
            }
            let Ok(active) = CURRENT.try_with(|current| {
                let active = current.replace(None);
                if let Some(mut previous) = self.previous {
                    if previous.first_refusal.is_none() {
                        previous.first_refusal = active.and_then(|scope| scope.first_refusal);
                    }
                    current.set(Some(previous));
                    None
                } else {
                    active
                }
            }) else {
                return;
            };
            let Some(active) = active else {
                return;
            };
            let Some(refusal) = active.first_refusal else {
                return;
            };
            let Ok(sequence) =
                EMITTED.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |count| {
                    (count < 64).then_some(count + 1)
                })
            else {
                return;
            };
            // Failure to write a diagnostic cannot replace the original error.
            let _ = writeln!(
                std::io::stderr().lock(),
                "ROOT_FINAL_USE_DIAGNOSTIC pid={} operation={} stage={} error={:?} io_kind={:?} sequence={} record_cap=64",
                std::process::id(),
                active.operation,
                refusal.stage,
                refusal.error,
                refusal.io_kind,
                sequence + 1,
            );
        }
    }
}
