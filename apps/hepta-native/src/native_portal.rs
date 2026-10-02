//! Bounded, owner-pinned XDG requests. Results are observations, never grants.
//!
//! The 64 KiB application check is after zbus receives a frame. zbus 5.19's
//! transport ceiling is 128 MiB per raw frame, not a 64 KiB allocation bound.
//! Limit main and matching queue counts; this is not a tighter physical-memory
//! guarantee. There is no supported per-connection raw-frame limit in zbus.
use std::collections::HashMap;
use std::future::Future;
use std::time::Duration;

use futures_lite::StreamExt as _;
use serde::Serialize;
use zbus::Connection;
use zbus::MatchRule;
use zbus::MessageStream;
use zbus::zvariant::DynamicType;
use zbus::zvariant::OwnedObjectPath;
use zbus::zvariant::OwnedValue;

use crate::error::ShellError;

const DESTINATION: &str = "org.freedesktop.portal.Desktop";
const DESKTOP_PATH: &str = "/org/freedesktop/portal/desktop";
const REQUEST_INTERFACE: &str = "org.freedesktop.portal.Request";
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
const CLOSE_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug)]
pub(crate) enum PortalResponse {
    Completed(HashMap<String, OwnedValue>),
    Cancelled,
}

pub(crate) async fn session_connection() -> zbus::Result<Connection> {
    zbus::connection::Builder::session()?
        .max_queued(4)
        .build()
        .await
}

pub(crate) fn request_token() -> Result<String, ShellError> {
    let mut random = [0_u8; 16];
    getrandom::fill(&mut random)
        .map_err(|error| ShellError::Platform(format!("portal request identity: {error}")))?;
    let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
    Ok(format!("hepta_native_{suffix}"))
}

fn portal_error(error: impl std::fmt::Display) -> ShellError {
    ShellError::Platform(format!("XDG portal: {error}"))
}

async fn bounded<T>(
    work: impl Future<Output = Result<T, ShellError>>,
    maximum: Duration,
) -> Result<T, ShellError> {
    futures_lite::future::race(work, async {
        async_io::Timer::after(maximum).await;
        Err(ShellError::Platform(
            "XDG portal observation deadline exceeded".into(),
        ))
    })
    .await
}

fn verified_reply(
    reply: zbus::Result<zbus::Message>,
    owner: &str,
) -> Result<zbus::Message, ShellError> {
    let reply = reply.map_err(portal_error)?;
    if reply
        .header()
        .sender()
        .is_none_or(|sender| sender.as_str() != owner)
        || reply.body().len() > MAX_RESPONSE_BYTES
    {
        return Err(portal_error("method reply has invalid owner or byte bound"));
    }
    Ok(reply)
}

pub(crate) async fn service_owner(
    connection: &Connection,
    destination: &str,
) -> Result<String, ShellError> {
    const DBUS: &str = "org.freedesktop.DBus";
    const PATH: &str = "/org/freedesktop/DBus";
    let initial = connection
        .call_method(
            Some(DBUS),
            PATH,
            Some(DBUS),
            "GetNameOwner",
            &(destination,),
        )
        .await;
    let reply = match initial {
        Err(zbus::Error::MethodError(name, _, reply))
            if name.as_str() == "org.freedesktop.DBus.Error.NameHasNoOwner"
                && reply
                    .header()
                    .sender()
                    .is_some_and(|sender| sender.as_str() == DBUS) =>
        {
            let started = verified_reply(
                connection
                    .call_method(
                        Some(DBUS),
                        PATH,
                        Some(DBUS),
                        "StartServiceByName",
                        &(destination, 0_u32),
                    )
                    .await,
                DBUS,
            )?;
            let status: u32 = started.body().deserialize().map_err(portal_error)?;
            if !matches!(status, 1 | 2) {
                return Err(portal_error("invalid service activation response"));
            }
            verified_reply(
                connection
                    .call_method(
                        Some(DBUS),
                        PATH,
                        Some(DBUS),
                        "GetNameOwner",
                        &(destination,),
                    )
                    .await,
                DBUS,
            )?
        }
        reply => verified_reply(reply, DBUS)?,
    };
    let owner: zbus::names::OwnedUniqueName = reply.body().deserialize().map_err(portal_error)?;
    Ok(owner.to_string())
}

pub(crate) async fn probe(interface: &str, minimum_version: u32) -> Result<(), ShellError> {
    bounded(
        async {
            let connection = session_connection().await.map_err(portal_error)?;
            let owner = service_owner(&connection, DESTINATION).await?;
            let reply = verified_reply(
                connection
                    .call_method(
                        Some(owner.as_str()),
                        DESKTOP_PATH,
                        Some("org.freedesktop.DBus.Properties"),
                        "Get",
                        &(interface, "version"),
                    )
                    .await,
                &owner,
            )?;
            let version: OwnedValue = reply.body().deserialize().map_err(portal_error)?;
            let version = u32::try_from(version).map_err(portal_error)?;
            if version < minimum_version {
                return Err(portal_error("required interface version is unavailable"));
            }
            Ok(())
        },
        Duration::from_secs(3),
    )
    .await
}

pub(crate) async fn request<B: Serialize + DynamicType>(
    interface: &str,
    method: &str,
    body: &B,
    token: &str,
    maximum: Duration,
) -> Result<PortalResponse, ShellError> {
    request_on(
        session_connection(),
        interface,
        method,
        body,
        token,
        maximum,
    )
    .await
}

async fn request_on<B: Serialize + DynamicType>(
    connect: impl Future<Output = zbus::Result<Connection>>,
    interface: &str,
    method: &str,
    body: &B,
    token: &str,
    maximum: Duration,
) -> Result<PortalResponse, ShellError> {
    let mut admitted = None;
    // Connection, activation, match installation, method dispatch and response
    // share one budget. A timeout drops the pending future before cleanup.
    let result = bounded(
        async {
            let connection = connect.await.map_err(portal_error)?;
            let owner = service_owner(&connection, DESTINATION).await?;
            let sender = connection
                .unique_name()
                .ok_or_else(|| portal_error("session bus has no unique client identity"))?;
            let sender = sender.as_str().trim_start_matches(':').replace('.', "_");
            let path = format!("{DESKTOP_PATH}/request/{sender}/{token}");
            let rule = MatchRule::builder()
                .msg_type(zbus::message::Type::Signal)
                .sender(owner.as_str())
                .map_err(portal_error)?
                .path(path.as_str())
                .map_err(portal_error)?
                .interface(REQUEST_INTERFACE)
                .map_err(portal_error)?
                .member("Response")
                .map_err(portal_error)?
                .build();
            let mut responses = MessageStream::for_match_rule(rule, &connection, Some(4))
                .await
                .map_err(portal_error)?;
            admitted = Some((connection.clone(), owner.clone(), path.clone()));
            let reply = verified_reply(
                connection
                    .call_method(
                        Some(owner.as_str()),
                        DESKTOP_PATH,
                        Some(interface),
                        method,
                        body,
                    )
                    .await,
                &owner,
            )?;
            let returned: OwnedObjectPath = reply.body().deserialize().map_err(portal_error)?;
            if returned.as_str() != path {
                // A legacy portal may ignore handle_token. Reject its unobserved
                // result, but close its returned request when it belongs to this
                // client's namespace; never address another client's request.
                let namespace = format!("{DESKTOP_PATH}/request/{sender}/");
                if returned.as_str().starts_with(&namespace)
                    && let Some((_, _, cleanup_path)) = admitted.as_mut()
                {
                    *cleanup_path = returned.to_string();
                }
                return Err(portal_error(
                    "request handle differs from the pre-subscribed identity",
                ));
            }
            let message = responses
                .next()
                .await
                .ok_or_else(|| portal_error("response stream closed"))?
                .map_err(portal_error)?;
            let body = message.body();
            if body.len() > MAX_RESPONSE_BYTES {
                return Err(portal_error("response exceeds byte bound"));
            }
            let (response, results): (u32, HashMap<String, OwnedValue>) =
                body.deserialize().map_err(portal_error)?;
            match response {
                0 => Ok(PortalResponse::Completed(results)),
                1 => Ok(PortalResponse::Cancelled),
                _ => Err(portal_error("request was rejected")),
            }
        },
        maximum,
    )
    .await;
    if let Some((connection, owner, path)) = admitted {
        // Closing an observation never proves that an external effect did not
        // occur. The runtime keeps its existing Indeterminate semantics.
        if result.is_err() {
            let _ = bounded(
                async {
                    connection
                        .call_method(
                            Some(owner.as_str()),
                            path.as_str(),
                            Some(REQUEST_INTERFACE),
                            "Close",
                            &(),
                        )
                        .await
                        .map_err(portal_error)?;
                    Ok(())
                },
                CLOSE_TIMEOUT,
            )
            .await;
        }
        bounded(
            async { connection.close().await.map_err(portal_error) },
            CLOSE_TIMEOUT,
        )
        .await?;
    }
    result
}

#[cfg(test)]
#[path = "native_portal_tests.rs"]
mod tests;
