use std::time::Duration;

use crossterm::event::KeyCode;
use crossterm::event::KeyEvent;
use crossterm::event::KeyModifiers;
use pretty_assertions::assert_eq;

use super::StartupDraftPump;
use super::handle_startup_draft_key;
use super::startup_test_pump;
use crate::input_clock::InputClock;
use crate::tui::TuiEvent;

pub(super) fn freeze_input_clock(pump: &mut StartupDraftPump) -> InputClock {
    let clock = InputClock::frozen();
    pump.input_clock = clock.clone();
    pump.bottom_pane.set_input_clock_for_test(clock.clone());
    clock
}

#[test]
fn startup_input_clock_preserves_the_held_character_flush_boundary() {
    let mut pump = startup_test_pump(std::iter::empty());
    let clock = freeze_input_clock(&mut pump);
    handle_startup_draft_key(
        &mut pump.bottom_pane,
        KeyEvent::new(KeyCode::Char('a'), KeyModifiers::NONE),
    )
    .expect("hold the first input character");

    clock.advance(Duration::from_millis(/*millis*/ 8));
    assert!(!pump.bottom_pane.flush_paste_burst_if_due());
    assert_eq!(pump.bottom_pane.composer_text(), "");
    clock.advance(Duration::from_millis(/*millis*/ 1));
    assert!(pump.bottom_pane.flush_paste_burst_if_due());
    assert_eq!(pump.bottom_pane.composer_text(), "a");
    assert!(pump.app_event_rx.try_recv().is_err());
}

#[test]
fn startup_input_clock_preserves_the_pending_newline_boundary() {
    for (elapsed_ms, expected) in [(120, "ab\nx"), (121, "abx")] {
        let mut pump = startup_test_pump(std::iter::empty());
        let clock = freeze_input_clock(&mut pump);
        let mut tui = crate::tui::test_support::make_test_tui().expect("create test terminal");
        for code in [KeyCode::Char('a'), KeyCode::Char('b'), KeyCode::Enter] {
            pump.handle_event(
                &mut tui,
                TuiEvent::Key(KeyEvent::new(code, KeyModifiers::NONE)),
            )
            .expect("stage the paste newline with real input handling");
        }
        assert_eq!(
            pump.pending_paste_newline
                .as_ref()
                .map(|(_, newlines)| newlines.as_str()),
            Some("\n")
        );

        clock.advance(Duration::from_millis(elapsed_ms));
        pump.handle_event(
            &mut tui,
            TuiEvent::Key(KeyEvent::new(KeyCode::Char('x'), KeyModifiers::NONE)),
        )
        .expect("resolve the original newline deadline");
        pump.bottom_pane.flush_composer_paste_burst();

        assert_eq!(pump.bottom_pane.composer_text(), expected);
        assert!(pump.pending_paste_newline.is_none());
        assert!(pump.app_event_rx.try_recv().is_err());
    }
}
