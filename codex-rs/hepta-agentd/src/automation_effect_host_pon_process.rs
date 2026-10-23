//! One operation-local subprocess exchange for the existing PoN adapter.
//! No durable owner, retry identity, endpoint choice, or execution authority.
use std::io;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

#[path = "automation_effect_host_pon_credential.rs"]
mod credential;
pub(super) use credential::CredentialPin;
pub(super) use credential::CredentialSnapshot;

pub(super) enum Outcome {
    BeforeStart,
    Unknown,
    Complete(Vec<u8>),
}

async fn read_bounded(mut stream: impl AsyncRead + Unpin, limit: usize) -> io::Result<Vec<u8>> {
    let mut retained = Vec::new();
    let mut buffer = [0_u8; 4096];
    loop {
        let read = stream.read(&mut buffer).await?;
        if read == 0 {
            return Ok(retained);
        }
        if read > limit.saturating_sub(retained.len()) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "PoN process output limit",
            ));
        }
        retained.extend_from_slice(&buffer[..read]);
    }
}

pub(super) async fn run(
    command: Command,
    payload: &[u8],
    deadline: Instant,
    output_limit: usize,
) -> Outcome {
    run_owned(
        command,
        payload,
        deadline,
        output_limit,
        /*credential*/ None,
    )
    .await
}

pub(super) async fn run_with_credential(
    command: Command,
    payload: &[u8],
    deadline: Instant,
    output_limit: usize,
    credential: CredentialSnapshot,
) -> Outcome {
    run_owned(command, payload, deadline, output_limit, Some(credential)).await
}

async fn run_owned(
    mut command: Command,
    payload: &[u8],
    deadline: Instant,
    output_limit: usize,
    mut credential: Option<CredentialSnapshot>,
) -> Outcome {
    if Instant::now() >= deadline {
        return Outcome::BeforeStart;
    }
    // The sealed ELF identity does not cover ambient loader configuration or
    // inherited credentials. This private PoN path takes all runtime inputs
    // through its pinned arguments and exact stdin; no caller environment is
    // part of that contract. Clear even explicit mappings at the last boundary
    // before spawn. System loader/libraries and the host remain trusted: this
    // is environment isolation, not a new sandbox or execution capability.
    command.env_clear().env("LC_ALL", "C").env("TZ", "UTC");
    let mut command = tokio::process::Command::from(command);
    command
        .kill_on_drop(true)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(_) => return Outcome::BeforeStart,
    };
    if let Some(credential) = credential.as_mut() {
        credential.child_started();
    }
    // These futures are polled together and dropped together. There are no
    // detached pipe threads whose blocking join can escape the original limit.
    let exchange = async {
        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| io::Error::other("PoN stdin missing"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("PoN stdout missing"))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| io::Error::other("PoN stderr missing"))?;
        let write = async move {
            stdin.write_all(payload).await?;
            stdin.shutdown().await?;
            drop(stdin); // Child must observe EOF, not wait for a live writer.
            Ok::<(), io::Error>(())
        };
        let ((), stdout, _, status) = tokio::try_join!(
            write,
            read_bounded(stdout, output_limit),
            read_bounded(stderr, output_limit),
            child.wait(),
        )?;
        if !status.success() {
            return Err(io::Error::other("PoN child status unknown"));
        }
        Ok::<Vec<u8>, io::Error>(stdout)
    };
    let result = tokio::time::timeout_at(tokio::time::Instant::from_std(deadline), exchange).await;
    if let Ok(Ok(stdout)) = result
        && Instant::now() < deadline
    {
        if let Some(credential) = credential.as_mut() {
            credential.child_reaped();
        }
        return Outcome::Complete(stdout);
    }
    // Timeout/output failure is post-entry Unknown, never NotDispatched. This
    // cleanup grace grants no extra execution-success deadline. If the kernel
    // cannot reap promptly, Tokio's kill-on-drop/reaper retains child cleanup;
    // it cannot turn an incomplete response into an acknowledgement. This is
    // direct-child cleanup, not a claim of arbitrary descendant supervision.
    let _ = child.start_kill();
    if let Ok(Ok(_)) = tokio::time::timeout(Duration::from_millis(250), child.wait()).await
        && let Some(credential) = credential.as_mut()
    {
        credential.child_reaped();
    }
    // If reap was not observed (including cancellation of this future), retain
    // only the protected snapshot pathname. Tokio retains direct-child cleanup;
    // this does not introduce another owner or extend the success deadline.
    Outcome::Unknown
}

#[cfg(all(
    test,
    target_os = "linux",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
#[path = "automation_effect_host_pon_native_tests.rs"]
mod native_tests;

#[cfg(all(
    test,
    target_os = "linux",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
#[path = "automation_effect_host_pon_chain_tests.rs"]
mod chain_tests;

#[cfg(all(
    test,
    target_os = "linux",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
#[path = "automation_effect_host_pon_task_chain_tests.rs"]
mod task_chain_tests;

#[cfg(all(
    test,
    target_os = "linux",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
#[path = "automation_effect_host_pon_growth_chain_tests.rs"]
mod growth_chain_tests;

#[cfg(all(
    test,
    target_os = "linux",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
#[path = "automation_effect_host_pon_growth_remote_chain_tests.rs"]
mod growth_remote_chain_tests;
