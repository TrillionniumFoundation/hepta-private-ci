use super::*;

#[test]
fn media_chunks_join_to_single_container_without_repeated_headers() -> Result<()> {
    for (modality, units, unit_bytes) in [(0, 16, 48), (1, 1024, 2), (2, 4, 768)] {
        let raw = vec![128; units as usize * unit_bytes];
        let whole = encode_chunk(modality, /*start*/ 0, units, &raw)?;
        let split_units = units / 2;
        let split_bytes = split_units as usize * unit_bytes;
        let first = encode_chunk(modality, /*start*/ 0, split_units, &raw[..split_bytes])?;
        let last = encode_chunk(
            modality,
            split_units,
            units - split_units,
            &raw[split_bytes..],
        )?;
        validate_chunk(modality, /*start*/ 0, split_units, &first)?;
        validate_chunk(modality, split_units, units - split_units, &last)?;
        assert_eq!([first, last].concat(), whole);
        assert!(validate_chunk(modality, /*start*/ 0, units, &whole[..whole.len() - 1]).is_err());
    }
    Ok(())
}

#[test]
fn text_frames_count_unicode_scalars_and_reject_truncation() -> Result<()> {
    validate_chunk(
        /*modality*/ 3,
        /*start*/ 0,
        /*units*/ 3,
        "é中🙂".as_bytes(),
    )?;
    assert!(
        validate_chunk(
            /*modality*/ 3,
            /*start*/ 0,
            /*units*/ 9,
            "é中🙂".as_bytes()
        )
        .is_err()
    );
    assert!(
        validate_chunk(
            /*modality*/ 3,
            /*start*/ 0,
            /*units*/ 1,
            &[0xe4, 0xb8]
        )
        .is_err()
    );
    Ok(())
}
