//! Keep action skill envelopes out of the ordinary opaque HTTP effect path.
//!
//! V1 has no separate type tag. Its top-level contract/destination identity
//! pair is reserved here even if another field, version, or trailing JSON is
//! malformed. Nested fields and ordinary opaque bytes retain their semantics.
//! Unrecognizable bytes are not authenticated or validated as action skills.

use std::fmt;

use codex_hepta_automation::ActionSkillInvocationV1;
use serde::Deserializer;
use serde::de::IgnoredAny;
use serde::de::MapAccess;
use serde::de::Visitor;

pub(crate) fn requires_action_skill_host(wire_payload: &[u8]) -> bool {
    if serde_json::from_slice::<ActionSkillInvocationV1>(wire_payload).is_ok() {
        return true;
    }
    let mut identity = SkillIdentityFields::default();
    let mut decoder = serde_json::Deserializer::from_slice(wire_payload);
    // Retain identity fields already decoded if a later field/value is broken.
    // This is syntax classification only, never an authority or goal check.
    let _ = decoder.deserialize_map(SkillIdentityVisitor(&mut identity));
    identity.contract_digest && identity.destination_id
}

#[derive(Default)]
struct SkillIdentityFields {
    contract_digest: bool,
    destination_id: bool,
}

struct SkillIdentityVisitor<'a>(&'a mut SkillIdentityFields);

impl<'de> Visitor<'de> for SkillIdentityVisitor<'_> {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a top-level effect payload object")
    }

    fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<(), M::Error> {
        while let Some(key) = map.next_key::<String>()? {
            match key.as_str() {
                "contract_digest" => self.0.contract_digest = true,
                "destination_id" => self.0.destination_id = true,
                _ => {}
            }
            map.next_value::<IgnoredAny>()?;
        }
        Ok(())
    }
}
