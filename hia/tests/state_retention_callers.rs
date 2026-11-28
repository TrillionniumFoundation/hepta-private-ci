use chrono::DateTime;
use chrono::Duration;
use chrono::Utc;
use std::cell::Cell;
use std::io::Write;

#[cfg(not(feature = "hia-native"))]
compile_error!("retention caller replay must execute the production native feature");

#[path = "../datetime_retention.rs"]
mod hia_datetime_retention;

thread_local! {
    static CLOCK: Cell<Option<([DateTime<Utc>; 2], usize)>> = const { Cell::new(None) };
}

fn read_clock() -> DateTime<Utc> {
    CLOCK.with(|clock| {
        let (times, reads) = clock.get().expect("caller clock was prepared");
        let now = times[reads];
        clock.set(Some((times, reads + 1)));
        now
    })
}

// Extracted from the actual immutable/current production sources. The only
// input substitution is the identical counting clock. The log caller's SQL
// invocation is observed as its exact cutoff argument; a skipped cleanup is None.
include!(env!("CODEX_STATE_RETENTION_METHODS"));

fn observe(times: [DateTime<Utc>; 2], call: impl FnOnce() -> Option<[i64; 2]>) -> [u64; 5] {
    CLOCK.with(|clock| clock.set(Some((times, 0))));
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(call));
    let reads = CLOCK.with(|clock| clock.get().unwrap().1) as u64;
    match result {
        Ok(Some([first, second])) => [1, first as u64, second as u64, reads, 0],
        Ok(None) => [0, 0, 0, reads, 0],
        Err(error) => {
            let (message, payload_kind) = if let Some(value) = error.downcast_ref::<&str>() {
                (*value, 1)
            } else if let Some(value) = error.downcast_ref::<String>() {
                (value.as_str(), 2)
            } else {
                panic!("unexpected retention panic payload type");
            };
            let code = match message {
                "TimeDelta::days out of bounds" => 2,
                "TimeDelta::hours out of bounds" => 3,
                "`DateTime - TimeDelta` overflowed" => 4,
                other => panic!("unexpected retention panic: {other}"),
            };
            [code, 0, 0, reads, payload_kind]
        }
    }
}

#[test]
fn complete_retention_corpora_preserve_cutoffs_panics_and_clock_order() {
    let input = std::fs::read(std::env::var_os("CODEX_STATE_RETENTION_CASES").unwrap()).unwrap();
    assert_eq!(input.len() % 40, 0);
    let output =
        std::fs::File::create_new(std::env::var_os("CODEX_STATE_RETENTION_TRACE").unwrap())
            .unwrap();
    let mut trace = std::io::BufWriter::new(output);
    let original_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let mut typed = [0_u64; 4];
    let mut statuses = [[0_u64; 5]; 4];
    let mut clock_reads = [0_u64; 4];
    let mut outside_typed_domain = 0_u64;
    let mut complete_two_clock_cases = 0_u64;
    for (index, bytes) in input.chunks_exact(40).enumerate() {
        let [operation, seconds, nanos, days, hours]: [u64; 5] = std::array::from_fn(|offset| {
            u64::from_le_bytes(bytes[offset * 8..(offset + 1) * 8].try_into().unwrap())
        });
        assert!(operation < 4, "unknown retention corpus operation");
        let timestamp = u32::try_from(nanos)
            .ok()
            .and_then(|nanos| DateTime::<Utc>::from_timestamp(seconds as i64, nanos));
        let mut observed = [0_u64; 11];
        if let Some(now) = timestamp {
            // Two distinguishable valid timestamps detect accidental clock
            // reuse and changes to the order of startup's two calculations.
            let second = if nanos >= 1_000_000_000 {
                DateTime::<Utc>::from_timestamp(seconds as i64, (2_999_999_999 - nanos) as u32)
            } else {
                DateTime::<Utc>::from_timestamp((seconds as i64) ^ 1, nanos as u32)
            }
            .expect("the second observed clock value is in the original typed domain");
            assert_ne!(now, second);
            let times = [now, second];
            let (days, hours) = (days as i64, hours as i64);
            let original = observe(times, || match operation {
                0 => original::logs(),
                1 => original::startup(days, hours),
                2 => original::prune(days),
                3 => original::phase2(days),
                _ => unreachable!(),
            });
            let native = observe(times, || match operation {
                0 => current::logs(),
                1 => current::startup(days, hours),
                2 => current::prune(days),
                3 => current::phase2(days),
                _ => unreachable!(),
            });
            if native != original {
                std::panic::set_hook(original_hook);
                panic!(
                    "retention input {index} op {operation} ({seconds}, {nanos}, {days}, {hours}): original {original:?}, native {native:?}"
                );
            }
            let operation = operation as usize;
            assert!((1..=2).contains(&original[3]));
            if operation != 1 {
                assert_eq!(original[3], 1);
            } else if original[0] == 1 {
                assert_eq!(original[3], 2);
                complete_two_clock_cases += 1;
            }
            typed[operation] += 1;
            statuses[operation][original[0] as usize] += 1;
            clock_reads[operation] += original[3];
            observed[0] = 1;
            observed[1..6].copy_from_slice(&original);
            observed[6..].copy_from_slice(&native);
        } else {
            outside_typed_domain += 1;
        }
        for word in observed {
            trace.write_all(&word.to_le_bytes()).unwrap();
        }
    }
    trace.flush().unwrap();
    std::panic::set_hook(original_hook);
    assert_eq!(
        typed.iter().sum::<u64>() + outside_typed_domain,
        (input.len() / 40) as u64
    );
    assert!(typed.iter().all(|count| *count > 0));
    assert!(statuses[0][0] > 0 && complete_two_clock_cases > 0);
    assert!(statuses[1][2] > 0 && statuses[1][3] > 0 && statuses[1][4] > 0);
    println!(
        "STATE_RETENTION_REPORT={{\"input_cases\":{},\"typed_cases\":{typed:?},\"statuses\":{statuses:?},\"clock_reads_per_implementation\":{clock_reads:?},\"outside_typed_domain\":{outside_typed_domain},\"complete_two_clock_cases\":{complete_two_clock_cases}}}",
        input.len() / 40
    );
}
