use super::*;
use pretty_assertions::assert_eq;
use tokio::sync::mpsc::unbounded_channel;

fn status_with_old_timer() -> StatusIndicatorWidget {
    let (tx, _rx) = unbounded_channel();
    let mut status = StatusIndicatorWidget::new(
        AppEventSender::new(tx),
        FrameRequester::test_dummy(),
        /*animations_enabled*/ true,
    );
    status.last_resume_at = Instant::now()
        .checked_sub(Duration::from_secs(/*secs*/ 3))
        .unwrap_or_else(|| panic!("test clock must support a three-second offset"));
    status
}

fn rendered_line(status: &StatusIndicatorWidget) -> String {
    let area = Rect::new(
        /*x*/ 0, /*y*/ 0, /*width*/ 80, /*height*/ 1,
    );
    let mut buffer = Buffer::empty(area);
    status.render(area, &mut buffer);
    buffer
        .content()
        .iter()
        .map(ratatui::buffer::Cell::symbol)
        .collect::<String>()
        .trim_end()
        .to_string()
}

#[test]
fn sampled_status_frame_preserves_elapsed_and_spinner_boundaries() {
    let truecolor = supports_color::on_cached(supports_color::Stream::Stdout)
        .is_some_and(|level| level.has_16m);
    for (millis, elapsed, blinking_indicator) in [
        (0, "0s", "•"),
        (600, "0s", "◦"),
        (1200, "1s", "•"),
        (3000, "3s", "◦"),
    ] {
        let status = status_with_old_timer();
        *status
            .next_snapshot_render_at
            .lock()
            .unwrap_or_else(|error| panic!("snapshot render clock poisoned: {error}")) =
            Some(status.last_resume_at + Duration::from_millis(millis));
        let indicator = if truecolor { "•" } else { blinking_indicator };
        assert_eq!(
            rendered_line(&status),
            format!("{indicator} Working ({elapsed} • esc to interrupt)"),
        );
    }
}

#[test]
fn sampled_status_frame_is_local_consumed_once_and_then_uses_live_time() {
    let sampled = status_with_old_timer();
    let other = status_with_old_timer();
    sampled.freeze_next_render_at_start();

    // An empty render does not consume the requested visible frame.
    let empty = Rect::default();
    sampled.render(empty, &mut Buffer::empty(empty));
    let other_line = rendered_line(&other);
    assert_eq!(rendered_line(&sampled), "• Working (0s • esc to interrupt)");
    let following_line = rendered_line(&sampled);

    // Neither the independent instance nor the subsequent render is held at zero.
    // The real timers started at least three seconds ago; no sleep is required.
    for live_line in [other_line, following_line] {
        assert!(live_line.ends_with(" • esc to interrupt)"));
        assert!(live_line.contains("Working ("));
        assert!(!live_line.contains("Working (0s "));
    }
}
