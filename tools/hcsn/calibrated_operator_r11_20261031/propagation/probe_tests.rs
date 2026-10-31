use super::*;
use pretty_assertions::assert_eq;

#[test]
fn recovered_distribution_preserves_all_receipts() {
    let parameters = [0.1; 11];
    let payload = json!({"parameters":parameters, "family":"distribution", "seed":719,
        "events":[{"driver":0.4,"micros":900000,"reset":false},
                  {"driver":-0.3,"micros":1500000,"reset":true},
                  {"driver":0.7,"micros":3000000,"reset":false}],
        "driver":0.2,"horizon_micros":1200000,"restore_after":null});
    let direct = run(serde_json::from_value(payload.clone()).unwrap()).unwrap();
    let mut restored = payload;
    restored["restore_after"] = json!(2);
    assert_eq!(
        direct,
        run(serde_json::from_value(restored).unwrap()).unwrap()
    );
}

#[test]
fn sampled_recovery_preserves_rng_and_event_times() {
    let parameters = [0.1; 11];
    let payload = json!({"parameters":parameters, "family":"sampled", "seed":701,
        "events":[{"driver":0.2,"micros":7000000,"reset":false},
                  {"driver":0.2,"micros":4000000,"reset":false}],
        "driver":0.2,"horizon_micros":2000000,"restore_after":null});
    let direct = run(serde_json::from_value(payload.clone()).unwrap()).unwrap();
    let mut restored = payload;
    restored["restore_after"] = json!(1);
    assert_eq!(
        direct,
        run(serde_json::from_value(restored).unwrap()).unwrap()
    );
}
