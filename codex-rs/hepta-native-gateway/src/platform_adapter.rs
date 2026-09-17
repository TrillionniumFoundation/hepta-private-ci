use std::collections::HashMap;
use std::collections::HashSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Mutex;
use std::sync::PoisonError;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;

use super::shell_runtime::InvokeObservation;
use super::shell_runtime::PermissionDecision;
use super::shell_runtime::PlatformAction;
use super::shell_runtime::PlatformAdapter;
use super::shell_runtime::PlatformRequest;
use super::shell_runtime::ReconcileObservation;
use super::shell_runtime::SessionKey;
use super::shell_runtime::TerminalStatus;

const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;
const MAX_JOURNAL_RECORDS: usize = 8192;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum NativePlatform {
    Windows,
    Macos,
    Linux,
    Unsupported,
}

impl NativePlatform {
    pub(crate) const fn current() -> Self {
        if cfg!(target_os = "windows") {
            Self::Windows
        } else if cfg!(target_os = "macos") {
            Self::Macos
        } else if cfg!(target_os = "linux") {
            Self::Linux
        } else {
            Self::Unsupported
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct PlatformMatrix {
    pub(crate) platform: NativePlatform,
    pub(crate) open_path: bool,
    pub(crate) reveal_path: bool,
    pub(crate) copy_text: bool,
    pub(crate) notify: bool,
}

pub(crate) const fn platform_matrix(platform: NativePlatform) -> PlatformMatrix {
    match platform {
        NativePlatform::Windows => PlatformMatrix {
            platform,
            open_path: true,
            reveal_path: true,
            copy_text: true,
            notify: false,
        },
        NativePlatform::Macos | NativePlatform::Linux => PlatformMatrix {
            platform,
            open_path: true,
            reveal_path: true,
            copy_text: true,
            notify: true,
        },
        NativePlatform::Unsupported => PlatformMatrix {
            platform,
            open_path: false,
            reveal_path: false,
            copy_text: false,
            notify: false,
        },
    }
}

#[derive(Clone, Debug, Default)]
pub(crate) struct PlatformPolicy {
    allowed: HashSet<PlatformAction>,
}

impl PlatformPolicy {
    pub(crate) fn allow(actions: impl IntoIterator<Item = PlatformAction>) -> Self {
        Self {
            allowed: actions.into_iter().collect(),
        }
    }

    fn permits(&self, action: PlatformAction) -> bool {
        self.allowed.contains(&action)
    }
}

pub(crate) trait EffectExecutor: Send + Sync {
    fn execute(&self, platform: NativePlatform, request: &PlatformRequest) -> Result<EffectResult>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum EffectResult {
    NotStarted,
    Indeterminate,
    Terminal(TerminalStatus),
}

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct OsCommandExecutor;

impl EffectExecutor for OsCommandExecutor {
    fn execute(&self, platform: NativePlatform, request: &PlatformRequest) -> Result<EffectResult> {
        if !action_supported(platform_matrix(platform), request.action) {
            return Ok(EffectResult::NotStarted);
        }
        match request.action {
            PlatformAction::OpenPath => execute_open(platform, &request.resource),
            PlatformAction::RevealPath => execute_reveal(platform, &request.resource),
            PlatformAction::CopyText => execute_copy(platform, &request.resource),
            PlatformAction::Notify => execute_notify(platform, &request.resource),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct JournalKey {
    session_id: String,
    generation: u64,
    operation_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum JournalEntry {
    Prepared {
        action: PlatformAction,
        payload_digest: String,
    },
    Terminal {
        action: PlatformAction,
        payload_digest: String,
        status: TerminalStatus,
    },
}

struct Journal {
    path: PathBuf,
    entries: HashMap<JournalKey, JournalEntry>,
    records: usize,
}

impl Journal {
    fn open(path: PathBuf) -> Result<Self> {
        validate_journal_permissions(&path)?;
        let mut journal = Self {
            path,
            entries: HashMap::new(),
            records: 0,
        };
        if journal.path.exists() {
            let file = File::open(&journal.path).context("open native effect journal")?;
            if file.metadata()?.len() > MAX_JOURNAL_BYTES {
                bail!("native effect journal exceeds {MAX_JOURNAL_BYTES} bytes");
            }
            for line in BufReader::new(file).lines() {
                let line = line.context("read native effect journal")?;
                journal.replay(&line)?;
            }
        }
        Ok(journal)
    }

    fn replay(&mut self, line: &str) -> Result<()> {
        self.records += 1;
        if self.records > MAX_JOURNAL_RECORDS {
            bail!("native effect journal exceeds {MAX_JOURNAL_RECORDS} records");
        }
        let fields = line.split('|').collect::<Vec<_>>();
        match fields.as_slice() {
            ["P", session_id, generation, operation_id, action, payload_digest] => {
                let key = journal_key(session_id, generation, operation_id)?;
                if self.entries.contains_key(&key) {
                    bail!("native effect journal repeats a prepared operation");
                }
                self.entries.insert(
                    key,
                    JournalEntry::Prepared {
                        action: parse_action(action)?,
                        payload_digest: validate_digest(payload_digest)?.to_string(),
                    },
                );
            }
            ["T", session_id, generation, operation_id, action, payload_digest, status] => {
                let key = journal_key(session_id, generation, operation_id)?;
                let action = parse_action(action)?;
                let payload_digest = validate_digest(payload_digest)?.to_string();
                let expected = self.entries.get(&key).context("terminal journal entry has no prepared intent")?;
                if !entry_matches(expected, action, &payload_digest) {
                    bail!("terminal journal entry does not match prepared intent");
                }
                self.entries.insert(
                    key,
                    JournalEntry::Terminal {
                        action,
                        payload_digest,
                        status: parse_status(status)?,
                    },
                );
            }
            _ => bail!("native effect journal record is malformed"),
        }
        Ok(())
    }

    fn append(&mut self, line: String, key: JournalKey, entry: JournalEntry) -> Result<()> {
        if self.records >= MAX_JOURNAL_RECORDS {
            bail!("native effect journal is at record capacity");
        }
        let current_bytes = self.path.metadata().map(|value| value.len()).unwrap_or(0);
        if current_bytes.saturating_add(line.len() as u64 + 1) > MAX_JOURNAL_BYTES {
            bail!("native effect journal is at byte capacity");
        }
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).context("create native effect journal parent")?;
        }
        let mut file = secure_append(&self.path)?;
        writeln!(file, "{line}").context("append native effect journal")?;
        file.flush().context("flush native effect journal")?;
        file.sync_all().context("sync native effect journal")?;
        self.records += 1;
        self.entries.insert(key, entry);
        Ok(())
    }
}

pub(crate) struct DurablePlatformAdapter<E> {
    platform: NativePlatform,
    policy: PlatformPolicy,
    executor: E,
    journal: Mutex<Journal>,
}

impl<E> DurablePlatformAdapter<E>
where
    E: EffectExecutor,
{
    pub(crate) fn open(
        platform: NativePlatform,
        policy: PlatformPolicy,
        executor: E,
        journal_path: PathBuf,
    ) -> Result<Self> {
        Ok(Self {
            platform,
            policy,
            executor,
            journal: Mutex::new(Journal::open(journal_path)?),
        })
    }
}

impl<E> PlatformAdapter for DurablePlatformAdapter<E>
where
    E: EffectExecutor,
{
    fn permission(&self, request: &PlatformRequest) -> Result<PermissionDecision> {
        if !self.policy.permits(request.action)
            || !action_supported(platform_matrix(self.platform), request.action)
        {
            return Ok(PermissionDecision::Denied {
                outcome_digest: request.payload_digest.clone(),
            });
        }
        Ok(PermissionDecision::Allowed)
    }

    fn reconcile(
        &self,
        session: &SessionKey,
        request: &PlatformRequest,
    ) -> Result<ReconcileObservation> {
        let key = JournalKey {
            session_id: session.session_id.clone(),
            generation: session.generation,
            operation_id: request.operation_id.clone(),
        };
        let journal = self
            .journal
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        match journal.entries.get(&key) {
            None => Ok(ReconcileObservation::NotFound),
            Some(entry) if !entry_matches(entry, request.action, &request.payload_digest) => {
                bail!("durable platform operation identity was reused with changed payload")
            }
            Some(JournalEntry::Prepared { .. }) => Ok(ReconcileObservation::Indeterminate),
            Some(JournalEntry::Terminal { status, .. }) => Ok(ReconcileObservation::Terminal {
                status: *status,
                outcome_digest: request.payload_digest.clone(),
            }),
        }
    }

    fn invoke(&self, session: &SessionKey, request: &PlatformRequest) -> Result<InvokeObservation> {
        let key = JournalKey {
            session_id: session.session_id.clone(),
            generation: session.generation,
            operation_id: request.operation_id.clone(),
        };
        {
            let mut journal = self
                .journal
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            if journal.entries.contains_key(&key) {
                bail!("platform invoke requires an operation not already present in the journal");
            }
            journal.append(
                format!(
                    "P|{}|{}|{}|{}|{}",
                    session.session_id,
                    session.generation,
                    request.operation_id,
                    action_name(request.action),
                    request.payload_digest
                ),
                key.clone(),
                JournalEntry::Prepared {
                    action: request.action,
                    payload_digest: request.payload_digest.clone(),
                },
            )?;
        }

        let status = match self.executor.execute(self.platform, request)? {
            EffectResult::Indeterminate => return Ok(InvokeObservation::Indeterminate),
            EffectResult::NotStarted => TerminalStatus::Failed,
            EffectResult::Terminal(status) => status,
        };

        let mut journal = self
            .journal
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        journal.append(
            format!(
                "T|{}|{}|{}|{}|{}|{}",
                session.session_id,
                session.generation,
                request.operation_id,
                action_name(request.action),
                request.payload_digest,
                status_name(status)
            ),
            key,
            JournalEntry::Terminal {
                action: request.action,
                payload_digest: request.payload_digest.clone(),
                status,
            },
        )?;
        Ok(InvokeObservation::Terminal {
            status,
            outcome_digest: request.payload_digest.clone(),
        })
    }
}

fn action_supported(matrix: PlatformMatrix, action: PlatformAction) -> bool {
    match action {
        PlatformAction::OpenPath => matrix.open_path,
        PlatformAction::RevealPath => matrix.reveal_path,
        PlatformAction::CopyText => matrix.copy_text,
        PlatformAction::Notify => matrix.notify,
    }
}

fn execute_open(platform: NativePlatform, resource: &str) -> Result<EffectResult> {
    let mut command = match platform {
        NativePlatform::Windows => {
            let mut value = Command::new("explorer.exe");
            value.arg(resource);
            value
        }
        NativePlatform::Macos => {
            let mut value = Command::new("open");
            value.arg(resource);
            value
        }
        NativePlatform::Linux => {
            let mut value = Command::new("xdg-open");
            value.arg(resource);
            value
        }
        NativePlatform::Unsupported => return Ok(EffectResult::NotStarted),
    };
    execute_child(&mut command, None)
}

fn execute_reveal(platform: NativePlatform, resource: &str) -> Result<EffectResult> {
    let mut command = match platform {
        NativePlatform::Windows => {
            let mut value = Command::new("explorer.exe");
            value.arg(format!("/select,{resource}"));
            value
        }
        NativePlatform::Macos => {
            let mut value = Command::new("open");
            value.arg("-R").arg(resource);
            value
        }
        NativePlatform::Linux => {
            let parent = Path::new(resource).parent().unwrap_or_else(|| Path::new(resource));
            let mut value = Command::new("xdg-open");
            value.arg(parent);
            value
        }
        NativePlatform::Unsupported => return Ok(EffectResult::NotStarted),
    };
    execute_child(&mut command, None)
}

fn execute_copy(platform: NativePlatform, resource: &str) -> Result<EffectResult> {
    let mut command = match platform {
        NativePlatform::Windows => {
            let mut value = Command::new("powershell.exe");
            value.args(["-NoProfile", "-NonInteractive", "-Command", "$input | Set-Clipboard"]);
            value
        }
        NativePlatform::Macos => Command::new("pbcopy"),
        NativePlatform::Linux => {
            let mut value = Command::new("sh");
            value.args(["-c", "if command -v wl-copy >/dev/null 2>&1; then wl-copy; else xclip -selection clipboard; fi"]);
            value
        }
        NativePlatform::Unsupported => return Ok(EffectResult::NotStarted),
    };
    execute_child(&mut command, Some(resource.as_bytes()))
}

fn execute_notify(platform: NativePlatform, resource: &str) -> Result<EffectResult> {
    let mut command = match platform {
        NativePlatform::Macos => {
            let mut value = Command::new("osascript");
            value.args([
                "-e",
                "on run argv",
                "-e",
                "display notification (item 1 of argv) with title \"Hepta\"",
                "-e",
                "end run",
                "--",
                resource,
            ]);
            value
        }
        NativePlatform::Linux => {
            let mut value = Command::new("notify-send");
            value.args(["Hepta", resource]);
            value
        }
        NativePlatform::Windows | NativePlatform::Unsupported => {
            return Ok(EffectResult::NotStarted);
        }
    };
    execute_child(&mut command, None)
}

fn execute_child(command: &mut Command, stdin: Option<&[u8]>) -> Result<EffectResult> {
    if stdin.is_some() {
        command.stdin(Stdio::piped());
    }
    command.stdout(Stdio::null()).stderr(Stdio::null());
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(_) => return Ok(EffectResult::NotStarted),
    };
    if let Some(bytes) = stdin {
        let Some(mut input) = child.stdin.take() else {
            return Ok(EffectResult::Indeterminate);
        };
        if input.write_all(bytes).is_err() {
            return Ok(EffectResult::Indeterminate);
        }
    }
    wait_child(&mut child)
}

fn wait_child(child: &mut Child) -> Result<EffectResult> {
    match child.wait() {
        Ok(status) if status.success() => Ok(EffectResult::Terminal(TerminalStatus::Succeeded)),
        Ok(_) => Ok(EffectResult::Terminal(TerminalStatus::Failed)),
        Err(_) => Ok(EffectResult::Indeterminate),
    }
}

fn journal_key(session_id: &str, generation: &str, operation_id: &str) -> Result<JournalKey> {
    Ok(JournalKey {
        session_id: validate_id(session_id)?.to_string(),
        generation: generation.parse::<u64>().context("parse journal generation")?,
        operation_id: validate_id(operation_id)?.to_string(),
    })
}

fn entry_matches(entry: &JournalEntry, action: PlatformAction, payload_digest: &str) -> bool {
    match entry {
        JournalEntry::Prepared {
            action: stored_action,
            payload_digest: stored_digest,
        }
        | JournalEntry::Terminal {
            action: stored_action,
            payload_digest: stored_digest,
            ..
        } => *stored_action == action && stored_digest == payload_digest,
    }
}

fn action_name(action: PlatformAction) -> &'static str {
    match action {
        PlatformAction::OpenPath => "open_path",
        PlatformAction::RevealPath => "reveal_path",
        PlatformAction::CopyText => "copy_text",
        PlatformAction::Notify => "notify",
    }
}

fn parse_action(value: &str) -> Result<PlatformAction> {
    match value {
        "open_path" => Ok(PlatformAction::OpenPath),
        "reveal_path" => Ok(PlatformAction::RevealPath),
        "copy_text" => Ok(PlatformAction::CopyText),
        "notify" => Ok(PlatformAction::Notify),
        _ => bail!("journal action is not registered"),
    }
}

fn status_name(status: TerminalStatus) -> &'static str {
    match status {
        TerminalStatus::Succeeded => "succeeded",
        TerminalStatus::Failed => "failed",
    }
}

fn parse_status(value: &str) -> Result<TerminalStatus> {
    match value {
        "succeeded" => Ok(TerminalStatus::Succeeded),
        "failed" => Ok(TerminalStatus::Failed),
        _ => bail!("journal terminal status is not registered"),
    }
}

fn validate_id(value: &str) -> Result<&str> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        bail!("journal stable identifier is invalid");
    }
    Ok(value)
}

fn validate_digest(value: &str) -> Result<&str> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value.bytes().all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        bail!("journal digest is invalid");
    }
    Ok(value)
}

fn secure_append(path: &Path) -> Result<File> {
    let mut options = OpenOptions::new();
    options.create(true).append(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path).context("open native effect journal for append")
}

fn validate_journal_permissions(path: &Path) -> Result<()> {
    if !path.exists() {
        return Ok(());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if path.metadata()?.permissions().mode() & 0o077 != 0 {
            bail!("native effect journal must not be group/world accessible");
        }
    }
    Ok(())
}
