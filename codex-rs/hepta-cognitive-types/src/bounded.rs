//! JSON byte budgets for allocation-free counting and bounded retained output.
//! An exceeded size is a lower bound (`maximum + 1`), not a full traversal.

use std::io;
use std::io::Write;

use serde::Serialize;

use crate::hnmf::HnmfContractError;

pub(crate) fn serialized_size<T: Serialize>(
    value: &T,
    maximum: usize,
    field: &'static str,
) -> Result<usize, HnmfContractError> {
    let mut writer = ByteBudget {
        maximum,
        written: 0,
        exceeded: false,
    };
    let result = serde_json::to_writer(&mut writer, value);
    if writer.exceeded {
        return Err(HnmfContractError::LimitExceeded {
            field,
            actual: maximum.saturating_add(1),
            maximum,
        });
    }
    result.map_err(|_| HnmfContractError::Invalid("contract serialization"))?;
    Ok(writer.written)
}

struct ByteBudget {
    maximum: usize,
    written: usize,
    exceeded: bool,
}

impl Write for ByteBudget {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > self.maximum.saturating_sub(self.written) {
            self.exceeded = true;
            return Err(io::Error::other("cognitive payload byte limit exceeded"));
        }
        self.written += bytes.len();
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

pub(crate) enum BoundedSerializationError {
    LimitExceeded { maximum: usize },
    Json(serde_json::Error),
}

/// Bound the bytes actually retained, even if Serialize changes after preflight.
/// Arbitrary work performed by a caller's Serialize implementation is not contained.
pub(crate) fn serialized_bytes<T: Serialize>(
    value: &T,
    maximum: usize,
) -> Result<Vec<u8>, BoundedSerializationError> {
    let mut writer = BoundedBuffer {
        budget: ByteBudget {
            maximum,
            written: 0,
            exceeded: false,
        },
        bytes: Vec::with_capacity(maximum.min(1_024)),
    };
    let result = serde_json::to_writer(&mut writer, value);
    if writer.budget.exceeded {
        return Err(BoundedSerializationError::LimitExceeded { maximum });
    }
    result.map_err(BoundedSerializationError::Json)?;
    Ok(writer.bytes)
}

struct BoundedBuffer {
    budget: ByteBudget,
    bytes: Vec<u8>,
}

impl Write for BoundedBuffer {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let written = self.budget.write(bytes)?;
        self.bytes.extend_from_slice(bytes);
        Ok(written)
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::ser::SerializeSeq;
    use std::cell::Cell;

    #[test]
    fn serialized_budget_counts_escaped_utf8_and_exact_boundary() {
        for value in ["", "é", "e\u{301}", "\"\\\n", "🦀"] {
            let actual = serde_json::to_vec(value).expect("fixture JSON").len();
            assert_eq!(serialized_size(&value, actual, "payload"), Ok(actual));
            assert!(matches!(
                serialized_size(&value, actual - 1, "payload"),
                Err(HnmfContractError::LimitExceeded { .. })
            ));
        }
    }

    struct CountedSequence<'a>(&'a Cell<usize>);

    impl Serialize for CountedSequence<'_> {
        fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
        where
            S: serde::Serializer,
        {
            let mut sequence = serializer.serialize_seq(Some(100_000))?;
            for _ in 0..100_000 {
                self.0.set(self.0.get() + 1);
                sequence.serialize_element(&0u8)?;
            }
            sequence.end()
        }
    }

    #[test]
    fn byte_budget_stops_serialization_before_traversing_oversized_input() {
        let visited = Cell::new(0);
        assert_eq!(
            serialized_size(&CountedSequence(&visited), 16, "payload"),
            Err(HnmfContractError::LimitExceeded {
                field: "payload",
                actual: 17,
                maximum: 16,
            })
        );
        assert!(visited.get() < 20);
    }
}
