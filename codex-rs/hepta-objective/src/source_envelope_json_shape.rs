use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Deserializer;
use serde::de::Error;
use serde::de::Visitor;

use crate::source_envelope_v1::*;

/// Remote struct derives also implement positional-sequence decoding. This
/// adapter is used only at object boundaries and forces their visitor through
/// the original deserializer's map path; field decoding retains original types.
pub(super) struct ObjectOnly<D>(pub(super) D);

impl<'de, D: Deserializer<'de>> Deserializer<'de> for ObjectOnly<D> {
    type Error = D::Error;

    fn deserialize_any<V: Visitor<'de>>(self, visitor: V) -> Result<V::Value, Self::Error> {
        self.0.deserialize_map(visitor)
    }

    serde::forward_to_deserialize_any! {
        bool i8 i16 i32 i64 u8 u16 u32 u64 f32 f64 char str string bytes byte_buf
        option unit unit_struct newtype_struct seq tuple tuple_struct map struct
        enum identifier ignored_any
    }
}

pub(super) fn digest<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Digest32, D::Error> {
    String::deserialize(deserializer)?
        .parse()
        .map_err(D::Error::custom)
}

pub(super) fn present_deadline<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<String>, D::Error> {
    String::deserialize(deserializer).map(Some)
}

// String-only decoding also excludes serde's externally tagged unit-enum
// object form. Spellings come directly from the ObjectiveSourceEnvelopeV1 row.
macro_rules! string_enum {
    ($function:ident, $kind:ident, {$($text:literal => $variant:ident),+ $(,)?}) => {
        pub(super) fn $function<'de, D: Deserializer<'de>>(
            deserializer: D,
        ) -> Result<$kind, D::Error> {
            match String::deserialize(deserializer)?.as_str() {
                $($text => Ok($kind::$variant),)+
                _ => Err(D::Error::custom("invalid objective enum spelling")),
            }
        }
    };
}

string_enum!(trust, ObjectiveSourceTrustV1, {
    "principal" => Principal, "trusted_system" => TrustedSystem,
    "authorized_adapter" => AuthorizedAdapter, "untrusted_evidence" => UntrustedEvidence,
});
string_enum!(predicate_comparator, ObjectivePredicateComparatorV1, {
    "eq" => Equal, "ne" => NotEqual, "lt" => LessThan, "lte" => LessThanOrEqual,
    "gt" => GreaterThan, "gte" => GreaterThanOrEqual,
});
string_enum!(constraint_comparator, ObjectiveConstraintComparatorV1, {
    "eq" => Equal, "ne" => NotEqual, "lt" => LessThan, "lte" => LessThanOrEqual,
    "gt" => GreaterThan, "gte" => GreaterThanOrEqual, "in" => In, "not_in" => NotInSet,
});
string_enum!(direction, ObjectiveSoftDirectionV1, {"maximize" => Maximize, "minimize" => Minimize});
string_enum!(risk, ObjectiveRiskClassV1, {"low" => Low, "medium" => Medium, "high" => High, "critical" => Critical});
string_enum!(rollback, ObjectiveRollbackClassV1, {
    "none" => None, "reversible" => Reversible,
    "compensatable" => Compensatable, "irreversible" => Irreversible,
});
