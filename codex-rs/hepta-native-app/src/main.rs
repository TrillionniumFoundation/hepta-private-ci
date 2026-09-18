use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use clap::Parser;
use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_native_app::AgentdBackend;
use codex_hepta_native_app::KeyringOperationStore;
use codex_hepta_native_app::NativeShellRuntime;
use codex_hepta_native_app::OperationStore;
use codex_hepta_native_app::SecurePlatformAdapter;
use codex_hepta_native_app::SignedUpdater;
use codex_hepta_native_app::persistence::ReadOnlyOperationStore;
use codex_hepta_native_app::run_native_ui;
use codex_hepta_native_app::update::parse_hex_32;
use serde::Deserialize;

const MAX_AUTHORITY_CONFIG_BYTES: u64 = 256 * 1024;

#[derive(Debug, Parser)]
#[command(name = "hepta-native", about = "Hepta Rust native application shell")]
struct Args {
    #[arg(long)]
    agentd_socket: PathBuf,

    #[arg(long)]
    agent_id: String,

    #[arg(long)]
    generation: u64,

    #[arg(long, requires = "authority_state_dir")]
    authority_config: Option<PathBuf>,

    #[arg(long)]
    authority_state_dir: Option<PathBuf>,

    #[arg(long, requires = "update_state_dir")]
    update_key_hex: Option<String>,

    #[arg(long)]
    update_state_dir: Option<PathBuf>,

    #[arg(long)]
    locale: Option<String>,

    #[arg(long, hide = true)]
    qualification_window_smoke: bool,

    #[arg(long, hide = true)]
    post_update_probe: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorityBootstrap {
    schema_version: u32,
    signer_id: String,
    verifying_key_hex: String,
    head: FinalUseRevocations,
}

fn main() -> Result<()> {
    let args = Args::parse();
    if args.generation == 0 {
        anyhow::bail!("--generation must be non-zero");
    }
    let agent_id = AgentId::parse(args.agent_id.clone()).context("parse --agent-id")?;

    let backend = AgentdBackend::new(
        args.agentd_socket.clone(),
        agent_id.clone(),
        args.generation,
    )
    .map_err(|error| anyhow::anyhow!(error.to_string()))?;
    let manifest = backend.endpoint_manifest();

    let authority = match (&args.authority_config, &args.authority_state_dir) {
        (Some(config), Some(state_dir)) => Some(load_authority(config, state_dir)?),
        (None, None) => None,
        _ => anyhow::bail!("authority config and state directory must be supplied together"),
    };
    let platform = SecurePlatformAdapter::new(authority);

    let keyring_store =
        KeyringOperationStore::system(agent_id.as_str()).map_err(|error| anyhow::anyhow!(error))?;
    let (store, journal_warning): (Box<dyn OperationStore>, Option<String>) =
        match keyring_store.load() {
            Ok(_) => (Box::new(keyring_store), None),
            Err(error) => {
                let warning = error.to_string();
                (
                    Box::new(ReadOnlyOperationStore::new(warning.clone())),
                    Some(warning),
                )
            }
        };

    let mut runtime =
        NativeShellRuntime::new(Box::new(backend), Box::new(platform), store)
            .map_err(|error| anyhow::anyhow!(error.to_string()))?;

    if args.post_update_probe {
        let session = runtime
            .connect(&manifest)
            .map_err(|error| anyhow::anyhow!(error.to_string()))?;
        let view = runtime
            .refresh_view()
            .map_err(|error| anyhow::anyhow!(error.to_string()))?;
        println!(
            "hepta-native probe: endpoint={} session={} generation={} revision={} digest={}",
            session.endpoint_id,
            session.fence.session_id,
            view.generation,
            view.revision,
            view.digest.as_str()
        );
        runtime
            .close()
            .map_err(|error| anyhow::anyhow!(error.to_string()))?;
        return Ok(());
    }

    let updater = match (&args.update_key_hex, &args.update_state_dir) {
        (Some(key), Some(state_dir)) => Some(
            SignedUpdater::new(
                parse_hex_32(key).map_err(|error| anyhow::anyhow!(error.to_string()))?,
                state_dir.clone(),
                AGENTD_CONTROL_SCHEMA_VERSION,
            )
            .map_err(|error| anyhow::anyhow!(error.to_string()))?,
        ),
        (None, None) => None,
        _ => anyhow::bail!("update key and state directory must be supplied together"),
    };

    let locale = args
        .locale
        .or_else(sys_locale::get_locale)
        .unwrap_or_else(|| "en-US".to_string());

    run_native_ui(
        runtime,
        manifest,
        updater,
        locale,
        journal_warning,
        args.qualification_window_smoke,
    )
    .map_err(|error| anyhow::anyhow!(error.to_string()))
}

fn load_authority(path: &Path, state_dir: &Path) -> Result<FinalUseAuthority> {
    if !path.is_absolute() || !state_dir.is_absolute() {
        anyhow::bail!("authority config and state directory must be absolute");
    }
    let file = std::fs::File::open(path)
        .with_context(|| format!("open authority config {}", path.display()))?;
    let mut bytes = Vec::new();
    file.take(MAX_AUTHORITY_CONFIG_BYTES + 1)
        .read_to_end(&mut bytes)
        .context("read authority config")?;
    if bytes.len() as u64 > MAX_AUTHORITY_CONFIG_BYTES {
        anyhow::bail!("authority config exceeds size bound");
    }
    let config: AuthorityBootstrap =
        serde_json::from_slice(&bytes).context("parse authority config")?;
    if config.schema_version != 1 {
        anyhow::bail!("unsupported authority bootstrap schema");
    }
    let key = parse_hex_32(&config.verifying_key_hex)
        .map_err(|error| anyhow::anyhow!(error.to_string()))?;
    FinalUseAuthority::open_state_dir(state_dir, config.signer_id, key, config.head)
        .map_err(|error| anyhow::anyhow!("open final-use authority: {error}"))
}
