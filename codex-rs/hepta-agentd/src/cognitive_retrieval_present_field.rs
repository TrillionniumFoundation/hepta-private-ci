//! Preserve absent-versus-null semantics at versioned bootstrap boundaries.
//!
//! `Option<T>` alone treats explicit JSON null as absence. With `default` and
//! this field deserializer, omission remains None but every present value must
//! be a valid T. This is important when v1 must reject *all* v2 fields.

use serde::Deserialize;
use serde::Deserializer;

pub(super) fn present_value<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    T::deserialize(deserializer).map(Some)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Fields {
        #[serde(default, deserialize_with = "present_value")]
        count: Option<u32>,
        #[serde(default, deserialize_with = "present_value")]
        salt: Option<String>,
    }

    #[test]
    fn omission_is_not_null() {
        let omitted: Fields = serde_json::from_str("{}").expect("absent fields");
        assert_eq!(omitted.count, None);
        assert_eq!(omitted.salt, None);
        for wire in [r#"{"count":null}"#, r#"{"salt":null}"#] {
            assert!(serde_json::from_str::<Fields>(wire).is_err());
        }
    }

    #[test]
    fn values_stay_typed_and_duplicates_fail() {
        let valid: Fields =
            serde_json::from_str(r#"{"count":0,"salt":"a"}"#).expect("typed present values");
        assert_eq!(valid.count, Some(0));
        assert_eq!(valid.salt.as_deref(), Some("a"));
        for wire in [
            r#"{"count":true}"#,
            r#"{"count":-1}"#,
            r#"{"count":4294967296}"#,
            r#"{"count":1.5}"#,
            r#"{"count":1,"count":2}"#,
            r#"{"count":null,"count":1}"#,
            r#"{"salt":1}"#,
            r#"{"unknown":1}"#,
        ] {
            assert!(serde_json::from_str::<Fields>(wire).is_err(), "{wire}");
        }
    }
}
