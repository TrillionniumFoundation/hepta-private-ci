//! Qualification-only retained-byte accounting, not an authorization or codec
//! for native TaskFlow event hashes. Only explicit qualification tests include it.
//!
//! Callers must supply the complete retained row inventory and actual producer
//! encoding. This layer cannot prove observation authenticity or missing rows.

pub(crate) const MAX_RETAINED_BYTES: usize = 16_384;
pub(crate) const MAX_OBSERVATION_BYTES: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum EncodingError {
    LengthOverflow,
    RetainedLimit,
    ObservationLimit,
}

pub(crate) enum FieldValue<'a> {
    Null,
    Uint(u64),
    Text(&'a str),
    Blob(&'a [u8]),
    /// Exact already-serialized JSON bytes, including actual escaping.
    /// Producer schema validation remains the caller's responsibility.
    Json(&'a [u8]),
}

pub(crate) struct EncodedRecord(Vec<u8>);

impl EncodedRecord {
    pub(crate) fn bytes(&self) -> &[u8] {
        &self.0
    }
}

pub(crate) fn encode_record(
    fields: &[(&str, FieldValue<'_>)],
) -> Result<EncodedRecord, EncodingError> {
    let count = u32::try_from(fields.len()).map_err(|_| EncodingError::LengthOverflow)?;
    let mut bytes = Vec::new();
    bytes.push(b'R');
    bytes.extend_from_slice(&count.to_be_bytes());
    for (key, value) in fields {
        let number;
        let (tag, raw): (u8, &[u8]) = match value {
            FieldValue::Null => (b'N', &[]),
            FieldValue::Uint(value) => {
                number = value.to_be_bytes();
                (b'I', &number)
            }
            FieldValue::Text(value) => (b'T', value.as_bytes()),
            FieldValue::Blob(value) => (b'B', value),
            FieldValue::Json(value) => (b'J', value),
        };
        let key_len = u32::try_from(key.len()).map_err(|_| EncodingError::LengthOverflow)?;
        let value_len = u32::try_from(raw.len()).map_err(|_| EncodingError::LengthOverflow)?;
        let additional = key
            .len()
            .checked_add(raw.len())
            .and_then(|length| length.checked_add(9))
            .ok_or(EncodingError::LengthOverflow)?;
        let total = bytes
            .len()
            .checked_add(additional)
            .ok_or(EncodingError::LengthOverflow)?;
        if total > MAX_RETAINED_BYTES {
            return Err(EncodingError::RetainedLimit);
        }
        bytes.extend_from_slice(&key_len.to_be_bytes());
        bytes.extend_from_slice(key.as_bytes());
        bytes.push(tag);
        bytes.extend_from_slice(&value_len.to_be_bytes());
        bytes.extend_from_slice(raw);
    }
    Ok(EncodedRecord(bytes))
}

/// Measures records exactly as retained. Equal copies are each charged; native
/// deduplication must omit nonexistent new records, not silently deduplicate here.
#[derive(Default)]
pub(crate) struct RetainedBudget {
    used: usize,
}

impl RetainedBudget {
    pub(crate) fn charge(&mut self, record: &EncodedRecord) -> Result<(), EncodingError> {
        let total = self
            .used
            .checked_add(record.bytes().len())
            .ok_or(EncodingError::LengthOverflow)?;
        if total > MAX_RETAINED_BYTES {
            return Err(EncodingError::RetainedLimit);
        }
        self.used = total;
        Ok(())
    }

    pub(crate) fn used(&self) -> usize {
        self.used
    }
}

/// The complete outer observation, not only its nested producer bytes.
/// Its actual retained record is also charged to the aggregate budget.
pub(crate) fn check_observation(bytes: &[u8]) -> Result<(), EncodingError> {
    if bytes.len() > MAX_OBSERVATION_BYTES {
        Err(EncodingError::ObservationLimit)
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_total_boundary_and_one_byte_over() {
        let payload = vec![0; MAX_RETAINED_BYTES - 15];
        let record = encode_record(&[("x", FieldValue::Blob(&payload))]).unwrap();
        assert_eq!(record.bytes().len(), MAX_RETAINED_BYTES);
        let mut budget = RetainedBudget::default();
        budget.charge(&record).unwrap();
        let extra = encode_record(&[]).unwrap();
        assert_eq!(budget.charge(&extra), Err(EncodingError::RetainedLimit));
        assert_eq!(budget.used(), MAX_RETAINED_BYTES);
        let oversized = vec![0; payload.len() + 1];
        assert!(matches!(
            encode_record(&[("x", FieldValue::Blob(&oversized))]),
            Err(EncodingError::RetainedLimit)
        ));
    }

    #[test]
    fn full_observation_has_independent_hard_limit() {
        assert_eq!(check_observation(&vec![0; 4_096]), Ok(()));
        assert_eq!(
            check_observation(&vec![0; 4_097]),
            Err(EncodingError::ObservationLimit)
        );
    }

    #[test]
    fn duplicate_retained_records_are_counted_twice() {
        let record = encode_record(&[("digest", FieldValue::Text(&"a".repeat(64)))]).unwrap();
        let mut budget = RetainedBudget::default();
        budget.charge(&record).unwrap();
        budget.charge(&record).unwrap();
        assert_eq!(budget.used(), 2 * record.bytes().len());
    }

    #[test]
    fn utf8_and_existing_json_escape_bytes_are_preserved() {
        let json = br#"{"content":"quote: \" slash: \\"}"#;
        let record = encode_record(&[
            ("text", FieldValue::Text("证据")),
            ("json", FieldValue::Json(json)),
        ])
        .unwrap();
        assert_eq!(record.bytes().len(), 5 + 9 + 4 + 6 + 9 + 4 + json.len());
        assert!(
            record
                .bytes()
                .windows(json.len())
                .any(|window| window == json)
        );
    }

    #[test]
    fn tags_lengths_and_integer_width_are_fixed() {
        let record =
            encode_record(&[("n", FieldValue::Null), ("u", FieldValue::Uint(u64::MAX))]).unwrap();
        assert_eq!(&record.bytes()[..5], &[b'R', 0, 0, 0, 2]);
        assert_eq!(record.bytes().len(), 5 + 10 + 10 + 8);
        assert_eq!(
            &record.bytes()[record.bytes().len() - 8..],
            &u64::MAX.to_be_bytes()
        );
    }

    #[test]
    fn aggregate_overflow_does_not_mutate_budget() {
        let record = encode_record(&[]).unwrap();
        let mut budget = RetainedBudget { used: usize::MAX };
        assert_eq!(budget.charge(&record), Err(EncodingError::LengthOverflow));
        assert_eq!(budget.used(), usize::MAX);
    }
}
