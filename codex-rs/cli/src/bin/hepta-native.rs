use std::ffi::OsString;
use std::fs;
use std::io::Read;
use std::io::Write;
use std::io::stdout;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use clap::Parser;
use codex_hepta_native_gateway::native_product::NativeAction;
use codex_hepta_native_gateway::native_product::NativeActionReceipt;
use codex_hepta_native_gateway::native_product::NativeActionRequest;
use codex_hepta_native_gateway::native_product::NativeCapabilitySet;
use codex_hepta_native_gateway::native_product::NativeProduct;
use codex_hepta_native_gateway::native_product::NativeProductConfig;
use codex_hepta_native_gateway::native_product::NativeSnapshot;
use codex_hepta_native_gateway::native_product::NativeUpdateRequest;
use codex_hepta_native_gateway::native_product::NativeUpdateStatus;
use codex_hepta_native_gateway::update_activation::artifact_digest;
use crossterm::cursor::Hide;
use crossterm::cursor::MoveTo;
use crossterm::cursor::Show;
use crossterm::event;
use crossterm::event::Event;
use crossterm::event::KeyCode;
use crossterm::event::KeyEventKind;
use crossterm::event::KeyModifiers;
use crossterm::execute;
use crossterm::queue;
use crossterm::style::Attribute;
use crossterm::style::Print;
use crossterm::style::SetAttribute;
use crossterm::terminal;
use crossterm::terminal::Clear;
use crossterm::terminal::ClearType;
use crossterm::terminal::EnterAlternateScreen;
use crossterm::terminal::LeaveAlternateScreen;
use serde::Deserialize;

const MAX_UPDATE_MANIFEST_BYTES: u64 = 64 * 1024;

#[derive(Debug, Parser)]
#[command(
    name = "hepta-native",
    about = "Hepta all-Rust native application shell"
)]
struct Args {
    #[arg(long, env = "HEPTA_NATIVE_MANIFEST_DIGEST")]
    manifest_digest: String,
    #[arg(long, env = "HEPTA_NATIVE_GRANT_PUBLIC_KEY")]
    grant_public_key: PathBuf,
    #[arg(long, env = "HEPTA_NATIVE_RELEASE_PUBLIC_KEY")]
    release_public_key: PathBuf,
    #[arg(long, env = "HEPTA_NATIVE_SELECTION_PUBLIC_KEY")]
    selection_public_key: PathBuf,
    #[arg(long)]
    effect_journal: Option<PathBuf>,
    #[arg(long)]
    update_journal: Option<PathBuf>,
    #[arg(long)]
    rollback_artifact: Option<PathBuf>,
    #[arg(long)]
    stage_artifact: Option<PathBuf>,
    #[arg(long)]
    windows_dpapi_session_path: Option<PathBuf>,
    #[arg(long)]
    allow_open_path: bool,
    #[arg(long)]
    allow_reveal_path: bool,
    #[arg(long)]
    allow_copy_text: bool,
    #[arg(long)]
    allow_notify: bool,
    #[arg(long)]
    no_session_persistence: bool,
    #[arg(long)]
    accessible: bool,
    #[arg(long, hide = true)]
    update_confirm_file: Option<PathBuf>,
    #[arg(long, hide = true)]
    update_expected_digest: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Page {
    Overview,
    Operations,
    Update,
    Help,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum EditField {
    OperationId,
    Resource,
    PayloadDigest,
    SignedGrant,
    UpdateManifest,
}

#[derive(Debug)]
struct AppState {
    page: Page,
    focus: usize,
    edit: Option<EditField>,
    edit_buffer: String,
    action: NativeAction,
    operation_id: String,
    resource: String,
    payload_digest: String,
    signed_grant: String,
    update_manifest: String,
    snapshot: NativeSnapshot,
    last_action: Option<NativeActionReceipt>,
    message: String,
    locale: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct UpdateManifest {
    package_path: PathBuf,
    package_digest: String,
    predecessor_digest: String,
    evidence_digest: String,
    producer_id: String,
    selector_id: String,
    release_signature_path: PathBuf,
    selection_signature_path: PathBuf,
}

struct TerminalGuard {
    active: bool,
}

impl TerminalGuard {
    fn enter() -> Result<Self> {
        terminal::enable_raw_mode().context("enable native shell raw mode")?;
        execute!(stdout(), EnterAlternateScreen, Hide).context("enter native shell screen")?;
        Ok(Self { active: true })
    }
}

impl Drop for TerminalGuard {
    fn drop(&mut self) {
        if self.active {
            let _ = execute!(stdout(), Show, LeaveAlternateScreen);
            let _ = terminal::disable_raw_mode();
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    if args.update_confirm_file.is_some() != args.update_expected_digest.is_some() {
        bail!("native update confirmation requires both hidden confirmation arguments");
    }
    let state_root = absolute_state_root()?;
    let native_root = state_root.join("native-shell");
    fs::create_dir_all(&native_root).context("create native shell state directory")?;
    let active_artifact = std::env::current_exe().context("resolve hepta-native executable")?;
    let config = NativeProductConfig {
        manifest_digest: args.manifest_digest,
        grant_public_key: absolute(args.grant_public_key, "grant public key")?,
        release_public_key: absolute(args.release_public_key, "release public key")?,
        selection_public_key: absolute(args.selection_public_key, "selection public key")?,
        effect_journal: args
            .effect_journal
            .unwrap_or_else(|| native_root.join("effects.journal")),
        update_journal: args
            .update_journal
            .unwrap_or_else(|| native_root.join("updates.journal")),
        active_artifact,
        rollback_artifact: args
            .rollback_artifact
            .unwrap_or_else(|| native_root.join("hepta-native.rollback")),
        stage_artifact: args
            .stage_artifact
            .unwrap_or_else(|| native_root.join("hepta-native.stage")),
        windows_dpapi_session_path: args
            .windows_dpapi_session_path
            .unwrap_or_else(|| native_root.join("session.dpapi")),
        capabilities: NativeCapabilitySet {
            open_path: args.allow_open_path,
            reveal_path: args.allow_reveal_path,
            copy_text: args.allow_copy_text,
            notify: args.allow_notify,
        },
        persist_session_reference: !args.no_session_persistence,
    };
    let restart_config = config.clone();
    let mut product = NativeProduct::open_from_env(config).await?;
    confirm_restarted_update(
        &product,
        &restart_config.active_artifact,
        args.update_confirm_file.as_deref(),
        args.update_expected_digest.as_deref(),
    )?;
    let snapshot = product.refresh()?;
    let locale = sys_locale::get_locale().unwrap_or_else(|| "en-US".to_string());
    if args.accessible {
        let result = run_accessible(&mut product, snapshot, locale);
        product.close()?;
        return result;
    }
    let result = run_full_screen(&mut product, snapshot, locale, &restart_config);
    product.close()?;
    result
}

fn confirm_restarted_update(
    product: &NativeProduct,
    active_artifact: &Path,
    confirm_file: Option<&Path>,
    expected_digest: Option<&str>,
) -> Result<()> {
    let (Some(confirm_file), Some(expected_digest)) = (confirm_file, expected_digest) else {
        return Ok(());
    };
    if !confirm_file.is_absolute() {
        bail!("native update confirmation path must be absolute");
    }
    let running_digest = artifact_digest(active_artifact)?;
    if running_digest != expected_digest {
        bail!("restarted native artifact does not match the staged package digest");
    }
    let status = product.recover_or_confirm_update(&running_digest)?;
    if status != NativeUpdateStatus::Confirmed {
        bail!("restarted native artifact was not confirmed: {status:?}");
    }
    write_confirmation(confirm_file, &running_digest)
}

fn write_confirmation(path: &Path, digest: &str) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).context("create native update confirmation parent")?;
    }
    let mut options = fs::OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(path)
        .context("create native update confirmation")?;
    writeln!(file, "{digest}").context("write native update confirmation")?;
    file.flush().context("flush native update confirmation")?;
    file.sync_all().context("sync native update confirmation")
}

fn run_full_screen(
    product: &mut NativeProduct,
    snapshot: NativeSnapshot,
    locale: String,
    restart_config: &NativeProductConfig,
) -> Result<()> {
    let _guard = TerminalGuard::enter()?;
    let mut app = AppState {
        page: Page::Overview,
        focus: 0,
        edit: None,
        edit_buffer: String::new(),
        action: NativeAction::OpenPath,
        operation_id: String::new(),
        resource: String::new(),
        payload_digest: String::new(),
        signed_grant: String::new(),
        update_manifest: String::new(),
        snapshot,
        last_action: None,
        message: "Ready".to_string(),
        locale,
    };
    loop {
        render(&app)?;
        if !event::poll(Duration::from_millis(250))? {
            continue;
        }
        match event::read()? {
            Event::Resize(_, _) => {}
            Event::Key(key) if key.kind == KeyEventKind::Press => {
                if edit_event(&mut app, key.code, key.modifiers) {
                    continue;
                }
                if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('c') {
                    return Ok(());
                }
                match key.code {
                    KeyCode::Char('q') | KeyCode::Esc => return Ok(()),
                    KeyCode::Char('1') => set_page(&mut app, Page::Overview),
                    KeyCode::Char('2') => set_page(&mut app, Page::Operations),
                    KeyCode::Char('3') => set_page(&mut app, Page::Update),
                    KeyCode::Char('4') => set_page(&mut app, Page::Help),
                    KeyCode::Tab => app.focus = (app.focus + 1) % focus_count(app.page),
                    KeyCode::BackTab => {
                        let count = focus_count(app.page);
                        app.focus = (app.focus + count - 1) % count;
                    }
                    KeyCode::Left | KeyCode::Right
                        if app.page == Page::Operations && app.focus == 0 =>
                    {
                        app.action = next_action(app.action);
                    }
                    KeyCode::Enter => begin_edit(&mut app),
                    KeyCode::Char('x') if app.page == Page::Operations => {
                        execute_action(product, &mut app)
                    }
                    KeyCode::Char('u') if app.page == Page::Update => {
                        if execute_update(product, &mut app, restart_config)? {
                            return Ok(());
                        }
                    }
                    KeyCode::Char('r') => match product.refresh() {
                        Ok(snapshot) => {
                            app.snapshot = snapshot;
                            app.message = "Runtime view refreshed".to_string();
                        }
                        Err(error) => app.message = format!("Refresh failed: {error:#}"),
                    },
                    _ => {}
                }
            }
            _ => {}
        }
    }
}

fn render(app: &AppState) -> Result<()> {
    let (width, height) = terminal::size()?;
    let mut out = stdout();
    queue!(out, MoveTo(0, 0), Clear(ClearType::All))?;
    line(
        &mut out,
        0,
        width,
        "Hepta Native — Rust / Win + macOS + Linux",
    )?;
    line(
        &mut out,
        1,
        width,
        &format!(
            "[1 Overview] [2 Operations] [3 Update] [4 Help]  page={}  locale={}",
            page_name(app.page),
            app.locale
        ),
    )?;
    line(&mut out, 2, width, &format!("Status: {}", app.message))?;
    line(
        &mut out,
        3,
        width,
        "────────────────────────────────────────────────",
    )?;
    match app.page {
        Page::Overview => render_overview(&mut out, app, width, height)?,
        Page::Operations => render_operations(&mut out, app, width, height)?,
        Page::Update => render_update(&mut out, app, width, height)?,
        Page::Help => render_help(&mut out, width, height)?,
    }
    let footer = "Tab/Shift-Tab focus  Enter edit  r refresh  q quit";
    line(&mut out, height.saturating_sub(1), width, footer)?;
    out.flush()?;
    Ok(())
}

fn render_overview(
    out: &mut impl Write,
    app: &AppState,
    width: u16,
    _height: u16,
) -> Result<()> {
    let snapshot = &app.snapshot;
    for (row, text) in [
        format!("Platform             {}", snapshot.platform),
        format!("Runtime              {}", snapshot.runtime_status),
        format!(
            "Session              {} / gen {}",
            snapshot.session_id, snapshot.session_generation
        ),
        format!(
            "View                 gen {} / rev {}",
            snapshot.view_generation, snapshot.view_revision
        ),
        format!("Schema               v{}", snapshot.schema_version),
        format!("Integrity verified   {}", snapshot.integrity_verified),
        format!("Authority closed     {}", snapshot.authority_closed),
        format!("Modules              {}", snapshot.modules.join(", ")),
    ]
    .into_iter()
    .enumerate()
    {
        line(out, 5 + row as u16, width, &text)?;
    }
    Ok(())
}

fn render_operations(
    out: &mut impl Write,
    app: &AppState,
    width: u16,
    _height: u16,
) -> Result<()> {
    let fields = [
        format!("Action          {:?}", app.action),
        format!(
            "Operation ID    {}",
            value_or_empty(&app.operation_id)
        ),
        format!("Resource        {}", value_or_empty(&app.resource)),
        format!(
            "Payload digest  {}",
            compact_secret(&app.payload_digest)
        ),
        format!("Signed grant    {}", hidden_value(&app.signed_grant)),
    ];
    for (index, text) in fields.into_iter().enumerate() {
        focus_line(out, 5 + index as u16, width, index == app.focus, &text)?;
    }
    line(
        out,
        11,
        width,
        "Press x to execute/reconcile the operation. Indeterminate is never replayed.",
    )?;
    if let Some(receipt) = &app.last_action {
        line(
            out,
            13,
            width,
            &format!(
                "Last receipt: {} {:?}, terminal={}, outcome={}",
                receipt.operation_id,
                receipt.status,
                receipt.terminal_observed,
                receipt
                    .outcome_digest
                    .as_deref()
                    .map(compact_secret)
                    .unwrap_or_else(|| "—".to_string())
            ),
        )?;
    }
    render_editor(out, app, width, 15)
}

fn render_update(
    out: &mut impl Write,
    app: &AppState,
    width: u16,
    _height: u16,
) -> Result<()> {
    focus_line(
        out,
        5,
        width,
        app.focus == 0,
        &format!(
            "Signed update manifest  {}",
            value_or_empty(&app.update_manifest)
        ),
    )?;
    line(
        out,
        7,
        width,
        "Manifest fields: package/digests/evidence/producer/selector/release+selection signatures.",
    )?;
    line(
        out,
        8,
        width,
        "Press u to verify, stage, hand off to helper and exit.",
    )?;
    line(
        out,
        9,
        width,
        "Helper activates after exit; unconfirmed restart restores predecessor.",
    )?;
    render_editor(out, app, width, 12)
}

fn render_help(out: &mut impl Write, width: u16, _height: u16) -> Result<()> {
    for (row, text) in [
        "Security: signed grants bind session, generation, operation, final payload and expiry.",
        "Effects: durable intent is fsynced before OS invocation; uncertain effects stay indeterminate.",
        "Updates: release and independent-selection signatures are both required; rollback is durable.",
        "Accessibility: use --accessible for a screen-reader-friendly line interface.",
        "DPI/resize: layout follows terminal dimensions; no pixel-size or fixed-font assumptions.",
        "No model/tool/network authority is minted by this application shell.",
    ]
    .into_iter()
    .enumerate()
    {
        line(out, 5 + row as u16, width, text)?;
    }
    Ok(())
}

fn render_editor(out: &mut impl Write, app: &AppState, width: u16, row: u16) -> Result<()> {
    if let Some(field) = app.edit {
        let value = if field == EditField::SignedGrant {
            hidden_value(&app.edit_buffer)
        } else {
            app.edit_buffer.clone()
        };
        line(out, row, width, &format!("Editing {field:?}: {value}"))?;
        line(
            out,
            row + 1,
            width,
            "Enter save  Esc cancel  Backspace delete",
        )?;
    }
    Ok(())
}

fn edit_event(app: &mut AppState, code: KeyCode, modifiers: KeyModifiers) -> bool {
    let Some(field) = app.edit else {
        return false;
    };
    match code {
        KeyCode::Enter => {
            assign_edit(app, field);
            app.edit = None;
            app.edit_buffer.clear();
        }
        KeyCode::Esc => {
            app.edit = None;
            app.edit_buffer.clear();
        }
        KeyCode::Backspace => {
            app.edit_buffer.pop();
        }
        KeyCode::Char(character) if !modifiers.contains(KeyModifiers::CONTROL) => {
            if app.edit_buffer.len() < 16 * 1024 {
                app.edit_buffer.push(character);
            }
        }
        _ => {}
    }
    true
}

fn begin_edit(app: &mut AppState) {
    let field = match (app.page, app.focus) {
        (Page::Operations, 1) => Some(EditField::OperationId),
        (Page::Operations, 2) => Some(EditField::Resource),
        (Page::Operations, 3) => Some(EditField::PayloadDigest),
        (Page::Operations, 4) => Some(EditField::SignedGrant),
        (Page::Update, 0) => Some(EditField::UpdateManifest),
        _ => None,
    };
    let Some(field) = field else {
        return;
    };
    app.edit_buffer = match field {
        EditField::OperationId => app.operation_id.clone(),
        EditField::Resource => app.resource.clone(),
        EditField::PayloadDigest => app.payload_digest.clone(),
        EditField::SignedGrant => app.signed_grant.clone(),
        EditField::UpdateManifest => app.update_manifest.clone(),
    };
    app.edit = Some(field);
}

fn assign_edit(app: &mut AppState, field: EditField) {
    match field {
        EditField::OperationId => app.operation_id.clone_from(&app.edit_buffer),
        EditField::Resource => app.resource.clone_from(&app.edit_buffer),
        EditField::PayloadDigest => app.payload_digest.clone_from(&app.edit_buffer),
        EditField::SignedGrant => app.signed_grant.clone_from(&app.edit_buffer),
        EditField::UpdateManifest => app.update_manifest.clone_from(&app.edit_buffer),
    }
}

fn execute_action(product: &mut NativeProduct, app: &mut AppState) {
    match product.request_platform_action(NativeActionRequest {
        operation_id: app.operation_id.clone(),
        action: app.action,
        resource: app.resource.clone(),
        displayed_revision: app.snapshot.view_revision,
        payload_digest: app.payload_digest.clone(),
        signed_grant: app.signed_grant.clone(),
    }) {
        Ok(receipt) => {
            app.message = format!("Operation {:?}", receipt.status);
            app.last_action = Some(receipt);
        }
        Err(error) => app.message = format!("Operation rejected: {error:#}"),
    }
}

fn execute_update(
    product: &NativeProduct,
    app: &mut AppState,
    restart_config: &NativeProductConfig,
) -> Result<bool> {
    let result = (|| -> Result<()> {
        let path = absolute(PathBuf::from(&app.update_manifest), "update manifest")?;
        let metadata = path.metadata().context("inspect native update manifest")?;
        if !metadata.is_file() || metadata.len() > MAX_UPDATE_MANIFEST_BYTES {
            bail!("update manifest must be a file <= {MAX_UPDATE_MANIFEST_BYTES} bytes");
        }
        let mut text = String::new();
        fs::File::open(&path)?.read_to_string(&mut text)?;
        let manifest: UpdateManifest = serde_json::from_str(&text)?;
        let package_digest = manifest.package_digest.clone();
        let predecessor_digest = manifest.predecessor_digest.clone();
        let status = product.apply_update(NativeUpdateRequest {
            package_path: absolute(manifest.package_path, "update package")?,
            package_digest: manifest.package_digest,
            predecessor_digest: manifest.predecessor_digest,
            evidence_digest: manifest.evidence_digest,
            producer_id: manifest.producer_id,
            selector_id: manifest.selector_id,
            release_signature_path: absolute(
                manifest.release_signature_path,
                "release signature",
            )?,
            selection_signature_path: absolute(
                manifest.selection_signature_path,
                "selection signature",
            )?,
        })?;
        if status != NativeUpdateStatus::RestartRequired {
            bail!("native update staging returned unexpected status {status:?}");
        }
        spawn_update_helper(restart_config, &predecessor_digest, &package_digest)?;
        Ok(())
    })();
    match result {
        Ok(()) => {
            app.message = "Update staged; helper will activate after this process exits".to_string();
            Ok(true)
        }
        Err(error) => {
            app.message = format!("Update rejected: {error:#}");
            Ok(false)
        }
    }
}

fn spawn_update_helper(
    config: &NativeProductConfig,
    predecessor_digest: &str,
    expected_package_digest: &str,
) -> Result<()> {
    let helper = updater_helper_path(&config.active_artifact)?;
    if !helper.is_file() {
        bail!("native updater helper is missing at {}", helper.display());
    }
    let confirm_file = config.update_journal.with_extension("restart-confirmed");
    let mut command = Command::new(helper);
    command
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .arg("--active-artifact")
        .arg(&config.active_artifact)
        .arg("--rollback-artifact")
        .arg(&config.rollback_artifact)
        .arg("--stage-artifact")
        .arg(&config.stage_artifact)
        .arg("--update-journal")
        .arg(&config.update_journal)
        .arg("--predecessor-digest")
        .arg(predecessor_digest)
        .arg("--expected-package-digest")
        .arg(expected_package_digest)
        .arg("--confirm-file")
        .arg(&confirm_file)
        .arg("--manifest-digest")
        .arg(&config.manifest_digest)
        .arg("--grant-public-key")
        .arg(&config.grant_public_key)
        .arg("--release-public-key")
        .arg(&config.release_public_key)
        .arg("--selection-public-key")
        .arg(&config.selection_public_key)
        .arg("--effect-journal")
        .arg(&config.effect_journal)
        .arg("--windows-dpapi-session-path")
        .arg(&config.windows_dpapi_session_path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if config.capabilities.open_path {
        command.arg("--allow-open-path");
    }
    if config.capabilities.reveal_path {
        command.arg("--allow-reveal-path");
    }
    if config.capabilities.copy_text {
        command.arg("--allow-copy-text");
    }
    if config.capabilities.notify {
        command.arg("--allow-notify");
    }
    if !config.persist_session_reference {
        command.arg("--no-session-persistence");
    }
    command.spawn().context("start native updater helper")?;
    Ok(())
}

fn updater_helper_path(active_artifact: &Path) -> Result<PathBuf> {
    let parent = active_artifact
        .parent()
        .context("native application executable has no parent directory")?;
    let mut name = OsString::from("hepta-native-updater");
    name.push(std::env::consts::EXE_SUFFIX);
    Ok(parent.join(name))
}

fn run_accessible(
    product: &mut NativeProduct,
    mut snapshot: NativeSnapshot,
    locale: String,
) -> Result<()> {
    let stdin = std::io::stdin();
    loop {
        println!("Hepta Native accessible mode — {locale}");
        println!(
            "Runtime: {} / platform: {}",
            snapshot.runtime_status, snapshot.platform
        );
        println!(
            "Session: {} generation {}",
            snapshot.session_id, snapshot.session_generation
        );
        println!(
            "View revision: {} / integrity: {} / authority closed: {}",
            snapshot.view_revision, snapshot.integrity_verified, snapshot.authority_closed
        );
        println!("Commands: refresh, quit");
        print!("> ");
        stdout().flush()?;
        let mut command = String::new();
        stdin.read_line(&mut command)?;
        match command.trim() {
            "refresh" | "r" => snapshot = product.refresh()?,
            "quit" | "q" => return Ok(()),
            _ => println!("Unknown command"),
        }
    }
}

fn set_page(app: &mut AppState, page: Page) {
    app.page = page;
    app.focus = 0;
    app.edit = None;
    app.edit_buffer.clear();
}

fn focus_count(page: Page) -> usize {
    match page {
        Page::Operations => 5,
        Page::Update => 1,
        Page::Overview | Page::Help => 1,
    }
}

fn next_action(action: NativeAction) -> NativeAction {
    match action {
        NativeAction::OpenPath => NativeAction::RevealPath,
        NativeAction::RevealPath => NativeAction::CopyText,
        NativeAction::CopyText => NativeAction::Notify,
        NativeAction::Notify => NativeAction::OpenPath,
    }
}

fn page_name(page: Page) -> &'static str {
    match page {
        Page::Overview => "overview",
        Page::Operations => "operations",
        Page::Update => "update",
        Page::Help => "help",
    }
}

fn line(out: &mut impl Write, row: u16, width: u16, text: &str) -> Result<()> {
    queue!(out, MoveTo(0, row), Print(truncate(text, width as usize)))?;
    Ok(())
}

fn focus_line(
    out: &mut impl Write,
    row: u16,
    width: u16,
    focused: bool,
    text: &str,
) -> Result<()> {
    queue!(out, MoveTo(0, row))?;
    if focused {
        queue!(out, SetAttribute(Attribute::Bold), Print("> "))?;
    } else {
        queue!(out, Print("  "))?;
    }
    queue!(
        out,
        Print(truncate(text, width.saturating_sub(2) as usize))
    )?;
    if focused {
        queue!(out, SetAttribute(Attribute::Reset))?;
    }
    Ok(())
}

fn truncate(value: &str, width: usize) -> String {
    value.chars().take(width).collect()
}

fn value_or_empty(value: &str) -> String {
    if value.is_empty() {
        "<empty>".to_string()
    } else {
        value.to_string()
    }
}

fn hidden_value(value: &str) -> String {
    if value.is_empty() {
        "<empty>".to_string()
    } else {
        format!("<set:{} bytes>", value.len())
    }
}

fn compact_secret(value: &str) -> String {
    if value.len() <= 16 {
        return value.to_string();
    }
    format!("{}…{}", &value[..8], &value[value.len() - 8..])
}

fn absolute(path: PathBuf, name: &str) -> Result<PathBuf> {
    if path.is_absolute() {
        return Ok(path);
    }
    Ok(std::env::current_dir()
        .context("resolve native shell current directory")?
        .join(path)
        .canonicalize()
        .with_context(|| format!("resolve {name}"))?)
}

fn absolute_state_root() -> Result<PathBuf> {
    let root = std::env::var_os("HEPTA_STATE_ROOT").context("HEPTA_STATE_ROOT is required")?;
    let root = PathBuf::from(root);
    if !root.is_absolute() {
        bail!("HEPTA_STATE_ROOT must be absolute");
    }
    Ok(root)
}
