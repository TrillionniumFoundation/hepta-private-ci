//! Private desktop intent references. Original App Server owns all chat effects.
use crate::chat_protocol::root::NativeChatRootRequest;
use crate::error::ShellError;
use crate::private_state::PrivateStateRoot;
use serde::Deserialize;
use serde::Serialize;
use std::io::Read as _;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ChatReference {
    pub endpoint_id: String,
    pub request: NativeChatRootRequest,
}
impl ChatReference {
    fn validate(&self) -> Result<(), ShellError> {
        if matches!(self.request, NativeChatRootRequest::Recover { .. }) {
            return Err(ShellError::Security(
                "read-only recovery cannot become a mutation reference".into(),
            ));
        }
        crate::model::validate_stable_id(&self.endpoint_id, "chat endpoint")?;
        self.request
            .validate()
            .map_err(|e| ShellError::State(e.into()))
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Stored {
    schema_version: u32,
    pending: Option<ChatReference>,
    checksum: String,
}

pub(crate) struct ChatReferenceStore {
    root: PrivateStateRoot,
    _lock: std::fs::File,
    pending: Option<ChatReference>,
    poisoned: bool,
}
impl ChatReferenceStore {
    pub fn open(root: PrivateStateRoot) -> Result<Self, ShellError> {
        root.verify()?;
        let path = root.path().join("chat-pending.lock");
        let lock = crate::journal_storage::open_private_file_in(
            &root,
            &path,
            crate::journal_storage::FileAccess::Lock,
            path.exists(),
        )?;
        lock.try_lock()
            .map_err(|_| ShellError::State("another desktop owns chat recovery".into()))?;
        let path = root.path().join("chat-pending.json");
        let pending = if path.exists() {
            let mut bytes = Vec::new();
            crate::journal_storage::open_private_file_in(
                &root,
                &path,
                crate::journal_storage::FileAccess::Read,
                true,
            )?
            .take(70 * 1024 + 1)
            .read_to_end(&mut bytes)?;
            if bytes.len() > 70 * 1024 {
                return Err(ShellError::State(
                    "chat recovery reference exceeds bound".into(),
                ));
            }
            let stored: Stored = serde_json::from_slice(&bytes)?;
            if stored.schema_version != 1 || stored.checksum != checksum(&stored.pending)? {
                return Err(ShellError::Security(
                    "chat recovery checksum differs".into(),
                ));
            }
            if let Some(value) = &stored.pending {
                value.validate()?;
            }
            stored.pending
        } else {
            None
        };
        Ok(Self {
            root,
            _lock: lock,
            pending,
            poisoned: false,
        })
    }
    pub fn pending(&self) -> Option<&ChatReference> {
        self.pending.as_ref()
    }
    pub fn reserve(&mut self, reference: ChatReference) -> Result<(), ShellError> {
        reference.validate()?;
        if self.pending.is_some() || self.poisoned {
            return Err(ShellError::State(
                "inspect the previous chat action before a new one".into(),
            ));
        }
        self.pending = Some(reference);
        self.persist()
    }
    pub fn clear_observed(&mut self) -> Result<(), ShellError> {
        if self.poisoned {
            return Err(ShellError::State(
                "reopen chat recovery after the failed private write".into(),
            ));
        }
        let old = self.pending.take();
        if let Err(error) = self.persist() {
            self.pending = old;
            return Err(error);
        }
        Ok(())
    }
    fn persist(&mut self) -> Result<(), ShellError> {
        let bytes = serde_json::to_vec(&Stored {
            schema_version: 1,
            pending: self.pending.clone(),
            checksum: checksum(&self.pending)?,
        })?;
        if let Err(error) = crate::journal_storage::write_private(
            &self.root,
            &self.root.path().join("chat-pending.json"),
            &bytes,
        ) {
            self.poisoned = true;
            return Err(error);
        }
        Ok(())
    }
}
fn checksum(value: &Option<ChatReference>) -> Result<String, ShellError> {
    let mut bytes = b"hepta.desktop.chat.reference.v1\0".to_vec();
    bytes.extend(serde_json::to_vec(value)?);
    Ok(crate::model::sha256_hex(bytes))
}
