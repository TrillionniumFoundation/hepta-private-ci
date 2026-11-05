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

pub(super) fn retain_live_daemon(
    pid: u32,
    generation: u64,
    agent: &AgentFixture,
    directory: &Path,
    source: &Value,
) -> Result<Value> {
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
    let temporary = directory.join(format!("agentd-{pid}-{start}.elf"));
    let mut retained = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
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
    let digest = format!("{:x}", hash.finalize());
    Ok(
        serde_json::json!({"source":source,"pid":pid,"spawn_generation":generation,"start_ticks":start,
        "cargo_resolved_binary":expected,"actual_executable":actual,"retained_copy":temporary,
        "sha256":digest,"bytes":before.len(),"device":before.dev(),"inode":before.ino(),
        "owner_and_generation_verified":true,"opened_fd_and_process_identity_verified":true}),
    )
}
