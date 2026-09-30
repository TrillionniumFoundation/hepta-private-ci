#![cfg(target_os = "linux")]

use std::env;
use std::error::Error;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Output;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveRecoveryError;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

const CHILD_MODE: &str = "HEPTA_COGNITIVE_FSYNC_FAULT_CHILD_MODE";
const TEST_ROOT: &str = "HEPTA_COGNITIVE_FSYNC_FAULT_TEST_ROOT";
const FAULT_ROOT: &str = "HEPTA_COGNITIVE_FSYNC_FAULT_ROOT";
const TEST_NAME: &str =
    "post_rename_directory_fsync_failure_is_indeterminate_and_retains_candidate";
const ACTIVE_POINTER: &str = ".cognitive-active-v1";
const ANCHOR_FILE: &str = "retained-current-cut.json";

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

struct RecoveryVerifier;

impl ProductionAuthorityVerifier for RecoveryVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        if &authority.agent_id == expected_agent {
            Ok(())
        } else {
            Err("recovery authority owner mismatch".to_string())
        }
    }
}

#[test]
fn post_rename_directory_fsync_failure_is_indeterminate_and_retains_candidate() -> TestResult {
    match env::var(CHILD_MODE).as_deref() {
        Ok("seed") => return seed_and_retain_current_cut(),
        Ok("recover") => return run_faulted_recovery_child(),
        Ok(other) => return Err(format!("unknown fsync fault child mode: {other}").into()),
        Err(_) => {}
    }

    let temp = TempDir::new()?;
    let owner = agent_id()?;
    let layout = layout(temp.path(), &owner)?;
    let preload = build_fsync_fault_library(temp.path())?;
    let current_exe = env::current_exe()?;

    assert_child_success(run_child(
        &current_exe,
        temp.path(),
        "seed",
        /*preload*/ None,
        layout.cognitive_root(),
    )?)?;
    assert_child_success(run_child(
        &current_exe,
        temp.path(),
        "recover",
        Some(&preload),
        layout.cognitive_root(),
    )?)?;
    Ok(())
}

fn run_child(
    current_exe: &Path,
    test_root: &Path,
    mode: &str,
    preload: Option<&Path>,
    fault_root: &Path,
) -> std::io::Result<Output> {
    let mut command = Command::new(current_exe);
    command
        .arg(TEST_NAME)
        .arg("--exact")
        .arg("--nocapture")
        .arg("--test-threads=1")
        .env(CHILD_MODE, mode)
        .env(TEST_ROOT, test_root);
    if let Some(preload) = preload {
        command
            .env(FAULT_ROOT, fault_root)
            .env("LD_PRELOAD", preload);
    }
    command.output()
}

fn assert_child_success(output: Output) -> TestResult {
    if output.status.success() {
        return Ok(());
    }
    Err(format!(
        "fault-injection child failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    )
    .into())
}

fn seed_and_retain_current_cut() -> TestResult {
    let test_root = PathBuf::from(env::var_os(TEST_ROOT).ok_or("missing seed test root")?);
    let owner = agent_id()?;
    let layout = layout(&test_root, &owner)?;
    let runtime = tokio::runtime::Runtime::new()?;
    let anchor = runtime.block_on(async {
        let store = CognitiveStore::open(&layout).await?;
        let anchor = store.recovery_anchor().await?;
        store.close_for_recovery_handoff().await?;
        Ok::<CognitiveRecoveryAnchor, Box<dyn Error>>(anchor)
    })?;
    fs::write(test_root.join(ANCHOR_FILE), serde_json::to_vec(&anchor)?)?;
    Ok(())
}

fn run_faulted_recovery_child() -> TestResult {
    let test_root = PathBuf::from(env::var_os(TEST_ROOT).ok_or("missing recovery test root")?);
    let owner = agent_id()?;
    let layout = layout(&test_root, &owner)?;
    let expected_fault_root = PathBuf::from(env::var_os(FAULT_ROOT).ok_or("missing fault root")?);
    if layout.cognitive_root() != expected_fault_root.as_path() {
        return Err("fault root differs from the cognitive owner root".into());
    }
    let anchor: CognitiveRecoveryAnchor =
        serde_json::from_slice(&fs::read(test_root.join(ANCHOR_FILE))?)?;

    let runtime = tokio::runtime::Runtime::new()?;
    runtime.block_on(async {
        let authority = recovery_authority(&owner)?;
        let result = CognitiveStore::open_with_recovery(
            &layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            &authority,
            &RecoveryVerifier,
        )
        .await;
        let error = match result {
            Err(error) => error,
            Ok(_) => return Err("faulted recovery unexpectedly returned a writable store".into()),
        };
        if !matches!(
            error,
            CognitiveRecoveryError::Indeterminate(ref message)
                if message.contains("pointer rename")
        ) {
            return Err(format!(
                "post-rename directory-fsync uncertainty must remain indeterminate: {error:?}"
            )
            .into());
        }

        let pointer = layout.cognitive_root().join(ACTIVE_POINTER);
        let active_name = fs::read_to_string(&pointer)?;
        let candidate = layout.cognitive_root().join(active_name.trim());
        if !candidate.exists() {
            return Err("a possibly active recovered generation was not retained".into());
        }
        if !active_name.trim().starts_with("cognitive_recovered_v1_") {
            return Err("the active pointer does not name a recovered generation".into());
        }
        Ok::<(), Box<dyn Error>>(())
    })
}

fn agent_id() -> TestResult<AgentId> {
    Ok(AgentId::parse("00000000-0000-4000-8000-00000000cf51")?)
}

fn layout(root: &Path, owner: &AgentId) -> TestResult<codex_hepta_paths::HeptaAgentLayout> {
    let fleet = root.join("fleet");
    fs::create_dir_all(&fleet)?;
    Ok(HeptaFleetRoot::parse(fleet)?.layout().agent(owner))
}

fn recovery_authority(owner: &AgentId) -> TestResult<ProductionAuthorityLease> {
    Ok(ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"post-rename-fsync-fault-grant"),
        7,
        11,
        u64::MAX,
        ProductionAuthorityToken::from_verified_bytes(b"post-rename-fsync-fault-token".to_vec())?,
    )?)
}

fn build_fsync_fault_library(root: &Path) -> TestResult<PathBuf> {
    let source = root.join("cognitive_fsync_fault.c");
    let library = root.join("libcognitive_fsync_fault.so");
    fs::write(
        &source,
        r#"
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static atomic_int injected = 0;

typedef int (*fsync_fn)(int);

int fsync(int fd) {
    static fsync_fn real_fsync = NULL;
    if (real_fsync == NULL) {
        real_fsync = (fsync_fn)dlsym(RTLD_NEXT, "fsync");
        if (real_fsync == NULL) {
            errno = ENOSYS;
            return -1;
        }
    }

    const char *root = getenv("HEPTA_COGNITIVE_FSYNC_FAULT_ROOT");
    if (root != NULL && atomic_load(&injected) == 0) {
        struct stat descriptor;
        if (fstat(fd, &descriptor) == 0 && S_ISDIR(descriptor.st_mode)) {
            char pointer[PATH_MAX];
            int written = snprintf(pointer, sizeof(pointer), "%s/.cognitive-active-v1", root);
            struct stat pointer_state;
            if (written > 0 && written < (int)sizeof(pointer)
                    && lstat(pointer, &pointer_state) == 0
                    && S_ISREG(pointer_state.st_mode)) {
                int expected = 0;
                if (atomic_compare_exchange_strong(&injected, &expected, 1)) {
                    errno = EIO;
                    return -1;
                }
            }
        }
    }

    return real_fsync(fd);
}
"#,
    )?;

    let output = Command::new("cc")
        .arg("-shared")
        .arg("-fPIC")
        .arg("-O2")
        .arg("-std=c11")
        .arg(&source)
        .arg("-o")
        .arg(&library)
        .arg("-ldl")
        .output()?;
    if !output.status.success() {
        return Err(format!(
            "compile fsync fault library\nstdout:\n{}\nstderr:\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        )
        .into());
    }
    Ok(library)
}
