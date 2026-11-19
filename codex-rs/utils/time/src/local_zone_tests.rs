use super::ConfigurationError;
use super::Zone;
use crate::LocalTimeError;
use crate::Timestamp;
use pretty_assertions::assert_eq;

fn fixed_fixture(version: u8, indicators: (u8, u8)) -> Vec<u8> {
    let mut bytes = b"TZif".to_vec();
    bytes.push(version);
    bytes.extend([0; 15]);
    for count in [1_u32, 1, 0, 0, 1, 4] {
        bytes.extend(count.to_be_bytes());
    }
    bytes.extend(3_600_i32.to_be_bytes());
    bytes.extend([0, 0]);
    bytes.extend(b"STD\0");
    bytes.extend([indicators.0, indicators.1]);
    if version != 0 {
        bytes.extend(bytes.clone());
        bytes.extend(b"\n\n");
    }
    bytes
}

#[test]
fn legacy_indicator_values_keep_original_acceptance_boundary() {
    for version in [0, b'2', b'3'] {
        for standard in 0..=255 {
            for universal in 0..=255 {
                let bytes = fixed_fixture(version, (standard, universal));
                let actual = Zone::tzif(&bytes).ok().and_then(|zone| zone.offset(0).ok());
                let expected = if (standard, universal) == (0, 1) {
                    None
                } else {
                    Some(3_600)
                };
                assert_eq!(
                    actual, expected,
                    "version={version} standard={standard} universal={universal}"
                );
            }
        }
    }
}

#[test]
fn incomplete_blocks_and_invalid_dst_flags_remain_rejected() {
    for version in [0, b'2', b'3'] {
        let bytes = fixed_fixture(version, (2, 255));
        for length in 0..bytes.len() {
            let actual = Zone::tzif(&bytes[..length])
                .ok()
                .and_then(|zone| zone.offset(0).ok());
            // One newline is a valid empty footer in both readers.
            let expected = if version != 0 && length == bytes.len() - 1 {
                Some(3_600)
            } else {
                None
            };
            assert_eq!(actual, expected, "version={version} length={length}");
        }
        let mut invalid = bytes.clone();
        let header = if version == 0 {
            0
        } else {
            (bytes.len() - 2) / 2
        };
        invalid[header + 48] = 2;
        assert!(matches!(
            Zone::tzif(&invalid),
            Err(ConfigurationError::Invalid)
        ));
    }
}

#[test]
fn absent_extrapolation_footer_keeps_last_real_offset() {
    let mut bytes = b"TZif\0".to_vec();
    bytes.extend([0; 15]);
    for count in [0_u32, 0, 0, 1, 2, 8] {
        bytes.extend(count.to_be_bytes());
    }
    bytes.extend(0_i32.to_be_bytes());
    bytes.push(1);
    bytes.extend(0_i32.to_be_bytes());
    bytes.extend([0, 0]);
    bytes.extend(3_600_i32.to_be_bytes());
    bytes.extend([0, 4]);
    bytes.extend(b"UTC\0STD\0");
    let zone = Zone::tzif(&bytes).expect("transition without footer");
    assert_eq!(
        [
            zone.offset(-1),
            zone.offset(0),
            zone.offset(8_210_266_876_799)
        ],
        [Ok(0), Ok(3_600), Ok(3_600)]
    );
}

#[test]
fn invalid_offsets_do_not_silently_select_utc() {
    let mut bytes = fixed_fixture(/*version*/ 0, (2, 255));
    bytes[44..48].copy_from_slice(&86_400_i32.to_be_bytes());
    let zone = Zone::tzif(&bytes).expect("structurally valid zone");
    assert_eq!(zone.offset(0), Err(LocalTimeError::InvalidOffset));
}

#[test]
fn inconsistent_posix_ordering_retains_neighboring_year_lookup() {
    let zone = Zone::posix("EST5EDT,J60/2,60/2").expect("legacy rule");
    for (input, offset) in [
        ("2023-03-01T06:59:59Z", -18_000),
        ("2023-03-01T07:00:00Z", -14_400),
        ("2023-03-02T05:59:59Z", -14_400),
        ("2023-03-02T06:00:00Z", -18_000),
        ("2024-03-01T05:59:59Z", -14_400),
        ("2024-03-01T06:00:00Z", -18_000),
        ("2024-03-01T07:00:00Z", -14_400),
    ] {
        let instant: Timestamp = input.parse().expect(input);
        assert_eq!(zone.offset(instant.timestamp()), Ok(offset), "{input}");
    }
}

#[test]
fn explicit_posix_offset_hours_retain_configuration_rejection() {
    for value in [
        "XYZ24",
        "XYZ-24",
        "XYZ23DST24,M3.2.0,M11.1.0",
        "XYZ23DST-24,M3.2.0,M11.1.0",
    ] {
        assert!(
            matches!(Zone::posix(value), Err(ConfigurationError::Invalid)),
            "{value}"
        );
        for version in [b'2', b'3'] {
            let mut bytes = fixed_fixture(version, (0, 0));
            bytes.truncate(bytes.len() - 2);
            bytes.extend(format!("\n{value}\n").as_bytes());
            assert!(
                matches!(Zone::tzif(&bytes), Err(ConfigurationError::Invalid)),
                "{value} version={version}"
            );
        }
    }
    assert_eq!(
        Zone::posix("XYZ-23:59:59")
            .expect("positive maximum")
            .offset(0),
        Ok(86_399)
    );
    assert_eq!(
        Zone::posix("XYZ23:59:59")
            .expect("negative maximum")
            .offset(0),
        Ok(-86_399)
    );
}

#[test]
fn implicit_dst_shift_and_transition_clocks_keep_original_boundaries() {
    let zone = Zone::posix("XYZ-23DST,M3.2.0,M11.1.0").expect("implicit daylight offset");
    let winter: Timestamp = "2024-01-15T00:00:00Z".parse().expect("winter");
    let summer: Timestamp = "2024-07-15T00:00:00Z".parse().expect("summer");
    assert_eq!(zone.offset(winter.timestamp()), Ok(82_800));
    assert_eq!(
        zone.offset(summer.timestamp()),
        Err(LocalTimeError::InvalidOffset)
    );
    assert!(Zone::posix("XYZ0DST,M3.2.0/24,M11.1.0/24").is_ok());
}
