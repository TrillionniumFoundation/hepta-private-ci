use std::fmt;

use codex_hepta_types::Digest32;

use crate::ContextRealizedItemV2;
use crate::SerializedContextV2;

pub struct RedactedRealizedItemV2<'a>(pub &'a ContextRealizedItemV2);

impl fmt::Debug for RedactedRealizedItemV2<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextRealizedItemV2")
            .field("item_id", &self.0.item_id)
            .field("role", &self.0.role)
            .field("content_bytes", &self.0.content.len())
            .field("content_digest", &Digest32::of_bytes(&self.0.content))
            .finish()
    }
}

pub struct RedactedSerializedContextV2<'a>(pub &'a SerializedContextV2);

impl fmt::Debug for RedactedSerializedContextV2<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SerializedContextV2")
            .field("payload_bytes", &self.0.payload().len())
            .field("payload_digest", &self.0.receipt().payload_digest())
            .field("serialized_token_count", &self.0.receipt().serialized_token_count())
            .field("receipt_digest", &self.0.receipt().receipt_digest())
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::StableId;

    use crate::ContextRealizedItemV2;
    use crate::ContextRoleV2;

    use super::RedactedRealizedItemV2;

    #[test]
    fn realized_item_debug_wrapper_never_prints_payload() {
        let item = ContextRealizedItemV2 {
            item_id: StableId::new("redacted-item".to_owned())
                .unwrap_or_else(|error| panic!("id: {error:?}")),
            role: ContextRoleV2::TrustedInstruction,
            content: b"top secret prompt bytes".to_vec(),
        };
        let rendered = format!("{:?}", RedactedRealizedItemV2(&item));
        assert!(!rendered.contains("top secret prompt bytes"));
        assert!(rendered.contains("content_digest"));
    }
}
