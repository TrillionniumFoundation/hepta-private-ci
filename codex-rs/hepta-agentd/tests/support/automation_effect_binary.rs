//! Bind the live owned daemon image to the exact binary resolved by Cargo.
//! Retention happens during each process phase, before any subsequent build.
use super::*;
use sha2::Digest;
use sha2::Sha256;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::process::Command;

fn source_command(root: &Path, args: &[&str]) -> Result<String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()?;
    ensure!(output.status.success(), "source identity command failed");
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

pub(super) fn source_identity() -> Result<Value> {
    let supplied = std::env::var_os("HEPTA_PQ_EFFECT_SOURCE_ROOT");
    let Some(supplied) = supplied else {
        ensure!(
            std::env::var_os("TESTED_SHA").is_none(),
            "qualification wrapper must supply its verified complete source root"
        );
        // Developer/Bazel functional execution makes no source qualification
        // claim. It still checks the live process image using the repo's binary
        // resolver. Qualification never derives a checkout from compile paths.
        return Ok(
            serde_json::json!({"qualification_binding":false,"scope":"unqualified functional process control; no wrapper-supplied source"}),
        );
    };
    let root = PathBuf::from(supplied);
    ensure!(
        root.is_absolute() && root.canonicalize()? == root,
        "qualification source root must be absolute and canonical"
    );
    let tested = std::env::var("TESTED_SHA").context("qualification tested SHA")?;
    let commit = source_command(&root, &["rev-parse", "HEAD"])?;
    let tree = source_command(&root, &["rev-parse", "HEAD^{tree}"])?;
    ensure!(
        tested == commit,
        "process evidence source differs from the original wrapper"
    );
    ensure!(
        source_command(
            &root,
            &["status", "--porcelain=v1", "--untracked-files=all"]
        )?
        .is_empty(),
        "qualification requires committed clean source"
    );
    let rustc = Command::new("rustc").arg("-Vv").output()?;
    ensure!(rustc.status.success(), "toolchain identity unavailable");
    let env: std::collections::BTreeMap<_, _> = [
        "RUSTUP_TOOLCHAIN",
        "CARGO_INCREMENTAL",
        "CARGO_BUILD_JOBS",
        "CARGO_PROFILE_TEST_DEBUG",
        "CARGO_PROFILE_DEV_DEBUG",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
    ]
    .into_iter()
    .map(|name| (name, std::env::var(name).ok()))
    .collect();
    Ok(
        serde_json::json!({"qualification_binding":true,"commit":commit,"tree":tree,"cargo_lock_sha256":Sha256Digest::for_bytes(&fs::read(root.join("codex-rs/Cargo.lock"))?),"rustc":String::from_utf8(rustc.stdout)?,"environment":env}),
    )
}

fn start_ticks(path: &Path) -> Result<String> {
    let stat = fs::read_to_string(path.join("stat"))?;
    Ok(stat
        .rsplit_once(')')
        .context("process stat")?
        .1
        .split_whitespace()
        .nth(19)
        .context("process start time")?
        .into())
}

fn file_identity(v: &fs::Metadata) -> (u64, u64, u64, i64, i64, i64, i64) {
    (
        v.dev(),
        v.ino(),
        v.len(),
        v.mtime(),
        v.mtime_nsec(),
        v.ctime(),
        v.ctime_nsec(),
    )
}

/// Keep both the original executable and completed retained copy open across
/// the owned restart. A later generation may reuse this exact file object,
/// never a path or an unverified earlier digest alone.
pub(super) struct LiveDaemonImage {
    image: fs::File,
    image_identity: (u64, u64, u64, i64, i64, i64, i64),
    retained: fs::File,
    retained_identity: (u64, u64, u64, i64, i64, i64, i64),
    retained_path: PathBuf,
    record: Value,
}

impl LiveDaemonImage {
    pub(super) fn record(&self) -> &Value {
        &self.record
    }
}

fn verify_same_held_file_object(
    original: &LiveDaemonImage,
    current: &fs::File,
    expected: &Path,
    source: &Value,
) -> Result<()> {
    ensure!(
        original.record["source"] == *source,
        "retained daemon image belongs to another source"
    );
    let path = fs::symlink_metadata(expected)?;
    ensure!(
        path.is_file()
            && file_identity(&path) == original.image_identity
            && file_identity(&current.metadata()?) == original.image_identity
            && file_identity(&original.image.metadata()?) == original.image_identity,
        "live daemon image is not the unchanged held file object"
    );
    let copy = fs::symlink_metadata(&original.retained_path)
        .context("completed retained daemon copy is unavailable")?;
    ensure!(
        copy.is_file()
            && file_identity(&copy) == original.retained_identity
            && file_identity(&original.retained.metadata()?) == original.retained_identity
            && copy.len() == original.image_identity.2,
        "completed retained daemon copy changed"
    );
    Ok(())
}

pub(super) fn retain_live_daemon(
    pid: u32,
    generation: u64,
    agent: &AgentFixture,
    directory: &Path,
    source: &Value,
    original: Option<&LiveDaemonImage>,
) -> Result<LiveDaemonImage> {
    let expected = support::fleet::agentd_binary()?.canonicalize()?;
    let process = PathBuf::from(format!("/proc/{pid}"));
    let start = start_ticks(&process)?;
    let argv = fs::read(process.join("cmdline"))?;
    let actual = fs::read_link(process.join("exe"))?;
    ensure!(
        actual == expected,
        "live Agentd executable differs from exact Cargo binary"
    );
    let mut image = fs::File::open(process.join("exe"))?;
    let before = image.metadata()?;
    ensure!(
        file_identity(&before) == file_identity(&fs::metadata(&expected)?),
        "Cargo path changed before live image capture"
    );
    let environment = fs::read(process.join("environ"))?;
    let selected = |key: &str| -> Option<String> {
        environment.split(|b| *b == 0).find_map(|line| {
            line.strip_prefix(format!("{key}=").as_bytes())
                .and_then(|v| std::str::from_utf8(v).ok())
                .map(str::to_owned)
        })
    };
    ensure!(
        selected("HEPTA_AGENT_ID").as_deref() == Some(agent.agent_id.as_str()),
        "live process belongs to another owner"
    );
    ensure!(
        selected("HEPTA_AGENT_GENERATION") == Some(generation.to_string()),
        "live process has another spawn generation"
    );
    ensure!(
        start_ticks(&process)? == start && fs::read(process.join("cmdline"))? == argv,
        "PID or argv changed while opening image"
    );
    ensure!(
        file_identity(&fs::metadata(process.join("exe"))?) == file_identity(&before),
        "PID executed a different image"
    );
    let (retained_path, retained, digest, method, original_pid, original_start) =
        if let Some(original) = original {
            verify_same_held_file_object(original, &image, &expected, source)?;
            // The held descriptor prevents inode reuse. This verifies the same
            // unchanged file object and completed copy; it is deliberately not
            // a second full hash/copy or proof against a privileged writer.
            (
                original.retained_path.clone(),
                original.retained.try_clone()?,
                original.record["sha256"].as_str().context("original image digest")?.to_owned(),
                "same-held-file-object-reuse",
                original.record["pid"].clone(),
                original.record["start_ticks"].clone(),
            )
        } else {
            let path = directory.join(format!("agentd-{pid}-{start}.elf"));
            let mut retained = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)?;
            let mut hash = Sha256::new();
            let mut buffer = [0; 1024 * 1024];
            loop {
                let read = image.read(&mut buffer)?;
                if read == 0 {
                    break;
                }
                hash.update(&buffer[..read]);
                retained.write_all(&buffer[..read])?;
            }
            retained.sync_all()?;
            fs::File::open(directory)?.sync_all()?;
            (
                path,
                retained,
                format!("{:x}", hash.finalize()),
                "first-live-fd-hash-copy",
                serde_json::json!(pid),
                serde_json::json!(start),
            )
        };
    ensure!(
        file_identity(&image.metadata()?) == file_identity(&before),
        "live executable changed while copied"
    );
    ensure!(
        start_ticks(&process)? == start && fs::read(process.join("cmdline"))? == argv,
        "process exited or changed during image capture"
    );
    ensure!(
        file_identity(&fs::metadata(process.join("exe"))?) == file_identity(&before),
        "process replaced its image during capture"
    );
    ensure!(
        file_identity(&fs::symlink_metadata(&expected)?) == file_identity(&before),
        "Cargo executable path changed during capture"
    );
    if let Some(original) = original {
        verify_same_held_file_object(original, &image, &expected, source)?;
    }
    let retained_identity = file_identity(&retained.metadata()?);
    ensure!(
        retained_identity.2 == before.len()
            && file_identity(&fs::symlink_metadata(&retained_path)?) == retained_identity,
        "retained executable copy is incomplete or replaced"
    );
    let record = serde_json::json!({"source":source,"pid":pid,"spawn_generation":generation,"start_ticks":start,
        "cargo_resolved_binary":expected,"actual_executable":actual,"retained_copy":retained_path,
        "sha256":digest,"bytes":before.len(),"device":before.dev(),"inode":before.ino(),
        "owner_and_generation_verified":true,"opened_fd_and_process_identity_verified":true,
        "capture_method":method,"full_hash_and_copy_this_capture":original.is_none(),
        "origin_capture_pid":original_pid,"origin_capture_start_ticks":original_start,
        "same_held_file_object_verified":original.is_some(),
        "scope":"owned live image with no concurrent build; file-object metadata stability is not a hostile privileged-writer guarantee"});
    Ok(LiveDaemonImage {
        image,
        image_identity: file_identity(&before),
        retained,
        retained_identity,
        retained_path,
        record,
    })
}

#[test]
fn held_daemon_image_reuse_refuses_wrong_changed_or_missing_files() -> Result<()> {
    for mutation in ["different_file_object", "changed_held_image", "missing_copy"] {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("image");
        let copy = directory.path().join("retained");
        let bytes = b"controlled file-identity fixture, not an executable";
        fs::write(&path, bytes)?;
        fs::write(&copy, bytes)?;
        let image = fs::File::open(&path)?;
        let retained = fs::File::open(&copy)?;
        let source = serde_json::json!({"scope":"synthetic file-identity control only"});
        let original = LiveDaemonImage {
            image_identity: file_identity(&image.metadata()?),
            retained_identity: file_identity(&retained.metadata()?),
            image,
            retained,
            retained_path: copy.clone(),
            record: serde_json::json!({"source":source}),
        };
        let mut current = fs::File::open(&path)?;
        verify_same_held_file_object(&original, &current, &path, &source)?;
        match mutation {
            "different_file_object" => {
                let different = directory.path().join("same-bytes-other-inode");
                fs::write(&different, bytes)?;
                current = fs::File::open(&different)?;
            }
            "changed_held_image" => {
                let mut writer = fs::OpenOptions::new().append(true).open(&path)?;
                writer.write_all(b" changed")?;
                writer.sync_all()?;
            }
            "missing_copy" => fs::remove_file(&copy)?,
            _ => unreachable!(),
        }
        ensure!(
            verify_same_held_file_object(&original, &current, &path, &source).is_err(),
            "same-file-object reuse admitted {mutation}"
        );
    }
    Ok(())
}
