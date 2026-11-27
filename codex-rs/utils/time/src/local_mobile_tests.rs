use super::find_zone;
use pretty_assertions::assert_eq;

fn database(width: usize) -> Vec<u8> {
    let mut bytes = b"tzdata2026a\0".to_vec();
    let data_start = 24 + width * 2;
    for offset in [24, data_start, data_start + 6] {
        bytes.extend((offset as u32).to_be_bytes());
    }
    for (name, start, length) in [
        (b"Area/One".as_slice(), 0_u32, 3_u32),
        (b"Area/Two".as_slice(), 3, 3),
    ] {
        let mut entry = vec![0; width];
        entry[..name.len()].copy_from_slice(name);
        entry[40..44].copy_from_slice(&start.to_be_bytes());
        entry[44..48].copy_from_slice(&length.to_be_bytes());
        bytes.extend(entry);
    }
    bytes.extend(b"onetwo");
    bytes
}

#[test]
fn both_mobile_database_layouts_select_exact_named_bytes() {
    for width in [48, 52] {
        let bytes = database(width);
        assert_eq!(
            find_zone(&bytes, width, b"Area/One").expect("first"),
            Some(b"one".to_vec())
        );
        assert_eq!(
            find_zone(&bytes, width, b"Area/Two").expect("second"),
            Some(b"two".to_vec())
        );
        assert_eq!(
            find_zone(&bytes, width, b"Area/Absent").expect("missing"),
            None
        );
    }
}

#[test]
fn truncated_indexes_and_out_of_bounds_entries_return_errors() {
    for width in [48, 52] {
        let bytes = database(width);
        for length in 0..24 + width * 2 {
            assert!(
                find_zone(&bytes[..length], width, b"Area/One").is_err(),
                "width={width} length={length}"
            );
        }
        let mut invalid = bytes.clone();
        invalid[64..68].copy_from_slice(&u32::MAX.to_be_bytes());
        assert!(find_zone(&invalid, width, b"Area/One").is_err());
        let mut invalid = bytes;
        invalid[16..20].copy_from_slice(&25_u32.to_be_bytes());
        assert!(find_zone(&invalid, width, b"Area/One").is_err());
    }
}
