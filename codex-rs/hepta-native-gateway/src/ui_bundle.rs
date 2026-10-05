//! Immutable, bounded Rust UI assets selected by an explicit manifest digest.
//! The digest is artifact integrity, never signer or business authority.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;

#[path = "ui_bundle_reader.rs"]
mod reader;

const MAX_MANIFEST_BYTES: usize = 2 * 1024 * 1024;
const MAX_ASSETS: usize = 128;
pub(crate) const MAX_ASSET_BYTES: usize = 64 * 1024 * 1024;
const MAX_BUNDLE_BYTES: usize = 128 * 1024 * 1024;
const CSP: &str = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

/// Explicit selection of a complete, immutable UI build result.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UiBundleOptions {
    pub directory: PathBuf,
    pub manifest_sha256: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Manifest {
    schema: String,
    browser_runtime: String,
    fixtures: bool,
    threads: bool,
    automatic_crash_upload: bool,
    source_identity: SourceIdentity,
    files: BTreeMap<String, AssetInput>,
}

#[derive(Deserialize)]
struct SourceIdentity {
    sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AssetInput {
    bytes: usize,
    sha256: String,
}

struct Asset {
    bytes: Arc<[u8]>,
    mime: &'static str,
}

pub(crate) struct UiBundle {
    assets: BTreeMap<String, Asset>,
    pub(crate) source_identity: String,
}

pub(crate) struct UiResponse {
    pub(crate) headers: Vec<u8>,
    pub(crate) body: Arc<[u8]>,
}

impl UiBundle {
    pub(crate) fn load(options: &UiBundleOptions) -> Result<Self> {
        ensure!(
            canonical_digest(&options.manifest_sha256),
            "invalid UI manifest SHA256"
        );
        let directory = reader::Directory::open(&options.directory)?;
        let bytes = directory.read("build-manifest.json", MAX_MANIFEST_BYTES)?;
        ensure!(
            digest(&bytes) == options.manifest_sha256,
            "UI manifest digest differs from selected artifact"
        );
        let manifest: Manifest =
            serde_json::from_slice(&bytes).context("parse UI build manifest")?;
        ensure!(
            manifest.schema == "hepta.robrix-ui.build.v1"
                && manifest.browser_runtime == "rust-makepad-wasm",
            "unsupported UI build schema/runtime"
        );
        ensure!(
            !manifest.fixtures && !manifest.threads && !manifest.automatic_crash_upload,
            "UI build has unsupported fixture/thread/upload behavior"
        );
        ensure!(
            canonical_digest(&manifest.source_identity.sha256),
            "invalid UI source identity"
        );
        ensure!(
            !manifest.files.is_empty() && manifest.files.len() <= MAX_ASSETS,
            "UI asset count exceeds bound"
        );
        for required in ["index.html", "bootstrap.js", "input-platform.css"] {
            ensure!(
                manifest.files.contains_key(required),
                "UI build missing required entry {required}"
            );
        }
        ensure!(
            manifest.files.keys().any(|path| path.ends_with(".wasm")),
            "UI build missing WASM"
        );
        let mut total = bytes.len();
        for input in manifest.files.values() {
            ensure!(
                input.bytes <= MAX_ASSET_BYTES && canonical_digest(&input.sha256),
                "invalid UI asset size/digest"
            );
            total = total
                .checked_add(input.bytes)
                .context("UI asset size overflow")?;
            ensure!(total <= MAX_BUNDLE_BYTES, "UI bundle exceeds memory bound");
        }
        let mut assets = BTreeMap::new();
        for (path, input) in manifest.files {
            ensure!(
                valid_asset_path(&path) && path != "build-manifest.json",
                "invalid or reserved UI asset path"
            );
            let bytes = directory.read(&path, input.bytes)?;
            ensure!(
                bytes.len() == input.bytes && digest(&bytes) == input.sha256,
                "UI asset differs from selected manifest: {path}"
            );
            assets.insert(
                path.clone(),
                Asset {
                    bytes: bytes.into(),
                    mime: mime(&path)?,
                },
            );
        }
        assets.insert(
            "build-manifest.json".to_owned(),
            Asset {
                bytes: bytes.into(),
                mime: "application/json",
            },
        );
        Ok(Self {
            assets,
            source_identity: manifest.source_identity.sha256,
        })
    }

    pub(crate) fn response(&self, target: &str) -> Option<UiResponse> {
        let path = target.split('?').next()?;
        let relative = if path == "/" {
            "index.html"
        } else {
            path.strip_prefix('/')?
        };
        if !valid_asset_path(relative) {
            return None;
        }
        let asset = self.assets.get(relative)?;
        let headers = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: {}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\nContent-Security-Policy: {CSP}\r\n\r\n",
            asset.mime, asset.bytes.len()
        ).into_bytes();
        Some(UiResponse {
            headers,
            body: Arc::clone(&asset.bytes),
        })
    }
}

fn canonical_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn valid_asset_path(path: &str) -> bool {
    !path.is_empty()
        && path.len() <= 512
        && path.split('/').count() <= 16
        && path.split('/').all(|part| {
            !part.is_empty()
                && part != "."
                && part != ".."
                && part
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        })
        && path != "healthz"
        && path != "api"
        && !path.starts_with("api/")
}

fn mime(path: &str) -> Result<&'static str> {
    Ok(match path.rsplit('.').next() {
        Some("html") => "text/html; charset=utf-8",
        Some("js") => "text/javascript; charset=utf-8",
        Some("css") => "text/css; charset=utf-8",
        Some("wasm") => "application/wasm",
        Some("ttf") => "font/ttf",
        Some("otf") => "font/otf",
        Some("png") => "image/png",
        Some("svg") => "image/svg+xml",
        Some("json") => "application/json",
        Some("txt" | "md") => "text/plain; charset=utf-8",
        _ => anyhow::bail!("unsupported UI asset type"),
    })
}

#[cfg(test)]
#[path = "ui_bundle_tests.rs"]
mod tests;
