//! Browser-origin checks for the shared loopback HTTP boundary.
//! These reject DNS rebinding/cross-origin reads; they are not user authentication.

use std::net::IpAddr;
use std::net::SocketAddr;

#[derive(Eq, PartialEq)]
struct Authority {
    host: String,
    port: u16,
}

fn authority(value: &str) -> Option<Authority> {
    if value.is_empty() || !value.is_ascii() || value.bytes().any(|byte| byte.is_ascii_whitespace())
    {
        return None;
    }
    if value.starts_with('[') {
        let end = value.find(']')?;
        let host = value.get(1..end)?.parse::<std::net::Ipv6Addr>().ok()?;
        let rest = value.get(end + 1..)?;
        let port = if rest.is_empty() {
            80
        } else {
            port(rest.strip_prefix(':')?)?
        };
        return Some(Authority {
            host: host.to_string(),
            port,
        });
    }
    let (host, port) = match value.rsplit_once(':') {
        Some((host, encoded)) => (host, port(encoded)?),
        None => (value, 80),
    };
    let host = if host.eq_ignore_ascii_case("localhost") {
        "localhost".to_owned()
    } else {
        host.parse::<std::net::Ipv4Addr>().ok()?.to_string()
    };
    Some(Authority { host, port })
}

fn port(value: &str) -> Option<u16> {
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    value.parse().ok().filter(|port| *port != 0)
}

pub(crate) fn allowed(request: &[u8], local: SocketAddr) -> bool {
    if !local.ip().is_loopback() {
        return false;
    }
    let Ok(text) = std::str::from_utf8(request) else {
        return false;
    };
    let mut lines = text.split("\r\n");
    let Some(first) = lines.next() else {
        return false;
    };
    let fields = first.split_whitespace().collect::<Vec<_>>();
    if fields.len() != 3 || !matches!(fields[2], "HTTP/1.0" | "HTTP/1.1") {
        return false;
    }
    let mut host = None;
    let mut origin = None;
    for line in lines {
        if line.is_empty() {
            break;
        }
        if line.starts_with([' ', '\t']) {
            return false;
        }
        let Some((name, value)) = line.split_once(':') else {
            return false;
        };
        if name.is_empty()
            || !name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte))
            || value
                .bytes()
                .any(|byte| (byte < 0x20 && byte != b'\t') || byte == 0x7f)
        {
            return false;
        }
        if name.eq_ignore_ascii_case("host") {
            if host.replace(value.trim()).is_some() {
                return false;
            }
        } else if name.eq_ignore_ascii_case("origin") && origin.replace(value.trim()).is_some() {
            return false;
        }
    }
    // Retain legacy direct HTTP/1.0 clients without granting browsers an omitted-Host path.
    let Some(host) = host else {
        return fields[2] == "HTTP/1.0" && origin.is_none();
    };
    let Some(host) = authority(host) else {
        return false;
    };
    let is_bound_host =
        host.host == "localhost" || host.host.parse::<IpAddr>().ok() == Some(local.ip());
    if !local.ip().is_loopback() || host.port != local.port() || !is_bound_host {
        return false;
    }
    match origin {
        None => true,
        Some(value) => value
            .strip_prefix("http://")
            .and_then(authority)
            .is_some_and(|value| value == host),
    }
}

#[cfg(test)]
#[path = "http_origin_tests.rs"]
mod tests;
