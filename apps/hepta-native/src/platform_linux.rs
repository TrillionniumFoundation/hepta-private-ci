//! Native desktop notification transport. No shell, interpreter, or path launcher.
use std::collections::HashMap;
use std::future::Future;
use std::time::Duration;

use async_io::Timer;
use futures_lite::future;
use serde::Serialize;
use serde::de::DeserializeOwned;
use zbus::Connection;
use zbus::zvariant::DynamicType;
use zbus::zvariant::Type;
use zbus::zvariant::Value;

use crate::error::ShellError;

const DESTINATION: &str = "org.freedesktop.Notifications";
const OBJECT_PATH: &str = "/org/freedesktop/Notifications";

pub(super) fn notification_supported() -> bool {
    future::block_on(future::race(
        async {
            let connection = crate::native_portal::session_connection().await.ok()?;
            let owner = crate::native_portal::service_owner(&connection, DESTINATION)
                .await
                .ok()?;
            let _: (String, String, String, String) =
                notification_call(&connection, &owner, "GetServerInformation", &())
                    .await
                    .ok()?;
            Some(())
        },
        async {
            Timer::after(Duration::from_secs(3)).await;
            None
        },
    ))
    .is_some()
}

pub(super) fn send_notification(title: &str, body: &str) -> Result<(), ShellError> {
    future::block_on(send_on(
        crate::native_portal::session_connection(),
        title,
        body,
    ))
}

async fn send_on(
    connect: impl Future<Output = zbus::Result<Connection>>,
    title: &str,
    body: &str,
) -> Result<(), ShellError> {
    future::race(
        async {
            let connection = connect.await.map_err(notification_error)?;
            let owner = crate::native_portal::service_owner(&connection, DESTINATION).await?;
            // The desktop protocol permits markup in body text. Escape it so
            // untrusted notification content remains literal presentation.
            let capabilities: Vec<String> =
                notification_call(&connection, &owner, "GetCapabilities", &()).await?;
            let body = if capabilities.iter().any(|value| value == "body-markup") {
                body.replace('&', "&amp;")
                    .replace('<', "&lt;")
                    .replace('>', "&gt;")
            } else {
                body.to_owned()
            };
            let hints: HashMap<&str, Value<'_>> =
                HashMap::from([("desktop-entry", Value::from("hepta-native"))]);
            let _: u32 = notification_call(
                &connection,
                &owner,
                "Notify",
                &(
                    "Hepta Native",
                    0_u32,
                    "",
                    title,
                    body,
                    Vec::<&str>::new(),
                    hints,
                    -1_i32,
                ),
            )
            .await?;
            // A notification ID proves method acceptance, not delivery or that
            // a person saw it. The platform owner keeps the effect indeterminate.
            Ok(())
        },
        async {
            Timer::after(super::NOTIFICATION_TIMEOUT).await;
            Err(ShellError::Platform(
                "notification deadline exceeded; effect remains indeterminate".to_owned(),
            ))
        },
    )
    .await
}

async fn notification_call<B: Serialize + DynamicType, R: DeserializeOwned + Type>(
    connection: &Connection,
    owner: &str,
    method: &str,
    body: &B,
) -> Result<R, ShellError> {
    let reply = connection
        .call_method(Some(owner), OBJECT_PATH, Some(DESTINATION), method, body)
        .await
        .map_err(notification_error)?;
    if reply.header().sender().map(|sender| sender.as_str()) != Some(owner)
        || reply.body().len() > 64 * 1024
    {
        return Err(ShellError::Security(
            "notification response sender or size is invalid".into(),
        ));
    }
    reply.body().deserialize().map_err(notification_error)
}

fn notification_error(error: zbus::Error) -> ShellError {
    ShellError::Platform(format!("native desktop notification: {error}"))
}

#[cfg(test)]
#[path = "platform_linux_tests.rs"]
mod tests;
