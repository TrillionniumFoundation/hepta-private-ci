//! Linux syscall fault regression. A child installs a self-restricting seccomp
//! filter, verifies real fsync EIO and execs the recovery worker. Missing Python
//! or denied seccomp fails this test rather than skipping it.
//! The disk authority is a source fixture, not authenticated host acceptance.

use std::cell::Cell;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Output;
use std::rc::Rc;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::AnchoredProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1 as JournalError;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptReceiptV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptTransitionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::storage;

const CHILD_TEST: &str =
    "recovery_sync_eio_tests::recovery_sync_eio_blocks_anchor_ack_and_successful_retry_retains_the_tail";
const ROOT_ENV: &str = "HEPTA_EVAL_RECOVERY_SYNC_TEST_ROOT";
const PATH_ENV: &str = "HEPTA_EVAL_RECOVERY_SYNC_TEST_PATH";
const EXPECTATION_ENV: &str = "HEPTA_EVAL_RECOVERY_SYNC_TEST_EXPECTATION";

// No Rust unsafe, runtime-generated binary, external script, or build-time
// resource is needed. The filter survives exec and denies only fsync. Reject
// unsupported syscall architectures before installing any filter; also check
// seccomp_data.arch on each syscall to prevent interpreting a different ABI.
const SECCOMP_EIO: &str = r#"
import ctypes
import errno
import os
import sys

supported = {'x86_64': (0xC000003E, 74), 'aarch64': (0xC00000B7, 82)}
machine = os.uname().machine
if machine not in supported:
    raise RuntimeError(f'unsupported seccomp syscall architecture: {machine}')
architecture, fsync_nr = supported[machine]

class Filter(ctypes.Structure):
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]

class Program(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]

filters = (Filter * 7)(
    Filter(0x20, 0, 0, 4),                     # load seccomp_data.arch
    Filter(0x15, 1, 0, architecture),          # matching architecture skips kill
    Filter(0x06, 0, 0, 0x80000000),            # SECCOMP_RET_KILL_PROCESS
    Filter(0x20, 0, 0, 0),                     # load seccomp_data.nr
    Filter(0x15, 0, 1, fsync_nr),              # other syscalls skip EIO
    Filter(0x06, 0, 0, 0x00050000 | errno.EIO), # SECCOMP_RET_ERRNO
    Filter(0x06, 0, 0, 0x7FFF0000),            # SECCOMP_RET_ALLOW
)
program = Program(len(filters), filters)
libc = ctypes.CDLL(None, use_errno=True)
libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                      ctypes.c_ulong, ctypes.c_ulong]
libc.prctl.restype = ctypes.c_int
for option, arg1, arg2 in [
    (38, 1, 0),                              # PR_SET_NO_NEW_PRIVS
    (22, 2, ctypes.cast(ctypes.byref(program), ctypes.c_void_p).value),
]:                                           # PR_SET_SECCOMP, FILTER
    if libc.prctl(option, arg1, arg2, 0, 0) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
os.execv(sys.argv[1], sys.argv[1:])
"#;

#[derive(Clone, Copy)]
enum RecoveryPath {
    Ordinary,
    Checkpoint,
}

impl RecoveryPath {
    fn name(self) -> &'static str {
        match self {
            Self::Ordinary => "ordinary",
            Self::Checkpoint => "checkpoint",
        }
    }
}

#[derive(Clone, Copy)]
enum ExpectedRecovery {
    SyncFailure,
    SuccessfulRetry,
}

struct FixtureRoot(PathBuf);

impl FixtureRoot {
    fn new(path: RecoveryPath) -> Self {
        let ordinal = super::NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-recovery-sync-eio-{}-{ordinal}-{}",
            std::process::id(),
            path.name()
        ));
        fs::create_dir(&root).unwrap_or_else(|error| panic!("create sync fixture: {error:?}"));
        Self(root)
    }
}

impl Drop for FixtureRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct CountingAuthority {
    inner: storage::DiskAnchor,
    cas_calls: Rc<Cell<usize>>,
}

impl ProductEvaluationAttemptAnchorStoreV1 for CountingAuthority {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, JournalError> {
        self.inner.load(binding)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), JournalError> {
        self.cas_calls.set(self.cas_calls.get() + 1);
        self.inner.compare_and_swap(binding, expected, next)
    }
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"recovery-sync-eio-binding")
}

fn attempt_id() -> StableId {
    StableId::new("recovery-sync-eio-attempt")
        .unwrap_or_else(|error| panic!("fixture attempt id: {error:?}"))
}

fn intent() -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1::intent(
        attempt_id(),
        Digest32::of_bytes(b"recovery-sync-plan"),
        Digest32::of_bytes(b"recovery-sync-owner-namespace"),
        Digest32::of_bytes(b"recovery-sync-owner-state"),
    )
}

fn consumed() -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1::holdout_consumed(
        attempt_id(),
        Digest32::of_bytes(b"recovery-sync-plan"),
        Digest32::of_bytes(b"recovery-sync-holdout-record"),
    )
}

fn prepare(root: &Path) -> Vec<ProductEvaluationAttemptReceiptV1> {
    let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
        storage::create(&root.join("attempt.journal")),
        binding(),
    )
    .unwrap_or_else(|error| panic!("create native sync journal: {error:?}"));
    let prefix = journal
        .append(intent())
        .unwrap_or_else(|error| panic!("persist prefix: {error:?}"));
    let minimum = journal
        .anchor()
        .unwrap_or_else(|error| panic!("prefix anchor: {error:?}"));
    storage::DiskAnchor::new(&root.join("anchor"), /*crash_at*/ None)
        .compare_and_swap(binding(), /*expected*/ None, minimum)
        .unwrap_or_else(|error| panic!("retain independent prefix anchor: {error:?}"));
    journal
        .checkpoint_into(
            storage::create(&root.join("checkpoint")),
            &mut storage::DiskAnchor::new(&root.join("checkpoint-anchor"), /*crash_at*/ None),
        )
        .unwrap_or_else(|error| panic!("retain independent checkpoint: {error:?}"));
    let tail = journal
        .append(consumed())
        .unwrap_or_else(|error| panic!("persist complete unacknowledged tail: {error:?}"));
    vec![prefix, tail]
}

fn child(root: &Path, path: RecoveryPath, expected: ExpectedRecovery) -> Output {
    let executable =
        std::env::current_exe().unwrap_or_else(|error| panic!("test executable: {error:?}"));
    let mut command = match expected {
        ExpectedRecovery::SyncFailure => {
            let mut value = Command::new("python3");
            value.arg("-c").arg(SECCOMP_EIO).arg(executable);
            value
        }
        ExpectedRecovery::SuccessfulRetry => Command::new(executable),
    };
    command
        .args(["--exact", CHILD_TEST, "--nocapture"])
        .env(ROOT_ENV, root)
        .env(PATH_ENV, path.name())
        .env(
            EXPECTATION_ENV,
            match expected {
                ExpectedRecovery::SyncFailure => "sync-failure",
                ExpectedRecovery::SuccessfulRetry => "successful-retry",
            },
        )
        .output()
        .unwrap_or_else(|error| {
            panic!("Linux recovery sync regression requires Python and self-restricting seccomp: {error:?}")
        })
}

fn recovery_sync_child(root: &Path) {
    let cas_calls = Rc::new(Cell::new(0));
    let expected = std::env::var(EXPECTATION_ENV)
        .unwrap_or_else(|error| panic!("recovery sync expectation: {error:?}"));
    let file = storage::reopen(&root.join("attempt.journal"));
    if expected == "sync-failure" {
        // Prove the filter survives exec and returns an actual Linux OS EIO.
        // This nonmutating syscall occurs before recovery or any authority CAS.
        assert_eq!(
            file.sync_all()
                .err()
                .and_then(|error| error.raw_os_error()),
            Some(5),
            "the kernel must inject fsync EIO in the recovery worker"
        );
    }
    let authority = CountingAuthority {
        inner: storage::DiskAnchor::new(&root.join("anchor"), /*crash_at*/ None),
        cas_calls: Rc::clone(&cas_calls),
    };
    let result = match std::env::var(PATH_ENV).as_deref() {
        Ok("ordinary") => AnchoredProductEvaluationAttemptJournalV1::recover(
            file,
            binding(),
            authority,
        ),
        Ok("checkpoint") => AnchoredProductEvaluationAttemptJournalV1::recover_with_checkpoint(
            file,
            storage::reopen(&root.join("checkpoint")),
            binding(),
            authority,
            &mut storage::DiskAnchor::new(&root.join("checkpoint-anchor"), /*crash_at*/ None),
        ),
        path => panic!("unknown recovery sync path: {path:?}"),
    };
    match expected.as_str() {
        "sync-failure" => {
            assert_eq!(result.err(), Some(JournalError::Indeterminate));
            assert_eq!(cas_calls.get(), 0);
        }
        "successful-retry" => {
            let mut journal = result.unwrap_or_else(|error| panic!("retry recovery: {error:?}"));
            let history = journal
                .history(&attempt_id())
                .unwrap_or_else(|error| panic!("recovered history: {error:?}"));
            assert_eq!(
                history.into_iter().map(|receipt| receipt.transition).collect::<Vec<_>>(),
                vec![intent(), consumed()]
            );
            assert_eq!(cas_calls.get(), 1);
        }
        expected => panic!("unknown recovery sync expectation: {expected:?}"),
    }
}

#[test]
fn recovery_sync_eio_blocks_anchor_ack_and_successful_retry_retains_the_tail() {
    if let Ok(root) = std::env::var(ROOT_ENV) {
        recovery_sync_child(Path::new(&root));
        return;
    }
    for path in [RecoveryPath::Ordinary, RecoveryPath::Checkpoint] {
        let root = FixtureRoot::new(path);
        let history = prepare(&root.0);
        let retained_paths = [
            "attempt.journal",
            "anchor/retained",
            "checkpoint",
            "checkpoint-anchor/retained",
        ];
        let before = retained_paths.map(|name| {
            fs::read(root.0.join(name)).unwrap_or_else(|error| panic!("before bytes: {error:?}"))
        });
        let failed = child(&root.0, path, ExpectedRecovery::SyncFailure);
        assert!(
            failed.status.success(),
            "{} fault child failed: {} {}",
            path.name(),
            String::from_utf8_lossy(&failed.stdout),
            String::from_utf8_lossy(&failed.stderr)
        );
        let after = retained_paths.map(|name| {
            fs::read(root.0.join(name)).unwrap_or_else(|error| panic!("after bytes: {error:?}"))
        });
        assert_eq!(after, before, "failed recovery must not change any durable bytes");
        let retry = child(&root.0, path, ExpectedRecovery::SuccessfulRetry);
        assert!(
            retry.status.success(),
            "{} retry child failed: {} {}",
            path.name(),
            String::from_utf8_lossy(&retry.stdout),
            String::from_utf8_lossy(&retry.stderr)
        );
        let mut recovered = LockedFileProductEvaluationAttemptJournalV1::recover(
            storage::reopen(&root.0.join("attempt.journal")),
            binding(),
        )
        .unwrap_or_else(|error| panic!("full replay after successful retry: {error:?}"));
        assert_eq!(recovered.history(&attempt_id()), Ok(history));
        let retained = storage::DiskAnchor::new(&root.0.join("anchor"), /*crash_at*/ None)
            .load(binding())
            .unwrap_or_else(|error| panic!("retained retry anchor: {error:?}"));
        assert_eq!(retained, recovered.anchor().ok());
    }
}
