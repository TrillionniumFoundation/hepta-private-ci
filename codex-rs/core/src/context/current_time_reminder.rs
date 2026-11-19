use super::ContextualUserFragment;
use codex_protocol::models::ContentItemKind;

pub(crate) struct CurrentTimeReminder {
    current_time: codex_utils_time::Timestamp,
}

impl CurrentTimeReminder {
    pub(crate) fn new(current_time: codex_utils_time::Timestamp) -> Self {
        Self { current_time }
    }

    pub(crate) fn formatted_time(&self) -> String {
        self.current_time
            .format_utc(codex_utils_time::UtcFormat::DateTimeUtc)
    }
}

impl ContextualUserFragment for CurrentTimeReminder {
    fn content_kind(&self) -> ContentItemKind {
        ContentItemKind("current_time.reminder".to_string())
    }

    fn role(&self) -> &'static str {
        "developer"
    }

    fn markers(&self) -> (&'static str, &'static str) {
        Self::type_markers()
    }

    fn type_markers() -> (&'static str, &'static str) {
        ("<current_time_reminder>", "</current_time_reminder>")
    }

    fn body(&self) -> String {
        format!("It is {}.", self.formatted_time())
    }
}
