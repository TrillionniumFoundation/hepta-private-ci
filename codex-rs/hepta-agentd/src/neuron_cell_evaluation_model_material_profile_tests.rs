//! Product v4 list-width compatibility and bounded rejection controls.
use pretty_assertions::assert_eq;

use super::Error;
use super::Reader;
use super::StableId;

#[test]
fn product_qualification_v4_id_vectors_match_count_width_and_preserve_tail() -> anyhow::Result<()> {
    // These are the Product v4 bytes: u64 vector count, then u32 ID lengths.
    // A following field must remain available even when the vector is empty.
    let mut empty = Reader::new(b"\0\0\0\0\0\0\0\0\x5a");
    assert_eq!(empty.ids_u64()?, Vec::<StableId>::new());
    assert_eq!(empty.u8()?, 0x5a);
    empty.finish()?;

    let mut multiple = Reader::new(b"\0\0\0\0\0\0\0\x02\0\0\0\x03one\0\0\0\x03two\x5a");
    assert_eq!(
        multiple.ids_u64()?,
        vec![StableId::new("one")?, StableId::new("two")?]
    );
    assert_eq!(multiple.u8()?, 0x5a);
    multiple.finish()?;

    // Signed request/decision lists continue to use the original u32 reader.
    let mut request = Reader::new(b"\0\0\0\x02\0\0\0\x03one\0\0\0\x03two\x5a");
    assert_eq!(
        request.ids()?,
        vec![StableId::new("one")?, StableId::new("two")?]
    );
    assert_eq!(request.u8()?, 0x5a);
    request.finish()?;
    Ok(())
}

#[test]
fn product_qualification_v4_id_vectors_reject_truncation() {
    let complete = b"\0\0\0\0\0\0\0\x02\0\0\0\x03one\0\0\0\x03two";
    for end in 0..complete.len() {
        let mut reader = Reader::new(&complete[..end]);
        assert!(
            matches!(
                reader.ids_u64(),
                Err(Error::Binding("truncated original material"))
            ),
            "truncated Product v4 vector at {end}"
        );
    }
    let mut empty_id = Reader::new(b"\0\0\0\0\0\0\0\x01\0\0\0\0");
    assert!(matches!(
        empty_id.ids_u64(),
        Err(Error::Binding("material identifier"))
    ));
}

#[test]
fn product_qualification_v4_id_vectors_enforce_original_count_bound() -> anyhow::Result<()> {
    let mut maximum = 1024_u64.to_be_bytes().to_vec();
    for _ in 0..1024 {
        maximum.extend_from_slice(b"\0\0\0\x01a");
    }
    let mut reader = Reader::new(&maximum);
    assert_eq!(reader.ids_u64()?, vec![StableId::new("a")?; 1024]);
    reader.finish()?;

    // Reject the count before attempting any IDs or allocating an input-sized
    // vector; high bits must not be truncated by a usize/u32 conversion.
    for count in [1025_u64, u64::from(u32::MAX) + 1, u64::MAX] {
        let bytes = count.to_be_bytes();
        let mut reader = Reader::new(&bytes);
        assert!(matches!(
            reader.ids_u64(),
            Err(Error::Binding("bounded original material count"))
        ));
    }
    Ok(())
}

#[test]
fn original_execution_envelope_ids_match_u16_width_and_preserve_tail() -> anyhow::Result<()> {
    // The HPEXEV01 producer uses u16 lengths for these two identifiers.
    // Fixed framing bytes are data only; no signed evidence is fabricated.
    let bytes = b"HPEXEV01\0\x03one\0\x03two\x5a";
    let mut reader = Reader::new(bytes);
    reader.literal(b"HPEXEV01")?;
    assert_eq!(reader.id_u16()?, StableId::new("one")?);
    assert_eq!(reader.id_u16()?, StableId::new("two")?);
    assert_eq!(reader.u8()?, 0x5a);
    reader.finish()?;

    // The unchanged u32 reader reproduces the former call-site rejection on
    // exactly the same valid execution-profile bytes.
    let mut wrong_profile = Reader::new(&bytes[8..]);
    assert!(matches!(
        wrong_profile.id(),
        Err(Error::Binding("bounded original material count"))
    ));

    // The regular material identifier profile still has its original width.
    let mut regular = Reader::new(b"\0\0\0\x03one\x5a");
    assert_eq!(regular.id()?, StableId::new("one")?);
    assert_eq!(regular.u8()?, 0x5a);
    regular.finish()?;
    Ok(())
}

#[test]
fn original_execution_envelope_ids_reject_truncated_or_other_profile_bytes() {
    let complete = b"\0\x03one\0\x03two";
    for end in 0..complete.len() {
        let mut reader = Reader::new(&complete[..end]);
        let result = reader.id_u16().and_then(|_| reader.id_u16());
        assert!(
            matches!(result, Err(Error::Binding("truncated original material"))),
            "truncated execution identifiers at {end}"
        );
    }
    let mut other_profile = Reader::new(b"\0\0\0\x03one");
    assert!(matches!(
        other_profile.id_u16(),
        Err(Error::Binding("bounded original execution identifier"))
    ));
    let mut invalid_utf8 = Reader::new(b"\0\x01\xff");
    assert!(matches!(
        invalid_utf8.id_u16(),
        Err(Error::Binding("material identifier"))
    ));
}

#[test]
fn original_execution_envelope_ids_enforce_original_identifier_bounds() -> anyhow::Result<()> {
    let mut maximum = 128_u16.to_be_bytes().to_vec();
    maximum.extend_from_slice(&[b'a'; 128]);
    let mut reader = Reader::new(&maximum);
    assert_eq!(reader.id_u16()?, StableId::new("a".repeat(128))?);
    reader.finish()?;

    for length in [0_u16, 129, u16::MAX] {
        let bytes = length.to_be_bytes();
        let mut reader = Reader::new(&bytes);
        assert!(matches!(
            reader.id_u16(),
            Err(Error::Binding("bounded original execution identifier"))
        ));
    }
    Ok(())
}
