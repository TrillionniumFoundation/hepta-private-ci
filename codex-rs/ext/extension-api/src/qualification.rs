//! Host-provided durable admission identity for qualification-only extensions.

/// The durable client/input identity available at a turn boundary.
///
/// This is deliberately a small, authority-free value object.  Core derives
/// it from the accepted user input; extensions may use it to bind local
/// observation records across physical turn/spawn attempts without retaining
/// the raw prompt as an authority artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationTurnAdmissionIdentity {
    pub thread_scope_key: String,
    pub client_user_message_id: String,
    pub payload_sha256: String,
}

impl QualificationTurnAdmissionIdentity {
    pub fn new(
        thread_scope_key: impl Into<String>,
        client_user_message_id: impl Into<String>,
        payload_sha256: impl Into<String>,
    ) -> Option<Self> {
        let value = Self {
            thread_scope_key: thread_scope_key.into(),
            client_user_message_id: client_user_message_id.into(),
            payload_sha256: payload_sha256.into(),
        };
        if value.thread_scope_key.trim().is_empty()
            || value.thread_scope_key.len() > 512
            || value.thread_scope_key.as_bytes().contains(&0)
            || value.client_user_message_id.trim().is_empty()
            || value.client_user_message_id.len() > 512
            || value.client_user_message_id.as_bytes().contains(&0)
            || value.payload_sha256.len() != 64
            || !value
                .payload_sha256
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return None;
        }
        Some(value)
    }
}
