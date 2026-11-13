use super::*;

#[test]
fn translated_monotonic_deadline_never_renews_the_original_window() -> io::Result<()> {
    let before = Instant::now();
    let end = now_ns()?.checked_add(1_000_000_000).ok_or_else(|| io::Error::other("test clock overflow"))?;
    let converted = absolute(end, Duration::from_secs(30))?;
    assert!(converted > before);
    assert!(converted <= Instant::now() + Duration::from_secs(1));
    assert!(remaining(converted)? <= Duration::from_secs(1));
    Ok(())
}

#[test]
fn expired_and_overlong_original_windows_are_refused_without_waiting() -> io::Result<()> {
    assert!(absolute(0, Duration::from_secs(30)).is_err());
    assert!(absolute(now_ns()?, Duration::from_secs(30)).is_err());
    assert!(absolute(u64::MAX, Duration::from_secs(300)).is_err());
    Ok(())
}
