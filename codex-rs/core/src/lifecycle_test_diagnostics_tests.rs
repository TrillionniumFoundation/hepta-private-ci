use super::*;
use pretty_assertions::assert_eq;

#[test]
fn subscription_is_exact_and_retained_until_the_last_owner_drops() {
    let tracked = ThreadId::new();
    let unrelated = ThreadId::new();
    let mut output = Vec::new();
    record_to(tracked, format_args!("before"), &mut output);
    let first = subscribe(tracked);
    let second = subscribe(tracked);
    record_to(unrelated, format_args!("unrelated"), &mut output);
    record_to(tracked, format_args!("first"), &mut output);
    drop(first);
    record_to(tracked, format_args!("second"), &mut output);
    drop(second);
    record_to(tracked, format_args!("after"), &mut output);
    let output = String::from_utf8_lossy(&output);
    let lines = output.lines().collect::<Vec<_>>();
    assert_eq!(lines.len(), 2);
    assert!(lines[0].contains(&format!("thread={tracked} seq=1 ")));
    assert!(lines[0].ends_with(" first"));
    assert!(lines[1].contains(&format!("thread={tracked} seq=2 ")));
    assert!(lines[1].ends_with(" second"));
}

#[test]
fn concurrent_records_share_one_bounded_budget() {
    let tracked = ThreadId::new();
    let _subscription = subscribe(tracked);
    let output = Mutex::new(Vec::new());
    std::thread::scope(|scope| {
        for _ in 0..8 {
            let output = &output;
            scope.spawn(move || {
                for _ in 0..MAX_RECORDS_PER_THREAD {
                    let mut record = Vec::new();
                    record_to(tracked, format_args!("concurrent"), &mut record);
                    output
                        .lock()
                        .unwrap_or_else(PoisonError::into_inner)
                        .extend(record);
                }
            });
        }
    });
    let output = output.into_inner().unwrap_or_else(PoisonError::into_inner);
    let output = String::from_utf8_lossy(&output);
    assert_eq!(output.lines().count(), MAX_RECORDS_PER_THREAD);
    let mut sequences = output
        .lines()
        .filter_map(|line| line.split_once(" seq="))
        .filter_map(|(_, tail)| tail.split_once(' '))
        .map(|(sequence, _)| sequence.to_string())
        .collect::<Vec<_>>();
    sequences.sort();
    sequences.dedup();
    assert_eq!(sequences.len(), MAX_RECORDS_PER_THREAD);
}
