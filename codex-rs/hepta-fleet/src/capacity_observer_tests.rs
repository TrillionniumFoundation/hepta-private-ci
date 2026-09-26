use super::*;
use pretty_assertions::assert_eq;

#[cfg(target_os = "linux")]
#[test]
fn procfs_observer_reads_real_shapes_and_enforces_pressure() {
    let directory = tempfile::tempdir().expect("tempdir");
    let meminfo = directory.path().join("meminfo");
    let pressure = directory.path().join("pressure");
    std::fs::write(&meminfo, "MemTotal: 8192 kB\nMemAvailable: 4096 kB\n")
        .expect("meminfo");
    std::fs::write(
        &pressure,
        "some avg10=0.12 avg60=0.00 avg300=0.00 total=1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
    )
    .expect("pressure");
    let observer = LinuxProcfsCapacityObserverV1::with_paths(
        "host-a".into(),
        "rack-a".into(),
        7,
        5_000,
        100,
        &meminfo,
        &pressure,
    )
    .expect("observer");
    let observation = observer.observe(10_000).expect("observation");
    assert_eq!(observation.memory_pressure_basis_points, 12);
    assert_eq!(observation.capacity.memory_bytes, 4 * 1024 * 1024);
    assert!(observation.capacity.cpu_millis >= 1_000);
    assert_eq!(observation.valid_until_ms, 15_000);

    std::fs::write(
        &pressure,
        "some avg10=2.00 avg60=0.00 avg300=0.00 total=1\n",
    )
    .expect("high pressure");
    assert!(matches!(
        observer.observe(11_000),
        Err(CapacityObservationError::PressureLimitExceeded {
            observed: 200,
            maximum: 100
        })
    ));
}

#[test]
fn pressure_parser_is_exact_and_bounded() {
    assert_eq!(parse_percent_basis_points("0.12").expect("pressure"), 12);
    assert_eq!(parse_percent_basis_points("1.2").expect("pressure"), 120);
    assert_eq!(
        parse_percent_basis_points("100.00").expect("pressure"),
        10_000
    );
    assert!(parse_percent_basis_points("100.01").is_err());
    assert!(parse_percent_basis_points("nan").is_err());
}
