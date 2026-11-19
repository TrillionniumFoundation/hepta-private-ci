//! Candidate pure Rust policy for pointer sequences rejected during IME preedit.
//!
//! The application adapter handles focus and routes mixed-touch packets while
//! the platform retains responsibility for capture cleanup and IME completion.
//! No backend action, authority, or successful IME commit is inferred here.
use std::collections::BTreeSet;

const MAX_BLOCKED_POINTERS: usize = 32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub(crate) enum PointerId {
    Mouse(u32),
    Touch(u64),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Preedit {
    Active,
    Inactive,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Position {
    FocusedField,
    OutsideFocusedField,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Capture {
    FocusedField,
    OtherOrNone,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Route {
    Forward,
    SuppressUiDispatch,
}

/// Bounded gesture fencing, deliberately not scoped to room/account state.
/// An epoch switch must not make a previously rejected release actionable.
#[derive(Default)]
pub(crate) struct PointerGate {
    blocked: BTreeSet<PointerId>,
    overflowed: bool,
}

impl PointerGate {
    pub(crate) fn start(&mut self, id: PointerId, preedit: Preedit, position: Position) -> Route {
        if self.overflowed || self.blocked.contains(&id) {
            return Route::SuppressUiDispatch;
        }
        if preedit == Preedit::Inactive || position == Position::FocusedField {
            return Route::Forward;
        }
        if self.blocked.len() == MAX_BLOCKED_POINTERS {
            self.overflowed = true;
        } else {
            self.blocked.insert(id);
        }
        Route::SuppressUiDispatch
    }

    pub(crate) fn motion(&self, id: PointerId) -> Route {
        if self.overflowed || self.blocked.contains(&id) {
            Route::SuppressUiDispatch
        } else {
            Route::Forward
        }
    }

    pub(crate) fn finish(
        &mut self,
        id: PointerId,
        preedit: Preedit,
        position: Position,
        capture: Capture,
    ) -> Route {
        let blocked = self.blocked.remove(&id);
        if self.overflowed
            || blocked
            || (preedit == Preedit::Active
                && position == Position::OutsideFocusedField
                && capture != Capture::FocusedField)
        {
            Route::SuppressUiDispatch
        } else {
            Route::Forward
        }
    }

    pub(crate) fn is_overflowed(&self) -> bool {
        self.overflowed
    }

    /// Only after the platform has explicitly cancelled contacts and released
    /// captures. Never call for a room/account change, elapsed timeout or redraw.
    #[cfg(test)]
    pub(crate) fn platform_input_reset_completed(&mut self) {
        self.blocked.clear();
        self.overflowed = false;
    }
}

#[cfg(test)]
#[path = "ime_pointer_gate_tests.rs"]
mod tests;
