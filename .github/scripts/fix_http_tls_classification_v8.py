#!/usr/bin/env python3
"""Apply and verify the narrow nested TLS error-chain repair used by V8."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "codex-rs"
TLS_PATH = CODEX / "http-client/src/tls_backend_fallback.rs"
POOL_PATH = CODEX / "http-client/src/route_aware_client_pool.rs"
RECEIPT = ROOT / "convergence/http-tls-fix-v8.json"

OLD_TLS = '''pub(crate) fn should_retry_with_rustls(error: &reqwest::Error) -> bool {
    error.is_connect() && !error.is_timeout() && error.source().is_some_and(has_retryable_tls_error)
}

fn has_retryable_tls_error(error: &(dyn Error + 'static)) -> bool {
    let mut source = Some(error);
    let mut recognized_negotiation_failure = false;

    while let Some(error) = source {
        let message = error.to_string().to_ascii_lowercase();
        if [
            "certificate",
            "unknown issuer",
            "unknown ca",
            "untrusted",
            "self signed",
            "self-signed",
            "hostname",
            "expired",
            "revoked",
        ]
        .iter()
        .any(|marker| message.contains(marker))
        {
            return false;
        }

        // macOS Secure Transport reports the protocol alert as "bad protocol version".
        let is_macos_protocol_version_error = message.contains("bad protocol version");
        // Linux OpenSSL reports the peer's "tlsv1 alert protocol version".
        let is_linux_protocol_version_error = message.contains("tlsv1 alert protocol version");
        // Windows Schannel may expose the protocol alert as a raw or formatted OS error.
        let is_schannel_protocol_version_error = error
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error)
            == Some(SCHANNEL_PROTOCOL_VERSION_ERROR)
            || message.contains("(os error -2146893054)")
            || message.contains("0x80090302");
        if is_macos_protocol_version_error
            || is_linux_protocol_version_error
            || is_schannel_protocol_version_error
        {
            recognized_negotiation_failure = true;
        }
        source = error.source();
    }

    recognized_negotiation_failure
}
'''

NEW_TLS = '''const MAX_ERROR_CHAIN_DEPTH: usize = 32;

pub(crate) fn should_retry_with_rustls(error: &reqwest::Error) -> bool {
    error.is_connect() && !error.is_timeout() && error.source().is_some_and(has_retryable_tls_error)
}

pub(crate) fn has_tls_error(error: &(dyn Error + 'static)) -> bool {
    let mut has_tls_error = false;
    walk_error_chain(error, 0, &mut |error| {
        has_tls_error |= error.is::<rustls::Error>() || error.is::<native_tls::Error>();
    });
    has_tls_error
}

fn has_retryable_tls_error(error: &(dyn Error + 'static)) -> bool {
    let mut recognized_negotiation_failure = false;
    let mut certificate_failure = false;

    walk_error_chain(error, 0, &mut |error| {
        let mut message = error.to_string().to_ascii_lowercase();
        if error.is::<rustls::Error>() {
            message.push(' ');
            message.push_str(&format!("{error:?}").to_ascii_lowercase());
        }

        if [
            "certificate",
            "unknown issuer",
            "unknownissuer",
            "unknown ca",
            "unknownca",
            "untrusted",
            "self signed",
            "self-signed",
            "hostname",
            "notvalidforname",
            "expired",
            "revoked",
        ]
        .iter()
        .any(|marker| message.contains(marker))
        {
            certificate_failure = true;
        }

        // macOS Secure Transport reports the protocol alert as "bad protocol version".
        let is_macos_protocol_version_error = message.contains("bad protocol version");
        // Linux OpenSSL reports the peer's "tlsv1 alert protocol version".
        let is_linux_protocol_version_error = message.contains("tlsv1 alert protocol version");
        // rustls retains the protocol alert as a structured error nested inside io::Error.
        let is_rustls_protocol_version_error = error.is::<rustls::Error>()
            && (message.contains("alertreceived(protocolversion)")
                || message.contains("received fatal alert: protocolversion"));
        // Windows Schannel may expose the protocol alert as a raw or formatted OS error.
        let is_schannel_protocol_version_error = error
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error)
            == Some(SCHANNEL_PROTOCOL_VERSION_ERROR)
            || message.contains("(os error -2146893054)")
            || message.contains("0x80090302");
        if is_macos_protocol_version_error
            || is_linux_protocol_version_error
            || is_rustls_protocol_version_error
            || is_schannel_protocol_version_error
        {
            recognized_negotiation_failure = true;
        }
    });

    recognized_negotiation_failure && !certificate_failure
}

fn walk_error_chain(
    error: &(dyn Error + 'static),
    depth: usize,
    visitor: &mut impl FnMut(&(dyn Error + 'static)),
) {
    if depth >= MAX_ERROR_CHAIN_DEPTH {
        return;
    }

    visitor(error);

    // std::io::Error stores custom errors behind get_ref(); on current Rust versions that
    // inner value is not guaranteed to be exposed by Error::source(). Walk it explicitly
    // so rustls certificate and protocol alerts remain classifiable through hyper/reqwest.
    if let Some(io_error) = error.downcast_ref::<std::io::Error>()
        && let Some(inner) = io_error.get_ref()
    {
        walk_error_chain(inner, depth + 1, visitor);
        return;
    }

    if let Some(source) = error.source() {
        walk_error_chain(source, depth + 1, visitor);
    }
}
'''

OLD_IMPORT = '''use crate::tls_backend_fallback::RustlsClientCache;
use crate::tls_backend_fallback::should_retry_with_rustls;
'''
NEW_IMPORT = '''use crate::tls_backend_fallback::RustlsClientCache;
use crate::tls_backend_fallback::has_tls_error;
use crate::tls_backend_fallback::should_retry_with_rustls;
'''

OLD_FAILURE = '''        if let Self::Route(RouteAwareClientPoolError::Resolve(error)) = self
            && let Some(source) = error.get_ref()
            && source.is::<rustls::Error>()
        {
            return Some(RouteFailureClass::TlsError);
        }

        let mut source: Option<&(dyn std::error::Error + 'static)> = Some(self);
        while let Some(error) = source {
            if error.downcast_ref::<rustls::Error>().is_some()
                || error.downcast_ref::<native_tls::Error>().is_some()
            {
                return Some(RouteFailureClass::TlsError);
            }
            if error.to_string() == "tunnel error: proxy authorization required" {
                return Some(RouteFailureClass::ProxyAuthenticationRequired);
            }
            source = error.source();
        }
'''
NEW_FAILURE = '''        if has_tls_error(self) {
            return Some(RouteFailureClass::TlsError);
        }

        let mut source: Option<&(dyn std::error::Error + 'static)> = Some(self);
        while let Some(error) = source {
            if error.to_string() == "tunnel error: proxy authorization required" {
                return Some(RouteFailureClass::ProxyAuthenticationRequired);
            }
            source = error.source();
        }
'''


def replace_or_verify(path: Path, old: str, new: str, marker: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return True
    if marker not in text:
        raise SystemExit(f"neither expected old block nor repaired marker found in {path}")
    return False


def main() -> int:
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    changed = []
    if replace_or_verify(TLS_PATH, OLD_TLS, NEW_TLS, "const MAX_ERROR_CHAIN_DEPTH: usize = 32;"):
        changed.append(str(TLS_PATH.relative_to(ROOT)))
    if replace_or_verify(POOL_PATH, OLD_IMPORT, NEW_IMPORT, "use crate::tls_backend_fallback::has_tls_error;"):
        changed.append(str(POOL_PATH.relative_to(ROOT)))
    if replace_or_verify(POOL_PATH, OLD_FAILURE, NEW_FAILURE, "if has_tls_error(self)"):
        relative = str(POOL_PATH.relative_to(ROOT))
        if relative not in changed:
            changed.append(relative)

    environment = os.environ.copy()
    environment.setdefault("CARGO_NET_GIT_FETCH_WITH_CLI", "true")
    environment.setdefault("CARGO_INCREMENTAL", "0")
    environment.setdefault("CARGO_PROFILE_DEV_DEBUG", "0")
    environment.setdefault("CARGO_PROFILE_TEST_DEBUG", "0")

    format_result = subprocess.run(
        ["cargo", "fmt", "--all"],
        cwd=CODEX,
        env=environment,
        check=False,
    )
    if format_result.returncode != 0:
        raise SystemExit(format_result.returncode)

    test_command = [
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-http-client",
        "--lib",
        "--",
        "--test-threads=1",
    ]
    test_result = subprocess.run(
        test_command,
        cwd=CODEX,
        env=environment,
        check=False,
    )
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)

    RECEIPT.write_text(
        json.dumps(
            {
                "schema": 8,
                "status": "fixed" if changed else "already-present",
                "changed_files": changed,
                "test_command": " ".join(test_command),
                "test_working_directory": "codex-rs",
                "test_exit_code": test_result.returncode,
                "classification_policy": "walk nested Error::source and std::io::Error::get_ref; never inspect outer request URL",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return test_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
