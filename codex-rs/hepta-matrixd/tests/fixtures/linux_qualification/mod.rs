//! Linux-only evidence adapter. The existing macOS schema and business assertions remain separate.

use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;
use url::Url;

use crate::E2eEnvironment;
use crate::FIXTURE_MANIFEST_ENV;
use crate::PINNED_SYNAPSE_GIT_SHA;
use crate::PINNED_SYNAPSE_IMAGE;
use crate::PINNED_SYNAPSE_IMAGE_ID;
use crate::ProcessIdentityLedger;
use crate::QualificationCompletionAuthority;
use crate::QualificationMode;
use crate::command_stdout_path;
use crate::command_text_path;
use crate::read_and_remove_secret_capability;
use crate::validate_file_sha256;
use crate::validate_git_sha1;
use crate::validate_mode_0600_regular_file;
use crate::validate_private_directory;

mod host;
mod types;

use types::Manifest;

pub(super) fn required() -> Result<E2eEnvironment> {
    let path = PathBuf::from(
        std::env::var_os(FIXTURE_MANIFEST_ENV)
            .context("Linux fixture manifest is required; no skip exists")?,
    );
    ensure!(
        path.canonicalize()? == path,
        "Linux fixture manifest must be physical"
    );
    validate_mode_0600_regular_file(&path, "Linux fixture manifest")?;
    host::readonly(&path)?;
    let manifest: Manifest = serde_json::from_slice(&std::fs::read(&path)?)?;
    ensure!(
        manifest.schema_version == 1
            && manifest.qualification_kind == "linux_exact"
            && manifest.scope == "native-linux-arm64",
        "Linux scope cannot be represented as macOS exact qualification"
    );
    let source = manifest
        .source_seal
        .json("producer-to-qualification source seal")?;
    let builder = manifest.builder_seal.json("fixed builder seal")?;
    let build = manifest.build_result.json("actual cold build evidence")?;
    let inputs = manifest.build_inputs.json("actual tool/sysroot evidence")?;
    let controller = manifest
        .controller_snapshot
        .json("trusted Docker controller evidence")?;
    for authority in [
        &manifest.source_seal,
        &manifest.builder_seal,
        &manifest.build_result,
        &manifest.build_inputs,
        &manifest.controller_snapshot,
    ] {
        host::readonly(&authority.path)?;
    }
    host::validate(&manifest, &builder, &inputs, &controller)?;
    ensure!(
        source["schema"] == "hepta.synapse.linux.source-seal.v1"
            && source["source_clean"] == true
            && source["original_head_unchanged"] == true,
        "source authority did not retain the original producer checkout"
    );
    ensure!(
        source["qualification_commit"] == manifest.candidate_sha
            && source["qualification_tree"] == manifest.candidate_tree_sha
            && source["candidate_tree"] == manifest.candidate_tree_sha,
        "producer candidate tree differs from the qualification commit"
    );
    ensure!(
        build["schema"] == "hepta.synapse.linux.build.v1"
            && build["status"] == "built_not_executed"
            && build["source_clean"] == true
            && build["seed_unchanged"] == true
            && build["both_cold_targets_reclaimed"] == true,
        "cold offline build did not complete its provenance/readback gates"
    );
    let source_root = manifest.source_root.canonicalize()?;
    ensure!(
        source_root == manifest.source_root
            && source["source_root"].as_str() == source_root.to_str(),
        "compiled source root differs"
    );
    host::readonly(&source_root)?;
    validate_git_sha1(&manifest.candidate_sha, "Linux qualification commit")?;
    validate_git_sha1(&manifest.candidate_tree_sha, "Linux qualification tree")?;
    let git = PathBuf::from(
        builder["tools"]["git"]["path"]
            .as_str()
            .context("missing sealed Git")?,
    );
    ensure!(
        command_text_path(&git, &["rev-parse", "HEAD"], &source_root)? == manifest.candidate_sha,
        "qualification HEAD changed"
    );
    ensure!(
        command_text_path(&git, &["rev-parse", "HEAD^{tree}"], &source_root)?
            == manifest.candidate_tree_sha,
        "qualification tree changed"
    );
    ensure!(
        command_stdout_path(
            &git,
            &[
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignored=matching"
            ],
            &source_root
        )?
        .is_empty(),
        "Linux qualification source is not clean"
    );
    for (name, identity) in source["bound_files"]
        .as_object()
        .context("missing source input inventory")?
    {
        let name = std::path::Path::new(name);
        ensure!(
            !name.is_absolute()
                && !name
                    .components()
                    .any(|part| part == std::path::Component::ParentDir),
            "invalid source inventory path"
        );
        validate_file_sha256(
            &source_root.join(name),
            identity["sha256"].as_str().context("missing source hash")?,
            "compiled source input",
        )?;
    }
    ensure!(
        manifest
            .binaries
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>()
            == ["agentd", "matrixd", "test"],
        "Linux executable set differs"
    );
    for (name, binary) in &manifest.binaries {
        binary.verify(name)?;
        host::readonly(&binary.path)?;
        ensure!(
            build["binaries"][name]["path"].as_str() == binary.path.to_str()
                && build["binaries"][name]["sha256"] == binary.sha256
                && build["binaries"][name]["bytes"] == binary.bytes,
            "actual executable differs from the cold compiler artifact"
        );
    }
    ensure!(
        manifest.binaries["test"].path == std::env::current_exe()?.canonicalize()?,
        "the executing test is not the preserved cold binary"
    );
    let synapse = &controller["synapse"];
    ensure!(
        synapse["inspect"]["Image"] == PINNED_SYNAPSE_IMAGE_ID
            && builder["synapse"]["reference"] == PINNED_SYNAPSE_IMAGE
            && builder["synapse"]["revision"] == PINNED_SYNAPSE_GIT_SHA
            && synapse["version"] == "1.159.0",
        "running Synapse differs from the original immutable pin"
    );
    ensure!(
        synapse["network_inspect"][0]["Internal"] == true,
        "Synapse network is not internal"
    );
    let ports = &synapse["inspect"]["NetworkSettings"]["Ports"];
    ensure!(
        ports
            .as_object()
            .is_some_and(|items| items.values().all(Value::is_null)),
        "Synapse port was published"
    );
    manifest.proxy_source.verify("unchanged original proxy")?;
    validate_file_sha256(
        &source_root.join("codex-rs/hepta-matrixd/tests/fixtures/synapse-loopback-proxy.py"),
        &manifest.proxy_source.sha256,
        "original proxy source",
    )?;
    let ready = manifest.proxy_ready.json("actual proxy ready evidence")?;
    ensure!(
        ready["schema_version"] == 1
            && ready["transport"] == "docker-exec-loopback-proxy-v1"
            && ready["host"] == "127.0.0.1"
            && ready["target"] == "127.0.0.1:8008",
        "original proxy transport differs"
    );
    let homeserver = Url::parse(&manifest.homeserver)?;
    ensure!(
        homeserver.scheme() == "http"
            && homeserver.host_str() == Some("127.0.0.1")
            && homeserver.port().map(u64::from) == ready["port"].as_u64(),
        "business homeserver is not the attested loopback proxy"
    );
    let completion = QualificationCompletionAuthority::required()?;
    let fixture = manifest.fixture_root.canonicalize()?;
    validate_private_directory(&fixture, "Linux runtime fixture")?;
    ensure!(
        completion.directory == fixture.join("completion")
            && completion.capability_directory == manifest.credentials_directory
            && manifest.credentials_directory == fixture.join("credentials"),
        "Linux completion/credentials escaped the private runtime root"
    );
    validate_private_directory(&manifest.credentials_directory, "Linux credentials")?;
    let mut names = std::fs::read_dir(&manifest.credentials_directory)?
        .map(|entry| entry.map(|item| item.file_name().to_string_lossy().into_owned()))
        .collect::<std::io::Result<Vec<_>>>()?;
    names.sort();
    ensure!(
        names == ["agent-a-password", "agent-b-password", "human-password"],
        "unexpected credential capability"
    );
    let agent_a_password = read_and_remove_secret_capability(
        &manifest.credentials_directory.join("agent-a-password"),
        "Agent A password",
    )?;
    let agent_b_password = read_and_remove_secret_capability(
        &manifest.credentials_directory.join("agent-b-password"),
        "Agent B password",
    )?;
    let human_password = read_and_remove_secret_capability(
        &manifest.credentials_directory.join("human-password"),
        "human password",
    )?;
    std::fs::remove_dir(&manifest.credentials_directory)?;
    ensure!(
        manifest.runtime_tmp_root == fixture.join("runtime"),
        "Linux runtime path escaped the fixture"
    );
    validate_private_directory(&manifest.runtime_tmp_root, "Linux runtime temp root")?;
    ensure!(
        std::fs::read_dir(&manifest.runtime_tmp_root)?
            .next()
            .is_none(),
        "Linux runtime must start empty"
    );
    ensure!(
        manifest.process_identity_ledger == fixture.join("process-identity-ledger.json"),
        "Linux process ledger escaped the fixture"
    );
    validate_mode_0600_regular_file(&manifest.process_identity_ledger, "Linux process ledger")?;
    let ledger: ProcessIdentityLedger =
        serde_json::from_slice(&std::fs::read(&manifest.process_identity_ledger)?)?;
    ensure!(
        ledger.schema_version == 1
            && ledger.active.is_empty()
            && ledger.history.is_empty()
            && !ledger.explicit_shutdown_completed
            && !ledger.all_historical_pids_absent,
        "process ledger must start fail-closed"
    );
    eprintln!(
        "R4_LINUX_QUALIFICATION scope=native-linux-arm64 macos_qualification=false promotion_allowed=false"
    );
    Ok(E2eEnvironment {
        qualification_mode: QualificationMode::LinuxExact,
        candidate_sha: manifest.candidate_sha,
        candidate_tree_sha: manifest.candidate_tree_sha,
        source_clean: true,
        homeserver: manifest.homeserver,
        agentd_binary: manifest.binaries["agentd"].path.clone(),
        matrixd_binary: manifest.binaries["matrixd"].path.clone(),
        agentd_sha256: manifest.binaries["agentd"].sha256.clone(),
        matrixd_sha256: manifest.binaries["matrixd"].sha256.clone(),
        runtime_tmp_root: manifest.runtime_tmp_root,
        process_identity_ledger: manifest.process_identity_ledger,
        agent_a_password,
        agent_b_password,
        human_password,
        completion,
    })
}
