use schemars::JsonSchema;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use ts_rs::TS;

use crate::models::ImageDetail;

/// Conservative cap so one user message cannot monopolize a large context window.
pub const MAX_USER_INPUT_TEXT_CHARS: usize = 1 << 20;

const USER_INPUT_PAYLOAD_DIGEST_DOMAIN: &[u8] = b"hepta.queue.user-input:v1\0";

/// Return the versioned canonical SHA-256 binding for ordered user input.
///
/// This is shared by the durable legacy event writer and queue reconciliation
/// so a client message id never joins content that differs only because two
/// JSON serializers chose different object-key ordering or whitespace.
pub fn user_input_payload_sha256(content: &[UserInput]) -> Result<String, serde_json::Error> {
    let value = serde_json::to_value(content)?;
    let mut canonical = Vec::new();
    append_canonical_json(&value, &mut canonical)?;
    let mut hasher = Sha256::new();
    hasher.update(USER_INPUT_PAYLOAD_DIGEST_DOMAIN);
    hasher.update(canonical);
    Ok(format!("{:x}", hasher.finalize()))
}

fn append_canonical_json(
    value: &serde_json::Value,
    output: &mut Vec<u8>,
) -> Result<(), serde_json::Error> {
    match value {
        serde_json::Value::Null => output.extend_from_slice(b"null"),
        serde_json::Value::Bool(value) => {
            output.extend_from_slice(if *value { b"true" } else { b"false" })
        }
        serde_json::Value::Number(value) => output.extend_from_slice(value.to_string().as_bytes()),
        serde_json::Value::String(value) => serde_json::to_writer(output, value)?,
        serde_json::Value::Array(values) => {
            output.push(b'[');
            for (index, value) in values.iter().enumerate() {
                if index != 0 {
                    output.push(b',');
                }
                append_canonical_json(value, output)?;
            }
            output.push(b']');
        }
        serde_json::Value::Object(values) => {
            output.push(b'{');
            let mut keys = values.keys().collect::<Vec<_>>();
            keys.sort_unstable();
            for (index, key) in keys.into_iter().enumerate() {
                if index != 0 {
                    output.push(b',');
                }
                serde_json::to_writer(&mut *output, key)?;
                output.push(b':');
                append_canonical_json(&values[key], output)?;
            }
            output.push(b'}');
        }
    }
    Ok(())
}

/// User input
#[non_exhaustive]
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, TS, JsonSchema)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum UserInput {
    Text {
        text: String,
        /// UI-defined spans within `text` that should be treated as special elements.
        /// These are byte ranges into the UTF-8 `text` buffer and are used to render
        /// or persist rich input markers (e.g., image placeholders) across history
        /// and resume without mutating the literal text.
        #[serde(default)]
        text_elements: Vec<TextElement>,
    },
    /// Pre‑encoded data: URI image.
    Image {
        image_url: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        #[ts(optional)]
        detail: Option<ImageDetail>,
    },
    /// Local image path provided by the user.  This will be converted to an
    /// `Image` variant (base64 data URL) during request serialization.
    LocalImage {
        path: std::path::PathBuf,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        #[ts(optional)]
        detail: Option<ImageDetail>,
    },
    /// Pre-encoded audio data URI forwarded to the Responses API.
    Audio { audio_url: String },
    /// Local audio path converted to an `Audio` data URI during request serialization.
    LocalAudio { path: std::path::PathBuf },

    /// Skill selected by the user (name + path to SKILL.md).
    Skill {
        name: String,
        path: std::path::PathBuf,
    },
    /// Explicit structured mention selected by the user.
    ///
    /// `path` identifies the exact mention target, for example
    /// `app://<connector-id>` or `plugin://<plugin-name>@<marketplace-name>`.
    Mention { name: String, path: String },
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, TS, JsonSchema)]
pub struct TextElement {
    /// Byte range in the parent `text` buffer that this element occupies.
    pub byte_range: ByteRange,
    /// Optional human-readable placeholder for the element, displayed in the UI.
    placeholder: Option<String>,
}

impl TextElement {
    pub fn new(byte_range: ByteRange, placeholder: Option<String>) -> Self {
        Self {
            byte_range,
            placeholder,
        }
    }

    /// Returns a copy of this element with a remapped byte range.
    ///
    /// The placeholder is preserved as-is; callers must ensure the new range
    /// still refers to the same logical element (and same placeholder)
    /// within the new text.
    pub fn map_range<F>(&self, map: F) -> Self
    where
        F: FnOnce(ByteRange) -> ByteRange,
    {
        Self {
            byte_range: map(self.byte_range),
            placeholder: self.placeholder.clone(),
        }
    }

    pub fn set_placeholder(&mut self, placeholder: Option<String>) {
        self.placeholder = placeholder;
    }

    /// Returns the stored placeholder without falling back to the text buffer.
    ///
    /// This must only be used inside `From<TextElement>` implementations on equivalent
    /// protocol types where the source text is unavailable. Prefer `placeholder(text)`
    /// everywhere else.
    #[doc(hidden)]
    pub fn _placeholder_for_conversion_only(&self) -> Option<&str> {
        self.placeholder.as_deref()
    }

    pub fn placeholder<'a>(&'a self, text: &'a str) -> Option<&'a str> {
        self.placeholder
            .as_deref()
            .or_else(|| text.get(self.byte_range.start..self.byte_range.end))
    }
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq, TS, JsonSchema)]
pub struct ByteRange {
    /// Start byte offset (inclusive) within the UTF-8 text buffer.
    pub start: usize,
    /// End byte offset (exclusive) within the UTF-8 text buffer.
    pub end: usize,
}

impl From<std::ops::Range<usize>> for ByteRange {
    fn from(range: std::ops::Range<usize>) -> Self {
        Self {
            start: range.start,
            end: range.end,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::UserInput;
    use super::user_input_payload_sha256;

    #[test]
    fn user_input_payload_digest_is_stable_and_versioned() {
        let content = [UserInput::Text {
            text: "hello".to_string(),
            text_elements: Vec::new(),
        }];

        assert_eq!(
            user_input_payload_sha256(&content).expect("digest user input"),
            "2364648ff389fdc0388dc3dfa5968c8c6a603e8f140f3cee2a0d30db8c234c28"
        );
    }

    #[test]
    fn user_input_payload_digest_binds_item_boundaries_and_order() {
        let one_item = [UserInput::Text {
            text: "hello".to_string(),
            text_elements: Vec::new(),
        }];
        let split_items = [
            UserInput::Text {
                text: "he".to_string(),
                text_elements: Vec::new(),
            },
            UserInput::Text {
                text: "llo".to_string(),
                text_elements: Vec::new(),
            },
        ];
        let reversed_items = [split_items[1].clone(), split_items[0].clone()];

        let one_digest = user_input_payload_sha256(&one_item).expect("digest one item");
        let split_digest = user_input_payload_sha256(&split_items).expect("digest split items");
        let reversed_digest =
            user_input_payload_sha256(&reversed_items).expect("digest reversed items");
        assert_ne!(one_digest, split_digest);
        assert_ne!(split_digest, reversed_digest);
    }
}
