//! Native D-Bus adapters. Request observation is subscribed before dispatch.
use std::collections::HashMap;
use std::future::Future;
use std::os::fd::AsFd;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use futures_lite::StreamExt as _;
use zbus::Connection;
use zbus::MatchRule;
use zbus::MessageStream;
use zbus::message::Type;
use zbus::zvariant::Fd;
use zbus::zvariant::OwnedObjectPath;
use zbus::zvariant::OwnedValue;
use zbus::zvariant::Value;

use crate::error::ShellError;

const DESTINATION: &str = "org.freedesktop.portal.Desktop";
const DESKTOP_PATH: &str = "/org/freedesktop/portal/desktop";
const REQUEST_INTERFACE: &str = "org.freedesktop.portal.Request";
const MAX_RESPONSE_BYTES: usize = 32 * 1024;

fn unavailable(_error: impl std::fmt::Display) -> ShellError {
    ShellError::Platform(
        "native desktop service is unavailable or returned an invalid response".into(),
    )
}

async fn bounded<T>(
    future: impl Future<Output = Result<T, ShellError>>,
    deadline: Instant,
) -> Result<T, ShellError> {
    futures_lite::future::or(future, async move {
        async_io::Timer::at(deadline).await;
        Err(ShellError::Platform(
            "native portal observation deadline exceeded".into(),
        ))
    })
    .await
}

fn validate_session_address(address: Option<&str>) -> Result<(), ShellError> {
    if let Some(address) = address
        && (address.is_empty()
            || !address
                .split(';')
                .all(|address| address.starts_with("unix:")))
    {
        return Err(ShellError::Platform(
            "native desktop requires a local Unix session bus".into(),
        ));
    }
    Ok(())
}

async fn session() -> Result<Connection, ShellError> {
    let configured = std::env::var("DBUS_SESSION_BUS_ADDRESS")
        .map(Some)
        .or_else(|error| match error {
            std::env::VarError::NotPresent => Ok(None),
            std::env::VarError::NotUnicode(_) => Err(unavailable(error)),
        })?;
    validate_session_address(configured.as_deref())?;
    Connection::session().await.map_err(unavailable)
}

async fn portal_owner(connection: &Connection) -> Result<String, ShellError> {
    // Ping permits ordinary D-Bus activation without launching a dialog/effect.
    connection
        .call_method(
            Some(DESTINATION),
            DESKTOP_PATH,
            Some("org.freedesktop.DBus.Peer"),
            "Ping",
            &(),
        )
        .await
        .map_err(unavailable)?;
    let bus = zbus::fdo::DBusProxy::new(connection)
        .await
        .map_err(unavailable)?;
    Ok(bus
        .get_name_owner(DESTINATION.try_into().map_err(unavailable)?)
        .await
        .map_err(unavailable)?
        .to_string())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Action {
    Picker,
    Open,
    Reveal,
}

pub(super) fn run(mode: &str) -> Result<(), ShellError> {
    futures_lite::future::block_on(async {
        let deadline = Instant::now()
            + if mode == "portal-probe" {
                Duration::from_secs(2)
            } else {
                Duration::from_secs(30)
            };
        let connection = bounded(session(), deadline).await?;
        let owner = bounded(portal_owner(&connection), deadline).await?;
        if mode == "portal-probe" {
            return Ok(());
        }
        let action = match mode {
            "open-resource" => Action::Open,
            "reveal-resource" => Action::Reveal,
            _ => {
                return Err(ShellError::InvalidInput(
                    "unknown portal resource mode".into(),
                ));
            }
        };
        let stdin = std::io::stdin();
        let retained =
            std::fs::File::from(stdin.as_fd().try_clone_to_owned().map_err(unavailable)?);
        request(&connection, &owner, action, Some(&retained), deadline)
            .await
            .map(|_| ())
    })
}

pub(super) fn select_file() -> Result<Option<PathBuf>, ShellError> {
    futures_lite::future::block_on(async {
        let deadline = Instant::now() + Duration::from_secs(120);
        let connection = bounded(session(), deadline).await?;
        let owner = bounded(portal_owner(&connection), deadline).await?;
        request(
            &connection,
            &owner,
            Action::Picker,
            /*resource*/ None,
            deadline,
        )
        .await
    })
}

async fn request(
    connection: &Connection,
    owner: &str,
    action: Action,
    resource: Option<&std::fs::File>,
    deadline: Instant,
) -> Result<Option<PathBuf>, ShellError> {
    let sender = connection
        .unique_name()
        .ok_or_else(|| unavailable("missing sender"))?
        .as_str()
        .trim_start_matches(':')
        .replace('.', "_");
    let prefix = format!("/org/freedesktop/portal/desktop/request/{sender}/");
    let mut random = [0_u8; 16];
    getrandom::fill(&mut random).map_err(unavailable)?;
    let token = format!(
        "hepta_{}",
        random
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    );
    let expected_path = format!("{prefix}{token}");
    let rule = MatchRule::builder()
        .msg_type(Type::Signal)
        .sender(owner)
        .map_err(unavailable)?
        .interface(REQUEST_INTERFACE)
        .map_err(unavailable)?
        .member("Response")
        .map_err(unavailable)?
        .path_namespace(prefix.trim_end_matches('/'))
        .map_err(unavailable)?
        .build();
    let mut responses = bounded(
        async {
            MessageStream::for_match_rule(rule, connection, Some(8))
                .await
                .map_err(unavailable)
        },
        deadline,
    )
    .await?;
    let mut options = HashMap::<&str, Value<'_>>::new();
    options.insert("handle_token", Value::from(token.as_str()));
    let mut handle = expected_path.clone();
    let result = bounded(
        async {
            let reply = if action == Action::Picker {
                options.insert("multiple", Value::from(false));
                options.insert("directory", Value::from(false));
                options.insert("modal", Value::from(true));
                connection
                    .call_method(
                        Some(owner),
                        DESKTOP_PATH,
                        Some("org.freedesktop.portal.FileChooser"),
                        "OpenFile",
                        &("", "Select a Hepta input file", options),
                    )
                    .await
                    .map_err(unavailable)?
            } else {
                options.insert("writable", Value::from(false));
                options.insert("ask", Value::from(false));
                let retained = resource
                    .ok_or_else(|| unavailable("verified resource descriptor is missing"))?;
                let metadata = retained.metadata().map_err(unavailable)?;
                if !metadata.is_file() && !metadata.is_dir() {
                    return Err(unavailable("resource is not a file or directory"));
                }
                let method = if action == Action::Open {
                    "OpenFile"
                } else {
                    "OpenDirectory"
                };
                // Pass the verified FD via SCM_RIGHTS. No resource pathname exists here.
                connection
                    .call_method(
                        Some(owner),
                        DESKTOP_PATH,
                        Some("org.freedesktop.portal.OpenURI"),
                        method,
                        &("", Fd::from(retained.as_fd()), options),
                    )
                    .await
                    .map_err(unavailable)?
            };
            if !reply.body().data().fds().is_empty() || reply.body().len() > 4096 {
                return Err(unavailable("oversized request handle"));
            }
            let (returned,): (OwnedObjectPath,) =
                reply.body().deserialize().map_err(unavailable)?;
            if !returned.as_str().starts_with(&prefix) || returned.as_str().len() > 1024 {
                return Err(unavailable("foreign request handle"));
            }
            handle = returned.to_string();
            // One helper owns one request. Extra signals cannot monopolize its loop.
            for _ in 0..16 {
                let message = responses
                    .next()
                    .await
                    .ok_or_else(|| unavailable("response stream closed"))?
                    .map_err(unavailable)?;
                if message.header().sender().map(|name| name.as_str()) != Some(owner) {
                    continue;
                }
                let header = message.header();
                let path = header.path().map(|path| path.as_str()).unwrap_or_default();
                if path != handle && path != expected_path {
                    continue;
                }
                if !message.body().data().fds().is_empty()
                    || message.body().len() > MAX_RESPONSE_BYTES
                {
                    return Err(unavailable("oversized response"));
                }
                let (code, results): (u32, HashMap<String, OwnedValue>) =
                    message.body().deserialize().map_err(unavailable)?;
                return decode_response(action, code, results);
            }
            Err(unavailable("unexpected request signals"))
        },
        deadline,
    )
    .await;
    if result.is_err() {
        // The original observation budget is never restarted. Cleanup has its
        // own existing five-second bound, inside the parent's reap margin.
        let _ = bounded(
            async {
                connection
                    .call_method(
                        Some(owner),
                        handle.as_str(),
                        Some(REQUEST_INTERFACE),
                        "Close",
                        &(),
                    )
                    .await
                    .map_err(unavailable)?;
                Ok(())
            },
            Instant::now() + Duration::from_secs(5),
        )
        .await;
    }
    result
}

fn decode_response(
    action: Action,
    code: u32,
    mut results: HashMap<String, OwnedValue>,
) -> Result<Option<PathBuf>, ShellError> {
    if code == 1 && action == Action::Picker {
        return Ok(None);
    }
    if code != 0 {
        return Err(ShellError::Platform(
            "native portal request was cancelled or rejected".into(),
        ));
    }
    if action != Action::Picker {
        return Ok(None);
    }
    let uris = Vec::<String>::try_from(
        results
            .remove("uris")
            .ok_or_else(|| unavailable("missing URI"))?,
    )
    .map_err(unavailable)?;
    if uris.len() != 1 {
        return Err(unavailable("exactly one selection required"));
    }
    decode_uri(&uris[0]).map(Some)
}

fn decode_uri(uri: &str) -> Result<PathBuf, ShellError> {
    if uri.len() > crate::model::MAX_NATIVE_PATH_BYTES {
        return Err(unavailable("oversized URI"));
    }
    // Preserve the exact selected pathname; URL normalizers collapse dot
    // segments before the independent resource owner can reject them.
    let path = if let Some(local) = uri.strip_prefix("file://") {
        let slash = local
            .find('/')
            .ok_or_else(|| unavailable("missing file path"))?;
        if !matches!(&local[..slash], "" | "localhost") {
            return Err(unavailable("remote file authority"));
        }
        &local[slash..]
    } else {
        uri.strip_prefix("file:")
            .ok_or_else(|| unavailable("not a file URI"))?
    };
    if !path.starts_with('/') || path.contains(['?', '#']) {
        return Err(unavailable("ambiguous file URI"));
    }
    let mut decoded = Vec::with_capacity(path.len());
    let bytes = path.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            let digits = bytes
                .get(index + 1..index + 3)
                .ok_or_else(|| unavailable("truncated percent encoding"))?;
            let high = char::from(digits[0])
                .to_digit(16)
                .ok_or_else(|| unavailable("invalid percent encoding"))?;
            let low = char::from(digits[1])
                .to_digit(16)
                .ok_or_else(|| unavailable("invalid percent encoding"))?;
            decoded.push((high * 16 + low) as u8);
            index += 3;
        } else {
            decoded.push(bytes[index]);
            index += 1;
        }
    }
    let path = PathBuf::from(String::from_utf8(decoded).map_err(unavailable)?);
    let text = path.to_str().ok_or_else(|| unavailable("non UTF-8 path"))?;
    if !path.is_absolute() || text.contains(['\0', '\r', '\n']) {
        return Err(unavailable("ambiguous local path"));
    }
    Ok(path)
}

pub(super) fn notify(title: &str, body: &str) -> Result<(), ShellError> {
    futures_lite::future::block_on(bounded(
        async {
            let connection = session().await?;
            let escaped = body
                .replace('&', "&amp;")
                .replace('<', "&lt;")
                .replace('>', "&gt;");
            let hints = HashMap::<&str, Value<'_>>::new();
            let reply = connection
                .call_method(
                    Some("org.freedesktop.Notifications"),
                    "/org/freedesktop/Notifications",
                    Some("org.freedesktop.Notifications"),
                    "Notify",
                    &(
                        "Hepta Native",
                        0_u32,
                        "",
                        title,
                        escaped.as_str(),
                        Vec::<String>::new(),
                        hints,
                        -1_i32,
                    ),
                )
                .await
                .map_err(unavailable)?;
            let _: u32 = reply.body().deserialize().map_err(unavailable)?;
            Ok(())
        },
        Instant::now() + Duration::from_secs(5),
    ))
}

#[cfg(test)]
mod tests;
