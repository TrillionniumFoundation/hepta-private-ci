#![cfg(target_os = "linux")]

use std::env;
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
const TEST_NAME: &str = "post_rename_directory_fsync_failure_is_indeterminate_and_retains_candidate";
const ACTIVE_POINTER: &str = ".cognitive-active-v1";
const ANCHOR_FILE: &str = "retained-current-cut.json";

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
fn post_rename_directory_fsync_failure_is_indeterminate_and_retains_candidate() {
    match env::var(CHILD_MODE).as_deref() {
        Ok("seed") => {
            seed_and_retain_current_cut();
            return;
        }
        Ok("recover") => {
            run_faulted_recovery_child();
            return;
        }
        Ok(other) => panic!("unknown fsync fault child mode: {other}"),
        Err(_) => {}
    }

    let temp = TempDir::new().expect("temporary fault-injection root");
    let owner = agent_id();
    let layout = layout(temp.path(), &owner);
    let preload = build_fsync_fault_library(temp.path());
    let current_exe = env::current_exe().expect("current integration-test executable");

    assert_child_success(run_child(
        &current_exe,
        temp.path(),
        "seed",
        /*preload*/ None,
        layout.cognitive_root(),
    ));
    assert_child_success(run_child(
        &current_exe,
        temp.path(),
        "recover",
        Some(&preload),
        layout.cognitive_root(),
    ));
}

fn run_child(
    current_exe: &Path,
    test_root: &Path,
    mode: &str,
    preload: Option<&Path>,
    fault_root: &Path,
) -> Output {
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
    command
        .output()
        .unwrap_or_else(|error| panic!("spawn {mode} recovery child: {error}"))
}

fn assert_child_success(output: Output) {
    assert!(
        output.status.success(),
        "fault-injection child failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

fn seed_and_retain_current_cut() {
    let test_root = PathBuf::from(env::var_os(TEST_ROOT).expect("seed test root"));
    let owner = agent_id();
    let layout = layout(&test_root, &owner);
    let runtime = tokio::runtime::Runtime::new().expect("tokio runtime");
    let anchor = runtime.block_on(async {
        let store = CognitiveStore::open(&layout)
            .await
            .expect("seed durable cognitive owner");
        store
            .recovery_anchor()
            .await
            .expect("capture exact current cut")
    });
    fs::write(
        test_root.join(ANCHOR_FILE),
        serde_json::to_vec(&anchor).expect("serialize retained current cut"),
    )
    .expect("persist retained current cut outside the cognitive root");
}

fn run_faulted_recovery_child() {
    let test_root = PathBuf::from(env::var_os(TEST_ROOT).expect("recovery test root"));
    let owner = agent_id();
    let layout = layout(&test_root, &owner);
    let expected_fault_root = PathBuf::from(env::var_os(FAULT_ROOT).expect("fault root"));
    assert_eq!(layout.cognitive_root(), expected_fault_root.as_path());
    let anchor: CognitiveRecoveryAnchor = serde_json::from_slice(
        &fs::read(test_root.join(ANCHOR_FILE)).expect("read retained current cut"),
    )
    .expect("decode retained current cut");

    let runtime = tokio::runtime::Runtime::new().expect("tokio runtime");
    runtime.block_on(async {
        let authority = recovery_authority(&owner);
        let result = CognitiveStore::open_with_recovery(
            &layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            &authority,
            &RecoveryVerifier,
        )
        .await;
        let error = match result {
            Err(error) => error,
            Ok(_) => panic!("faulted recovery unexpectedly returned a writable store"),
        };
        assert!(
            matches!(
                error,
                CognitiveRecoveryError::Indeterminate(ref message)
                    if message.contains("pointer rename")
            ),
            "post-rename directory-fsync uncertainty must remain indeterminate: {error:?}",
        );

        let pointer = layout.cognitive_root().join(ACTIVE_POINTER);
        let active_name = fs::read_to_string(&pointer).expect("retained active pointer");
        let candidate = layout.cognitive_root().join(active_name.trim());
        assert!(
            candidate.exists(),
            "a possibly active recovered generation must be retained"
        );
        assert!(
            active_name.trim().starts_with("cognitive_recovered_v1_"),
            "the active pointer must name a recovered generation"
        );
    });
}

fn agent_id() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-00000000cf51").expect("valid Agent id")
}

fn layout(root: &Path, owner: &AgentId) -> codex_hepta_paths::HeptaAgentLayout {
    let fleet = root.join("fleet");
    fs::create_dir_all(&fleet).expect("create fleet root");
    HeptaFleetRoot::parse(fleet)
        .expect("fleet root")
        .layout()
        .agent(owner)
}

fn recovery_authority(owner: &AgentId) -> ProductionAuthorityLease {
    ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"post-rename-fsync-fault-grant"),
        7,
        11,
        u64::MAX,
        ProductionAuthorityToken::from_verified_bytes(
            b"post-rename-fsync-fault-token".to_vec(),
        )
        .expect("valid recovery token"),
    )
    .expect("valid recovery authority")
}

fn build_fsync_fault_library(root: &Path) -> PathBuf {
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
    )
    .expect("write fsync fault source");

    let output = Command::new("cc")
        .arg("-shared")
        .arg("-fPIC")
        .arg("-O2")
        .arg("-std=c11")
        .arg(&source)
        .arg("-o")
        .arg(&library)
        .arg("-ldl")
        .output()
        .expect("compile fsync fault library");
    assert!(
        output.status.success(),
        "compile fsync fault library\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    library
}
