//! Safe WinRT projection. Notification identity is installed out of band.
use windows::Data::Xml::Dom::XmlDocument;
use windows::UI::Notifications::ToastNotification;
use windows::UI::Notifications::ToastNotificationManager;
use windows::core::HSTRING;

use crate::error::ShellError;

pub(super) fn send(title: &str, body: &str, _nonce: &str) -> Result<(), ShellError> {
    if !super::super::notification_supported() {
        return Err(ShellError::Platform(
            "Windows notification identity is not registered for Trillionnium.Hepta.Native".into(),
        ));
    }
    send_toast(title, body)
        .map_err(|error| ShellError::Platform(format!("native WinRT notification: {error}")))
}

fn send_toast(title: &str, body: &str) -> windows::core::Result<()> {
    // The safe WinRT factory projection initializes an apartment-agnostic fresh
    // helper process. No COM object crosses a thread or process boundary.
    let document = XmlDocument::new()?;
    document.LoadXml(&HSTRING::from("<toast><visual><binding template=\"ToastGeneric\"><text/><text/></binding></visual></toast>"))?;
    let nodes = document.GetElementsByTagName(&HSTRING::from("text"))?;
    for (index, text) in [title, body].into_iter().enumerate() {
        // Literal text nodes avoid injecting untrusted markup into toast XML.
        let node = nodes.Item(index as u32)?;
        let value = document.CreateTextNode(&HSTRING::from(text))?;
        node.AppendChild(&value)?;
    }
    let toast = ToastNotification::CreateToastNotification(&document)?;
    let notifier = ToastNotificationManager::CreateToastNotifierWithId(&HSTRING::from(
        super::super::WINDOWS_AUMID,
    ))?;
    notifier.Show(&toast)
}
