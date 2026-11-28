use chrono::DateTime;
use chrono::Duration as ChronoDuration;
use chrono::Utc;
use std::cell::Cell;
use std::io::Write;
use std::time::Duration;

#[cfg(not(feature = "hia-native"))]
compile_error!("cloud caller replay must execute the production native feature");

thread_local! {
    static CLOCK: Cell<Option<(DateTime<Utc>, u64)>> = const { Cell::new(None) };
}

fn read_clock() -> DateTime<Utc> {
    CLOCK.with(|clock| {
        let (now, reads) = clock.get().expect("caller clock was prepared");
        clock.set(Some((now, reads + 1)));
        now
    })
}

// The original production error has no fields. This replay observes its success
// or failure category; the unchanged complete crate tests cover its public
// Display/Error behavior and the rest of save's signed file-writing path.
#[derive(Debug)]
struct CloudConfigBundleCacheError;

// Generated from the complete immutable/current save methods. Only Utc::now()
// is replaced in each calculation fragment, with the same counting clock.
include!(env!("CODEX_CLOUD_DEADLINE_METHODS"));

fn encoded(value: Option<DateTime<Utc>>) -> [u64; 3] {
    match value {
        Some(value) => [
            1,
            value.timestamp() as u64,
            u64::from(value.timestamp_subsec_nanos()),
        ],
        None => [0; 3],
    }
}

#[test]
fn complete_cloud_and_std_duration_corpora_preserve_deadlines_and_clock_order() {
    let input = std::fs::read(std::env::var_os("CODEX_CLOUD_DEADLINE_CASES").unwrap()).unwrap();
    assert_eq!(input.len() % 40, 0);
    let output =
        std::fs::File::create_new(std::env::var_os("CODEX_CLOUD_DEADLINE_TRACE").unwrap()).unwrap();
    let mut trace = std::io::BufWriter::new(output);
    let mut cloud = 0_u64;
    let mut generic = 0_u64;
    let mut outside_typed_domain = 0_u64;
    let mut cloud_errors = 0_u64;
    let mut generic_errors = 0_u64;
    for (index, bytes) in input.chunks_exact(40).enumerate() {
        let [operation, seconds, nanos, duration_seconds, duration_nanos]: [u64; 5] =
            std::array::from_fn(|offset| {
                u64::from_le_bytes(bytes[offset * 8..(offset + 1) * 8].try_into().unwrap())
            });
        assert!(operation <= 1, "unknown corpus operation");
        if operation == 0 {
            assert_eq!([duration_seconds, duration_nanos], [3600, 0]);
        }
        let timestamp = u32::try_from(nanos)
            .ok()
            .and_then(|nanos| DateTime::<Utc>::from_timestamp(seconds as i64, nanos));
        let mut observed = [0_u64; 9];
        if let Some(now) = timestamp
            && duration_nanos < 1_000_000_000
        {
            let (original, native, original_reads, native_reads) = if operation == 0 {
                cloud += 1;
                let (original, original_reads) = original::cloud(now);
                let (native, native_reads) = current::cloud(now);
                assert_eq!(original_reads, 1, "one original clock read");
                assert_eq!(native_reads, original_reads, "clock order at input {index}");
                cloud_errors += u64::from(original.is_none());
                (original, native, original_reads, native_reads)
            } else {
                generic += 1;
                let duration =
                    Duration::new(duration_seconds, u32::try_from(duration_nanos).unwrap());
                let original = ChronoDuration::from_std(duration)
                    .ok()
                    .and_then(|duration| now.checked_add_signed(duration));
                let native = current::hia_datetime_deadline::add_std(
                    now.timestamp(),
                    now.timestamp_subsec_nanos(),
                    duration,
                )
                .map(|(seconds, nanos)| {
                    DateTime::from_timestamp(seconds, nanos)
                        .expect("native success must return a valid timestamp")
                });
                generic_errors += u64::from(original.is_none());
                (original, native, 0, 0)
            };
            assert_eq!(
                native, original,
                "full actual deadline at corpus input {index}"
            );
            observed[0] = 1;
            observed[1..4].copy_from_slice(&encoded(original));
            observed[4..7].copy_from_slice(&encoded(native));
            observed[7] = original_reads;
            observed[8] = native_reads;
        } else {
            outside_typed_domain += 1;
        }
        for word in observed {
            trace.write_all(&word.to_le_bytes()).unwrap();
        }
    }
    trace.flush().unwrap();
    assert_eq!(
        cloud + generic + outside_typed_domain,
        (input.len() / 40) as u64
    );
    assert!(cloud > 0 && generic > 0 && cloud_errors > 0 && generic_errors > 0);
    println!(
        "CLOUD_DEADLINE_REPORT={{\"input_cases\":{},\"cloud_cases\":{cloud},\"generic_cases\":{generic},\"outside_typed_domain\":{outside_typed_domain},\"cloud_errors\":{cloud_errors},\"generic_errors\":{generic_errors},\"clock_reads_per_implementation\":{cloud}}}",
        input.len() / 40
    );
}
