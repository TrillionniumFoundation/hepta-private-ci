//! Safe Rust bindings to the installed application's UserNotifications identity.
use block2::RcBlock;
use objc2::runtime::Bool;
use objc2_foundation::NSBundle;
use objc2_foundation::NSError;
use objc2_foundation::NSString;
use objc2_user_notifications::UNAuthorizationOptions;
use objc2_user_notifications::UNMutableNotificationContent;
use objc2_user_notifications::UNNotificationRequest;
use objc2_user_notifications::UNUserNotificationCenter;

use crate::error::ShellError;

pub(super) fn supported() -> bool {
    NSBundle::mainBundle()
        .bundleIdentifier()
        .is_some_and(|identifier| identifier.to_string() == "org.trillionnium.hepta.native")
}

pub(super) fn send(title: &str, body: &str, nonce: &str) -> Result<(), ShellError> {
    if !supported() {
        return Err(ShellError::Platform(
            "macOS notifications require the installed Hepta Native bundle identity".into(),
        ));
    }
    let center = UNUserNotificationCenter::currentNotificationCenter();
    let (sender, receiver) = std::sync::mpsc::sync_channel(1);
    let authorization = RcBlock::new(move |granted: Bool, error: *mut NSError| {
        let _ = sender.send(granted.as_bool() && error.is_null());
    });
    center.requestAuthorizationWithOptions_completionHandler(
        UNAuthorizationOptions::Alert,
        &authorization,
    );
    if receiver.recv_timeout(super::super::NOTIFICATION_TIMEOUT) != Ok(true) {
        return Err(ShellError::Platform(
            "macOS notification permission was not granted within the adapter deadline".into(),
        ));
    }
    let content = UNMutableNotificationContent::new();
    content.setTitle(&NSString::from_str(title));
    content.setBody(&NSString::from_str(body));
    let request = UNNotificationRequest::requestWithIdentifier_content_trigger(
        &NSString::from_str(nonce),
        &content,
        /*trigger*/ None,
    );
    let (sender, receiver) = std::sync::mpsc::sync_channel(1);
    let completion = RcBlock::new(move |error: *mut NSError| {
        // The pointer remains owned by the framework. No dereference, retention,
        // or cross-thread transfer is needed to observe acceptance/rejection.
        let _ = sender.send(error.is_null());
    });
    center.addNotificationRequest_withCompletionHandler(&request, Some(&completion));
    match receiver.recv_timeout(super::super::NOTIFICATION_TIMEOUT) {
        Ok(true) => Ok(()),
        Ok(false) => Err(ShellError::Platform(
            "macOS rejected the notification request; check notification permission".into(),
        )),
        Err(_) => Err(ShellError::Platform(
            "macOS notification acceptance deadline exceeded".into(),
        )),
    }
}
