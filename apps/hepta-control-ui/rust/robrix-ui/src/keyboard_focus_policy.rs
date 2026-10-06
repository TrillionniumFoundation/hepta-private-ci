//! Pure, deliberately narrow compact-chat focus policy. No framework or owner I/O.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Stop<A> {
    pub area: A,
    pub valid: bool,
}
#[derive(Clone, Copy)]
pub(crate) struct ChatStops<A> {
    pub conversations: A,
    pub theme: A,
    pub send: A,
    pub editor: A,
}
pub(crate) fn tab_target<A: Copy + Eq>(
    stops: &[Stop<A>],
    complete: bool,
    known: ChatStops<A>,
    focus: Option<A>,
    shift: bool,
    send_enabled: bool,
) -> Option<A> {
    if !complete || stops.len() > 32 {
        return None;
    }
    let Some(focus) = focus else {
        return (!shift)
            .then(|| stops.first())
            .flatten()
            .filter(|stop| stop.valid && stop.area == known.conversations)
            .map(|stop| stop.area);
    };
    if send_enabled {
        return None;
    }
    let index = stops
        .iter()
        .position(|stop| stop.valid && stop.area == focus)?;
    let triple = if shift && focus == known.editor {
        stops.get(index.checked_sub(2)?..=index)?
    } else if !shift && focus == known.theme {
        stops.get(index..=index.checked_add(2)?)?
    } else {
        return None;
    };
    if triple.iter().all(|stop| stop.valid)
        && triple[0].area == known.theme
        && triple[1].area == known.send
        && triple[2].area == known.editor
    {
        Some(if shift { known.theme } else { known.editor })
    } else {
        None
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct ReturnIdentity<A, U> {
    pub epoch: u64,
    pub room: u64,
    pub focus: A,
    pub opener: U,
    pub search: U,
}
#[derive(Clone, Copy)]
struct Pending<A, U, F> {
    identity: ReturnIdentity<A, U>,
    frame: Option<F>,
}
pub(crate) struct ReturnPolicy<A, U, F> {
    pending: Option<Pending<A, U, F>>,
}
impl<A, U, F> Default for ReturnPolicy<A, U, F> {
    fn default() -> Self {
        Self { pending: None }
    }
}
impl<A: Copy + Eq, U: Copy + Eq, F: Copy + Eq> ReturnPolicy<A, U, F> {
    pub fn cancel(&mut self) {
        self.pending = None;
    }
    pub fn begin(&mut self, identity: ReturnIdentity<A, U>) {
        self.pending = Some(Pending {
            identity,
            frame: None,
        });
    }
    pub fn observe(&mut self, identity: ReturnIdentity<A, U>, eligible: bool, newer_input: bool) {
        if !eligible || newer_input || self.pending.is_some_and(|p| p.identity != identity) {
            self.cancel();
        }
    }
    /// First draw only; never requeue after a failed target or an armed frame.
    pub fn needs_frame_after_draw(&mut self, target_valid: bool) -> bool {
        if self.pending.is_some_and(|p| p.frame.is_none()) {
            if target_valid {
                return true;
            }
            self.cancel();
        }
        false
    }
    pub fn arm(&mut self, frame: F) {
        if let Some(pending) = self.pending.as_mut()
            && pending.frame.is_none()
        {
            pending.frame = Some(frame);
        }
    }
    pub fn frame(&self) -> Option<F> {
        self.pending.and_then(|p| p.frame)
    }
    pub fn take_frame(&mut self, frame: F) -> bool {
        if self.frame() == Some(frame) {
            self.cancel();
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn known() -> ChatStops<u8> {
        ChatStops {
            conversations: 1,
            theme: 4,
            send: 5,
            editor: 6,
        }
    }
    fn stops() -> Vec<Stop<u8>> {
        (1..=6).map(|area| Stop { area, valid: true }).collect()
    }
    fn target(stops: &[Stop<u8>], focus: Option<u8>, shift: bool, enabled: bool) -> Option<u8> {
        tab_target(stops, true, known(), focus, shift, enabled)
    }
    fn identity() -> ReturnIdentity<u8, u8> {
        ReturnIdentity {
            epoch: 1,
            room: 2,
            focus: 8,
            opener: 9,
            search: 10,
        }
    }
    fn pending() -> ReturnPolicy<u8, u8, u8> {
        let mut p = ReturnPolicy::default();
        p.begin(identity());
        p
    }
    #[test]
    fn cold_forward_only_first_conversations() {
        assert_eq!(target(&stops(), None, false, false), Some(1));
        assert_eq!(target(&stops(), None, true, false), None);
    }
    #[test]
    fn exact_disabled_adjacency_both_directions() {
        assert_eq!(target(&stops(), Some(6), true, false), Some(4));
        assert_eq!(target(&stops(), Some(4), false, false), Some(6));
    }
    #[test]
    fn enabled_send_remains_reachable() {
        assert_eq!(target(&stops(), Some(6), true, true), None);
        assert_eq!(target(&stops(), Some(4), false, true), None);
    }
    #[test]
    fn inserted_enabled_control_is_not_skipped() {
        let mut s = stops();
        s.insert(
            4,
            Stop {
                area: 7,
                valid: true,
            },
        );
        assert_eq!(target(&s, Some(6), true, false), None);
        assert_eq!(target(&s, Some(4), false, false), None);
    }
    #[test]
    fn unrelated_focus_and_ordinary_boundaries_untouched() {
        for f in [1, 2, 3, 5, 7] {
            assert_eq!(target(&stops(), Some(f), true, false), None);
            assert_eq!(target(&stops(), Some(f), false, false), None);
        }
    }
    #[test]
    fn invalid_targets_and_focus_reject() {
        for i in [3, 4, 5] {
            let mut s = stops();
            s[i].valid = false;
            assert_eq!(target(&s, Some(6), true, false), None);
            assert_eq!(target(&s, Some(4), false, false), None);
        }
    }
    #[test]
    fn missing_root_empty_and_overflow_fail_closed() {
        assert_eq!(
            tab_target(&stops(), false, known(), None, false, false),
            None
        );
        assert_eq!(target(&[], None, false, false), None);
        let s = vec![
            Stop {
                area: 1,
                valid: true
            };
            33
        ];
        assert_eq!(target(&s, None, false, false), None);
    }
    #[test]
    fn changed_first_stop_does_not_force_conversations() {
        let mut s = stops();
        s[0].area = 7;
        assert_eq!(target(&s, None, false, false), None);
        s[0].area = 1;
        s[0].valid = false;
        assert_eq!(target(&s, None, false, false), None);
    }
    #[test]
    fn one_draw_one_frame_and_take_once() {
        let mut p = pending();
        assert!(p.needs_frame_after_draw(true));
        p.arm(3);
        assert!(!p.needs_frame_after_draw(true));
        p.arm(4);
        assert_eq!(p.frame(), Some(3));
        assert!(!p.take_frame(4));
        assert!(p.take_frame(3));
        assert!(!p.take_frame(3));
    }
    #[test]
    fn invalid_first_draw_drops_no_retry() {
        let mut p = pending();
        assert!(!p.needs_frame_after_draw(false));
        assert!(!p.needs_frame_after_draw(true));
    }
    #[test]
    fn newer_input_cancels_before_restore() {
        let mut p = pending();
        p.arm(3);
        p.observe(identity(), true, true);
        assert!(!p.take_frame(3));
    }
    #[test]
    fn changed_room_epoch_focus_or_widget_cancels() {
        for field in 0..5 {
            let mut p = pending();
            p.arm(3);
            let mut id = identity();
            match field {
                0 => id.epoch += 1,
                1 => id.room += 1,
                2 => id.focus += 1,
                3 => id.opener += 1,
                _ => id.search += 1,
            };
            p.observe(id, true, false);
            assert!(!p.take_frame(3));
        }
    }
    #[test]
    fn scope_or_ime_owner_disqualification_cancels() {
        let mut p = pending();
        p.arm(3);
        p.observe(identity(), false, false);
        assert!(!p.take_frame(3));
    }
    #[test]
    fn repeated_open_escape_replaces_old_token() {
        let mut p = pending();
        p.arm(3);
        p.cancel();
        p.begin(identity());
        assert!(!p.take_frame(3));
        assert!(p.needs_frame_after_draw(true));
        p.arm(4);
        assert!(p.take_frame(4));
    }
    #[test]
    fn unchanged_observations_preserve_pending() {
        let mut p = pending();
        p.arm(3);
        p.observe(identity(), true, false);
        assert!(p.take_frame(3));
    }
}
