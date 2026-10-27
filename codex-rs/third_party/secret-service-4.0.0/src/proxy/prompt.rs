//Copyright 2022 secret-service-rs Developers
//
// Licensed under the Apache License, Version 2.0, <LICENSE-APACHE or
// http://apache.org/licenses/LICENSE-2.0> or the MIT license <LICENSE-MIT or
// http://opensource.org/licenses/MIT>, at your option. This file may not be
// copied, modified, or distributed except according to those terms.

//! A dbus proxy for speaking with secret service's `Prompt` Interface.

use zbus::Variant;

/// A dbus proxy for speaking with secret service's `Prompt` Interface.
///
/// This will derive PromptProxy
///
/// Note that `Variant` in the method signatures corresponds to `VARIANT` dbus type.
#[zbus::proxy(
    interface = "org.freedesktop.Secret.Prompt",
    default_service = "org.freedesktop.Secret.Prompt"
)]
pub(crate) trait Prompt {
    fn prompt(&self, window_id: &str) -> zbus::Result<()>;

    fn dismiss(&self) -> zbus::Result<()>;

    #[zbus(signal)]
    fn completed(&self, dismissed: bool, result: Variant<'_>) -> zbus::Result<()>;
}
