use super::*;
use pretty_assertions::assert_eq;

#[test]
fn blocking_and_higher_priority_interference_are_included() {
    let tasks = [
        FixedPriorityTaskV1 {
            period_ns: 1_000,
            deadline_ns: 1_000,
            execution_ns: 200,
            blocking_ns: 100,
        },
        FixedPriorityTaskV1 {
            period_ns: 10_000,
            deadline_ns: 10_000,
            execution_ns: 2_000,
            blocking_ns: 100,
        },
    ];
    assert_eq!(fixed_priority_response_times(&tasks), Ok(vec![300, 2_700]));
    let tasks = [
        tasks[0],
        FixedPriorityTaskV1 {
            deadline_ns: 2_500,
            ..tasks[1]
        },
    ];
    assert_eq!(
        fixed_priority_response_times(&tasks),
        Err(TimingError::DeadlineMiss {
            task: 1,
            response_ns: 2_700
        })
    );
}

#[test]
fn overflow_sized_execution_is_reported_as_a_deadline_miss() {
    let tasks = [FixedPriorityTaskV1 {
        period_ns: u64::MAX,
        deadline_ns: u64::MAX,
        execution_ns: u64::MAX,
        blocking_ns: u64::MAX,
    }];
    assert_eq!(
        fixed_priority_response_times(&tasks),
        Err(TimingError::DeadlineMiss {
            task: 0,
            response_ns: u128::from(u64::MAX) * 2
        })
    );
}
