use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;

use super::types::BoundFile;
use super::types::Manifest;
use crate::command_stdout_path;
use crate::validate_file_sha256;

pub(super) fn readonly(path: &Path) -> Result<()> {
    let mut selected = None;
    for line in std::fs::read_to_string("/proc/self/mountinfo")?.lines() {
        let fields = line.split_whitespace().collect::<Vec<_>>();
        ensure!(fields.len() > 6, "malformed Linux mount evidence");
        let mount = PathBuf::from(fields[4].replace("\\040", " ").replace("\\134", "\\"));
        if path.starts_with(&mount)
            && selected
                .as_ref()
                .is_none_or(|(length, _)| mount.as_os_str().len() > *length)
        {
            selected = Some((
                mount.as_os_str().len(),
                fields[5].split(',').any(|item| item == "ro"),
            ));
        }
    }
    ensure!(
        selected.is_some_and(|(_, immutable)| immutable),
        "qualification authority must be mounted read-only: {}",
        path.display()
    );
    Ok(())
}

pub(super) fn validate(
    manifest: &Manifest,
    builder: &Value,
    inputs: &Value,
    controller: &Value,
) -> Result<()> {
    ensure!(
        std::env::consts::OS == "linux" && std::env::consts::ARCH == "aarch64",
        "Linux qualification requires native ARM64"
    );
    let status = std::fs::read_to_string("/proc/self/status")?;
    ensure!(
        status
            .lines()
            .any(|line| line == "CapEff:\t0000000000000000"),
        "business process has effective capabilities"
    );
    ensure!(
        status.lines().any(|line| line == "NoNewPrivs:\t1"),
        "business process lacks no-new-privileges"
    );
    let uid = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:\t"))
        .context("missing process uid")?
        .split_whitespace()
        .map(str::parse::<u32>)
        .collect::<std::result::Result<Vec<_>, _>>()?;
    ensure!(
        uid.len() == 4 && uid.iter().all(|value| *value != 0),
        "business process must be non-root"
    );
    let net = std::fs::read_to_string("/proc/net/dev")?;
    let interfaces = net
        .lines()
        .filter_map(|line| line.split_once(':').map(|(name, _)| name.trim()))
        .collect::<BTreeSet<_>>();
    ensure!(
        interfaces == BTreeSet::from(["lo"]),
        "business namespace has non-loopback network interfaces"
    );
    for path in [
        "/var/run/docker.sock",
        "/run/docker.sock",
        "/hepta-docker.sock",
        "/hepta-control",
    ] {
        ensure!(
            !Path::new(path).exists(),
            "business process received Docker authority"
        );
    }
    ensure!(
        builder["schema"] == "hepta.synapse.linux.builder-seal.v1"
            && builder["target"] == "aarch64-unknown-linux-gnu"
            && builder["rust_release"] == "1.96.0",
        "Linux builder authority differs"
    );
    ensure!(
        inputs["schema"] == "hepta.synapse.linux.inputs.v1",
        "Linux actual input ledger differs"
    );
    ensure!(
        controller["schema"] == "hepta.synapse.linux.runtime-controller.v1"
            && controller["scope"] == "native-linux-arm64",
        "controller evidence has the wrong qualification scope"
    );
    let runtime = &controller["runtime_inspect"];
    let host = &runtime["HostConfig"];
    ensure!(
        runtime["Image"] == builder["image"]["config_id"] && runtime["State"]["Running"] == true,
        "business container identity changed"
    );
    ensure!(
        host["NetworkMode"] == "none"
            && host["ReadonlyRootfs"] == true
            && host["Privileged"] == false,
        "business host boundary differs"
    );
    ensure!(
        host["PidMode"].as_str() == Some("") && host["CapDrop"] == serde_json::json!(["ALL"]),
        "business PID/capability boundary differs"
    );
    let expected_user = format!(
        "{}:{}",
        uid[0],
        controller["runtime_gid"]
            .as_u64()
            .context("missing runtime gid")?
    );
    ensure!(
        runtime["Config"]["User"] == expected_user,
        "actual runtime uid differs from the host controller"
    );
    let proxy = &controller["proxy_inspect"];
    let runtime_id = runtime["Id"]
        .as_str()
        .context("runtime container has no identity")?;
    ensure!(
        proxy["HostConfig"]["NetworkMode"] == format!("container:{runtime_id}")
            && proxy["HostConfig"]["PidMode"] == "",
        "trusted proxy shared an unexpected namespace"
    );
    ensure!(
        controller["proxy_has_broad_docker_authority"] == true
            && controller["business_has_docker_authority"] == false,
        "Docker authority boundary was not stated accurately"
    );
    let tools = builder["tools"]
        .as_object()
        .context("missing sealed tools")?;
    ensure!(
        inputs["tools"].as_object() == Some(tools),
        "observed tools differ from the frozen builder"
    );
    for (name, identity) in tools {
        let tool: BoundFile = serde_json::from_value(identity.clone())?;
        tool.verify(name)?;
        readonly(&tool.path)?;
    }
    let rustc = PathBuf::from(
        tools["rustc"]["path"]
            .as_str()
            .context("missing compiler path")?,
    );
    let version = String::from_utf8(command_stdout_path(
        &rustc,
        &["-Vv"],
        &manifest.source_root,
    )?)?;
    for required in [
        "release: 1.96.0",
        "host: aarch64-unknown-linux-gnu",
        "commit-hash: ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96",
    ] {
        ensure!(
            version.lines().any(|line| line == required),
            "actual compiler release/host/commit differs"
        );
    }
    for name in [
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "LD_PRELOAD",
    ] {
        ensure!(
            std::env::var_os(name).is_none(),
            "unsealed compiler/loader override {name}"
        );
    }
    for name in ["RUSTC", "RUSTDOC"] {
        let key = name.to_ascii_lowercase();
        let expected = tools.get(&key).context("missing fixed compiler tool")?["path"]
            .as_str()
            .context("missing fixed compiler path")?;
        ensure!(
            std::env::var(name).as_deref() == Ok(expected),
            "executed compiler variable differs from the seal"
        );
    }
    if let Some(paths) = std::env::var_os("LD_LIBRARY_PATH") {
        for path in std::env::split_paths(&paths) {
            ensure!(
                path.starts_with("/hepta-build/frozen-test")
                    || path.starts_with("/usr/")
                    || path.starts_with("/lib/"),
                "nextest loader path escaped frozen executable/sysroot authority"
            );
            if path.exists() {
                readonly(&path)?;
            }
        }
    }
    let sysroot = PathBuf::from(
        inputs["rust_sysroot"]["root"]
            .as_str()
            .context("missing actual sysroot")?,
    );
    readonly(&sysroot)?;
    for (name, identity) in inputs["rust_sysroot"]["files"]
        .as_object()
        .context("missing sysroot inventory")?
    {
        let path = sysroot.join(name);
        ensure!(
            !Path::new(name).is_absolute()
                && !Path::new(name)
                    .components()
                    .any(|part| part == std::path::Component::ParentDir),
            "invalid sysroot inventory path"
        );
        let actual = path.canonicalize()?;
        if let Some(link) = identity.get("link") {
            ensure!(
                std::fs::read_link(&path)?.to_str() == link.as_str(),
                "actual sysroot symlink changed"
            );
            ensure!(
                actual.to_str() == identity["resolved"].as_str(),
                "sysroot link target changed"
            );
        } else {
            ensure!(actual == path, "unsealed sysroot symlink appeared");
        }
        validate_file_sha256(
            &actual,
            identity["sha256"]
                .as_str()
                .context("missing sysroot hash")?,
            "actual Rust sysroot input",
        )?;
    }
    Ok(())
}
