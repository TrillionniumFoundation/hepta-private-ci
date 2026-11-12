use super::*;

#[test]
fn initial_q24_clock_samples_the_actual_original_time_domains()
-> Result<(), Box<dyn std::error::Error>> {
    let wall_before = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
    let monotonic_before = now()?;
    let sampled = sample();
    let monotonic_after = now()?;
    let wall_after = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
    assert!((wall_before..=wall_after).contains(&u128::from(sampled.circuit_millis)));
    assert!((monotonic_before..=monotonic_after).contains(&sampled.cell_micros));
    Ok(())
}
