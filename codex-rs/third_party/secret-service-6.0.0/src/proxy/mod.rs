pub mod collection;
pub mod item;
pub mod prompt;
pub mod service;

use serde::Deserialize;
use serde::Serialize;
use zbus::OwnedObjectPath;
use zbus::Type;

#[derive(Debug, Serialize, Deserialize, Type)]
pub struct SecretStruct {
    pub(crate) session: OwnedObjectPath,
    pub(crate) parameters: Vec<u8>,
    pub(crate) value: Vec<u8>,
    pub(crate) content_type: String,
}
