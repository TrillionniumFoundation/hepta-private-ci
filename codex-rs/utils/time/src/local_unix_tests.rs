use super::ConfigurationError;
use super::configured_zone;
use super::discover;
use super::read_zone_file;
use pretty_assertions::assert_eq;

#[test]
fn explicit_utc_and_posix_offsets_do_not_depend_on_host_zone() {
    assert_eq!(configured_zone(Some("")).expect("UTC").offset(0), Ok(0));
    assert_eq!(
        configured_zone(Some("XYZ-5:45")).expect("POSIX").offset(0),
        Ok(20_700)
    );
}

#[test]
fn invalid_configuration_can_use_original_system_discovery_fallback() {
    let path = ":/hepta-no-such-local-time-file-for-test";
    assert!(matches!(
        configured_zone(Some(path)),
        Err(ConfigurationError::Invalid)
    ));
    assert!(
        discover(Some(path))
            .expect("IANA or UTC fallback")
            .offset(0)
            .is_ok()
    );
}

#[test]
fn absolute_tzif_configuration_is_read_and_retains_offset() {
    let directory = tempfile::tempdir().expect("temporary zone directory");
    let path = directory.path().join("zone");
    let mut bytes = b"TZif\0".to_vec();
    bytes.extend([0; 15]);
    for count in [0_u32, 0, 0, 0, 1, 4] {
        bytes.extend(count.to_be_bytes());
    }
    bytes.extend((-20_700_i32).to_be_bytes());
    bytes.extend([0, 0]);
    bytes.extend(b"STD\0");
    std::fs::write(&path, bytes).expect("write zone");
    let name = format!(":{}", path.display());
    assert_eq!(
        configured_zone(Some(&name)).expect("file zone").offset(0),
        Ok(-20_700)
    );
}

#[test]
fn padded_file_names_retain_invalid_configuration_fallback() {
    let fallback = discover(Some(":/hepta-no-such-local-time-file-for-test")).expect("fallback");
    for value in [" America/New_York ", " Etc/UTC "] {
        assert!(
            matches!(
                configured_zone(Some(value)),
                Err(ConfigurationError::Invalid)
            ),
            "{value}"
        );
        let zone = discover(Some(value)).expect("system fallback");
        for seconds in [0, 1_710_054_000, 1_730_613_600] {
            assert_eq!(
                zone.offset(seconds),
                fallback.offset(seconds),
                "{value} at {seconds}"
            );
        }
    }
}

#[test]
fn opened_file_read_failure_is_distinct_from_a_missing_zone() {
    let directory = tempfile::tempdir().expect("temporary zone directory");
    let missing = directory.path().join("missing");
    assert_eq!(
        read_zone_file(&missing.to_string_lossy()).expect("missing"),
        None
    );
    assert!(read_zone_file(&directory.path().to_string_lossy()).is_err());
}
