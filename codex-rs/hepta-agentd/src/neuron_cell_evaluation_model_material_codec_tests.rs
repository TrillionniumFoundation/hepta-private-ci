//! Canonical Product v4 vectors have u64 counts; decision v1 vectors have u32 counts.
use super::Error;
use super::Reader;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

#[test]
fn original_model_material_codec_reads_both_original_vector_widths() -> Result<(), Error> {
    let product = b"\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x01a\x00\x00\x00\x01b";
    let decision = b"\x00\x00\x00\x02\x00\x00\x00\x01a\x00\x00\x00\x01b";
    let expected = vec![StableId::new("a").unwrap(), StableId::new("b").unwrap()];
    let mut product_reader = Reader::new(product);
    assert_eq!(product_reader.ids_u64()?, expected);
    product_reader.finish()?;
    let mut decision_reader = Reader::new(decision);
    assert_eq!(decision_reader.ids()?, expected);
    decision_reader.finish()?;
    let mut empty = Reader::new(&[0; 8]);
    assert!(empty.ids_u64()?.is_empty());
    empty.finish()
}

#[test]
fn original_model_material_codec_rejects_unbounded_product_counts() {
    for count in [1025_u64, 1_u64 << 32, u64::MAX] {
        let bytes = count.to_be_bytes();
        assert!(matches!(
            Reader::new(&bytes).ids_u64(),
            Err(Error::Binding("bounded original material count"))
        ));
    }
}

#[test]
fn original_model_material_codec_rejects_truncated_product_vectors() {
    let valid = b"\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x01a";
    for end in 0..valid.len() {
        assert!(
            Reader::new(&valid[..end]).ids_u64().is_err(),
            "prefix {end}"
        );
    }
    let invalid_id = b"\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x81";
    assert!(Reader::new(invalid_id).ids_u64().is_err());
    let absent_id = b"\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00";
    assert!(Reader::new(absent_id).ids_u64().is_err());
}

#[test]
fn original_model_material_codec_rejects_wrong_width_and_trailing_bytes() -> Result<(), Error> {
    let product = b"\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x01a";
    let decision = b"\x00\x00\x00\x01\x00\x00\x00\x01a";
    assert!(Reader::new(decision).ids_u64().is_err());
    let mut wrong_width = Reader::new(product);
    assert!(wrong_width.ids()?.is_empty());
    assert!(wrong_width.finish().is_err());
    let mut trailing = product.to_vec();
    trailing.push(0);
    let mut reader = Reader::new(&trailing);
    assert_eq!(reader.ids_u64()?, vec![StableId::new("a").unwrap()]);
    assert!(reader.finish().is_err());
    Ok(())
}

#[test]
fn original_model_material_codec_reads_execution_ids_without_changing_product_ids()
-> Result<(), Error> {
    let execution = b"\x00\x03one\x00\x03two";
    let product = b"\x00\x00\x00\x03one\x00\x00\x00\x03two";
    let expected = [StableId::new("one").unwrap(), StableId::new("two").unwrap()];
    let mut execution_reader = Reader::new(execution);
    assert_eq!(
        [execution_reader.id_u16()?, execution_reader.id_u16()?],
        expected
    );
    execution_reader.finish()?;
    let mut product_reader = Reader::new(product);
    assert_eq!([product_reader.id()?, product_reader.id()?], expected);
    product_reader.finish()
}

#[test]
fn original_model_material_codec_bounds_execution_identifier_length() -> Result<(), Error> {
    let maximum = "a".repeat(/*n*/ 128);
    let mut bytes = vec![0, 128];
    bytes.extend_from_slice(maximum.as_bytes());
    let mut reader = Reader::new(&bytes);
    assert_eq!(reader.id_u16()?, StableId::new(maximum.as_str()).unwrap());
    reader.finish()?;
    for length in [0_u16, 129, u16::MAX] {
        assert!(matches!(
            Reader::new(&length.to_be_bytes()).id_u16(),
            Err(Error::Binding("bounded original execution identifier"))
        ));
    }
    Ok(())
}

#[test]
fn original_model_material_codec_rejects_truncated_and_invalid_execution_identifiers() {
    let valid = b"\x00\x05alpha";
    for end in 0..valid.len() {
        assert!(Reader::new(&valid[..end]).id_u16().is_err(), "prefix {end}");
    }
    assert!(Reader::new(b"\x00\x01\xff").id_u16().is_err());
}

#[test]
fn original_model_material_codec_rejects_execution_id_wrong_width_and_trailing_bytes()
-> Result<(), Error> {
    let execution = b"\x00\x01a";
    let product = b"\x00\x00\x00\x01a";
    assert!(Reader::new(product).id_u16().is_err());
    assert!(Reader::new(execution).id().is_err());
    let mut trailing = execution.to_vec();
    trailing.push(0);
    let mut reader = Reader::new(&trailing);
    assert_eq!(reader.id_u16()?, StableId::new("a").unwrap());
    assert!(reader.finish().is_err());
    Ok(())
}
