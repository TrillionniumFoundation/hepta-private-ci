use std::cell::Cell;

use serde::ser::SerializeSeq;

use super::*;

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
fn native_learning_budget_stops_before_materializing_oversized_payload() {
    let visited = Cell::new(0);
    assert_eq!(
        validate_serialized_bound_v1(&CountedSequence(&visited), 16, "nativeLearning"),
        Err(HnmfContractError::LimitExceeded {
            field: "nativeLearning",
            actual: 17,
            maximum: 16,
        })
    );
    assert!(visited.get() < 20);
}

#[test]
fn native_learning_budget_preserves_escaped_utf8_boundaries() {
    for value in ["", "é", "e\u{301}", "\"\\\n", "🦀"] {
        let size = serde_json::to_vec(value).expect("fixture JSON").len();
        assert_eq!(
            validate_serialized_bound_v1(&value, size, "nativeLearning"),
            Ok(())
        );
        assert_eq!(
            validate_serialized_bound_v1(&value, size - 1, "nativeLearning"),
            Err(HnmfContractError::LimitExceeded {
                field: "nativeLearning",
                actual: size,
                maximum: size - 1,
            })
        );
    }
}
