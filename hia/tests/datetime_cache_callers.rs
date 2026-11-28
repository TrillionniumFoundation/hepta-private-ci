use chrono::DateTime;
use chrono::TimeDelta;
use chrono::Utc;
use std::cell::Cell;
use std::time::Duration;

#[cfg(not(feature = "hia-native"))]
compile_error!("the current caller replay must execute its native HIA branch");

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

// The controller extracts the complete original and current production methods
// from their exact source files. Only Utc::now() is replaced by read_clock() in
// both model methods so identical boundary inputs and clock-read order are observable.
include!(env!("CODEX_DATETIME_CACHE_METHODS"));

#[test]
fn complete_representable_corpus_preserves_actual_callers_and_clock_order() {
    let input = std::fs::read(std::env::var_os("CODEX_DATETIME_CACHE_CASES").unwrap()).unwrap();
    assert_eq!(input.len() % 56, 0);
    let mut models = 0_u64;
    let mut plugins = 0_u64;
    let mut unrepresentable = 0_u64;
    let mut clock_reads = 0_u64;
    for (index, bytes) in input.chunks_exact(56).enumerate() {
        let row: [u64; 7] = std::array::from_fn(|offset| {
            u64::from_le_bytes(bytes[offset * 8..(offset + 1) * 8].try_into().unwrap())
        });
        let [operation, fs, fnanos, ns, nnanos, ts, tnanos] = row;
        let from_timestamp = |seconds, nanos| {
            u32::try_from(nanos)
                .ok()
                .and_then(|fraction| DateTime::<Utc>::from_timestamp(seconds as i64, fraction))
        };
        let (Some(fetched), Some(now)) = (from_timestamp(fs, fnanos), from_timestamp(ns, nnanos))
        else {
            unrepresentable += 1;
            continue;
        };
        if tnanos >= 1_000_000_000 {
            unrepresentable += 1;
            continue;
        }
        let ttl = Duration::new(ts, u32::try_from(tnanos).unwrap());
        match operation {
            0 | 1 => {
                let original = original::model(fetched, now, ttl);
                let native = current::model(fetched, now, ttl);
                assert_eq!(
                    native, original,
                    "model result and clock reads at corpus row {index}"
                );
                models += 1;
                clock_reads += original.1;
            }
            2 => {
                // The real plugin caller owns its original fixed three-hour TTL.
                assert_eq!(
                    current::plugin(Some(fetched), now),
                    original::plugin(Some(fetched), now),
                    "plugin result at corpus row {index}"
                );
                plugins += 1;
            }
            _ => panic!("unknown cache corpus operation"),
        }
    }
    println!(
        "CACHE_CALLER_REPORT={{\"input_cases\":{},\"model_cases\":{models},\"plugin_cases\":{plugins},\"transport_only_cases\":{unrepresentable},\"clock_reads\":{clock_reads}}}",
        input.len() / 56
    );
}
