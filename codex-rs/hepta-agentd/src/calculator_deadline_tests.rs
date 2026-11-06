use super::*;
#[test]
fn total_budget_rejects_clock_regression_and_late_final_io() {
    let deadline = Deadline {
        started_ns: 10,
        end_ns: 20,
    };
    assert_eq!(deadline.remaining_at(19).unwrap(), Duration::from_nanos(1));
    for now in [9, 20, 21, u64::MAX] {
        assert_eq!(
            deadline.remaining_at(now).unwrap_err().kind(),
            io::ErrorKind::TimedOut
        );
    }
}
