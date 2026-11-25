use super::*;

fn elf() -> Vec<u8> {
    let mut bytes = vec![0; 4096];
    bytes[..7].copy_from_slice(b"\x7fELF\x02\x01\x01");
    bytes[16..18].copy_from_slice(&2u16.to_le_bytes());
    bytes[18..20].copy_from_slice(&62u16.to_le_bytes());
    bytes[24..32].copy_from_slice(&0x400100u64.to_le_bytes());
    bytes[32..40].copy_from_slice(&64u64.to_le_bytes());
    bytes[52..54].copy_from_slice(&64u16.to_le_bytes());
    bytes[54..56].copy_from_slice(&56u16.to_le_bytes());
    bytes[56..58].copy_from_slice(&1u16.to_le_bytes());
    bytes[64..68].copy_from_slice(&1u32.to_le_bytes());
    bytes[68..72].copy_from_slice(&5u32.to_le_bytes());
    bytes[80..88].copy_from_slice(&0x400000u64.to_le_bytes());
    bytes[96..104].copy_from_slice(&4096u64.to_le_bytes());
    bytes[104..112].copy_from_slice(&4096u64.to_le_bytes());
    bytes[112..120].copy_from_slice(&4096u64.to_le_bytes());
    bytes
}

#[test]
fn installed_role_elf_rejects_invalid_or_unbounded_loads() {
    require_elf(&elf()).unwrap();
    let mutations: &[fn(&mut Vec<u8>)] = &[
        |v| v.truncate(63),
        |v| v[4] = 1,
        |v| v[18] = 183,
        |v| v[54] = 55,
        |v| v[56] = 65,
        |v| v[32..40].copy_from_slice(&u64::MAX.to_le_bytes()),
        |v| v[24..32].copy_from_slice(&0x900000u64.to_le_bytes()),
        |v| v[68..72].copy_from_slice(&7u32.to_le_bytes()),
        |v| v[96..104].copy_from_slice(&4097u64.to_le_bytes()),
        |v| v[104..112].copy_from_slice(&0u64.to_le_bytes()),
        |v| v[104..112].copy_from_slice(&(LOAD_BOUND + 1).to_le_bytes()),
        |v| v[112..120].copy_from_slice(&8191u64.to_le_bytes()),
        |v| v.resize(FILE_BOUND as usize + 1, 0),
    ];
    for mutate in mutations {
        let mut value = elf();
        mutate(&mut value);
        assert!(require_elf(&value).is_err());
    }
    let mut overlap = elf();
    overlap[56..58].copy_from_slice(&2u16.to_le_bytes());
    overlap.copy_within(64..120, 120);
    assert!(require_elf(&overlap).is_err());
}
