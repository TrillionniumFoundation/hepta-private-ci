//! Matrix plain-text compatibility. Presentation metadata is never authority.
use codex_app_server_protocol::UserInput;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_store::InboxRecord;
use serde::Deserialize;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum InputRejection {
    EventType,
    Malformed,
    MessageType,
    EmptyBody,
    Relation,
}

#[derive(Deserialize)]
struct TextMessageContent {
    msgtype: String,
    body: String,
    // Unknown top-level presentation/extension fields are ignored, not copied
    // into Agent input. Known critical fields retain typed/duplicate checks.
    #[serde(default, rename = "m.mentions")]
    _mentions: TextMessageMentions,
    #[serde(default, rename = "m.relates_to")]
    relation: Option<Relation>,
}

#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct TextMessageMentions {
    #[serde(default, rename = "user_ids")]
    _user_ids: Vec<MatrixUserId>,
    #[serde(default, rename = "room")]
    _room: bool,
}

#[derive(Deserialize)]
struct Relation {
    #[serde(default)]
    rel_type: Option<String>,
}

pub(super) fn supported_text_input(inbox: &InboxRecord) -> Result<Vec<UserInput>, InputRejection> {
    if inbox.event_type != "m.room.message" {
        return Err(InputRejection::EventType);
    }
    let content: TextMessageContent =
        serde_json::from_slice(&inbox.payload).map_err(|_| InputRejection::Malformed)?;
    if content.msgtype != "m.text" {
        return Err(InputRejection::MessageType);
    }
    if content.body.trim().is_empty() {
        return Err(InputRejection::EmptyBody);
    }
    // A replacement/annotation is not a new user command. Plain replies and
    // thread messages keep their unmodified plain-text body; no HTML executes.
    if content
        .relation
        .as_ref()
        .and_then(|r| r.rel_type.as_deref())
        .is_some_and(|kind| kind != "m.thread")
    {
        return Err(InputRejection::Relation);
    }
    Ok(vec![UserInput::Text {
        text: content.body,
        text_elements: Vec::new(),
    }])
}
