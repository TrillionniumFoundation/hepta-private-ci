//! One source adopted by the original App before its first event is dispatched.
//! There is deliberately no default ChatWorkspace in an unadopted App.

#[cfg(feature = "native-presentation")]
use crate::native_presentation::OwnedComposition;
use hepta_control_core::chat::ChatWorkspace;

pub(crate) enum ChatSource {
    Standalone(Box<ChatWorkspace>),
    #[cfg(feature = "native-presentation")]
    Embedded(OwnedComposition),
}

#[derive(Default)]
pub(crate) struct ChatSourceSlot {
    source: Option<ChatSource>,
}

impl ChatSourceSlot {
    pub(crate) fn adopt_once(&mut self, source: impl FnOnce() -> ChatSource) -> bool {
        if self.source.is_some() {
            return false;
        }
        self.source = Some(source());
        true
    }

    #[cfg(any(test, target_arch = "wasm32", feature = "ui-fixtures"))]
    pub(crate) fn workspace(&self) -> &ChatWorkspace {
        match self
            .source
            .as_ref()
            .expect("App adopts its ChatSource before dispatch")
        {
            ChatSource::Standalone(workspace) => workspace,
            #[cfg(feature = "native-presentation")]
            ChatSource::Embedded(composition) => composition.inner.workspace(),
        }
    }

    pub(crate) fn workspace_mut(&mut self) -> &mut ChatWorkspace {
        match self
            .source
            .as_mut()
            .expect("App adopts its ChatSource before dispatch")
        {
            ChatSource::Standalone(workspace) => workspace,
            #[cfg(feature = "native-presentation")]
            ChatSource::Embedded(composition) => composition.inner.workspace_mut(),
        }
    }

    #[cfg(feature = "native-presentation")]
    pub(crate) fn composition_mut(&mut self) -> Option<&mut OwnedComposition> {
        match self.source.as_mut() {
            Some(ChatSource::Embedded(composition)) => Some(composition),
            _ => None,
        }
    }
}

#[cfg(test)]
#[path = "chat_source_tests.rs"]
mod tests;
