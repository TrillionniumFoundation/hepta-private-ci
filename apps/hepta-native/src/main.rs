use std::net::SocketAddr;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use hepta_native::backend::LoopbackGatewayBackend;
use hepta_native::journal::OperationJournal;
use hepta_native::model::EndpointManifest;
use hepta_native::platform::PlatformPolicy;
use hepta_native::platform::SystemPlatformAdapter;
use hepta_native::runtime::NativeShellRuntime;
use hepta_native::security::KernelFinalUseGate;
use hepta_native::security::SignedEndpointManifestV1;
use hepta_native::security::TrustedKeySet;
use hepta_native::session_store::GatewayCredentialStore;
use hepta_native::ui::HeptaNativeApp;
use hepta_native::updater::UpdateManager;

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-native: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let raw_args: Vec<String> = std::env::args().skip(1).collect();
    if raw_args.len() == 1 && raw_args[0] == "--self-test" {
        println!(
            "{{\"schema\":\"hepta.native-self-test.v1\",\"platform\":\"{}\",\"architecture\":\"{}\",\"gui\":\"eframe-0.36.2\",\"accessibility\":\"accesskit\"}}",
            std::env::consts::OS,
            std::env::consts::ARCH
        );
        return Ok(());
    }

    let config = AppConfig::parse(&raw_args)?;
    std::fs::create_dir_all(&config.state_dir)?;
    let trusted_keys = TrustedKeySet::from_path(&config.trusted_keys)?;
    let signed_manifest: SignedEndpointManifestV1 =
        serde_json::from_slice(&std::fs::read(&config.endpoint_manifest)?)?;
    let verified_endpoint = signed_manifest.verify(&trusted_keys)?;
    let manifest: EndpointManifest = verified_endpoint.manifest;
    let protocol_version = manifest.protocol_version;
    let address: SocketAddr = manifest.address.parse()?;
    let bearer_token =
        GatewayCredentialStore::default().load(&verified_endpoint.gateway_credential_account)?;
    let backend = LoopbackGatewayBackend::new(address, bearer_token)?;
    let policy = PlatformPolicy::new(
        config.allowed_roots.clone(),
        config.allow_clipboard,
        config.allow_notifications,
    )?;
    let platform = SystemPlatformAdapter::new(policy);
    let journal = OperationJournal::open(config.state_dir.join("operation-journal.json"))?;
    let final_use = config
        .final_use_authority
        .clone()
        .map(KernelFinalUseGate::open)
        .transpose()?
        .map(Arc::new);
    let runtime = NativeShellRuntime::new(
        Box::new(backend),
        Box::new(platform),
        final_use,
        journal,
    );
    let updater = UpdateManager::new(trusted_keys.clone(), config.state_dir.join("updates"))?;
    let pending_update_path = updater.pending_path();
    let activate_update_on_exit = Arc::new(AtomicBool::new(false));
    let app = HeptaNativeApp::new(
        runtime,
        manifest,
        updater,
        Arc::clone(&activate_update_on_exit),
    )?;

    let native_options = eframe::NativeOptions {
        renderer: eframe::Renderer::Glow,
        persistence_path: Some(config.state_dir.join("ui-state")),
        viewport: eframe::egui::ViewportBuilder::default()
            .with_title("Hepta Native")
            .with_inner_size([1180.0, 760.0])
            .with_min_inner_size([800.0, 560.0]),
        ..Default::default()
    };
    eframe::run_native(
        "hepta-native",
        native_options,
        Box::new(move |_cc| Ok(Box::new(app))),
    )?;

    if activate_update_on_exit.load(Ordering::SeqCst) {
        let target = std::env::current_exe()?;
        let helper = match config.updater_helper {
            Some(path) => path,
            None => default_updater_helper(&target)?,
        };
        if !helper.is_file() {
            return Err(format!("native updater helper is unavailable: {}", helper.display()).into());
        }
        Command::new(&helper)
            .arg(&pending_update_path)
            .arg(&config.trusted_keys)
            .arg(&target)
            .arg(protocol_version.to_string())
            .spawn()?;
    }
    Ok(())
}

#[derive(Debug)]
struct AppConfig {
    endpoint_manifest: PathBuf,
    trusted_keys: PathBuf,
    final_use_authority: Option<PathBuf>,
    updater_helper: Option<PathBuf>,
    state_dir: PathBuf,
    allowed_roots: Vec<PathBuf>,
    allow_clipboard: bool,
    allow_notifications: bool,
}

impl AppConfig {
    fn parse(args: &[String]) -> Result<Self, Box<dyn std::error::Error>> {
        let mut endpoint_manifest = None;
        let mut trusted_keys = None;
        let mut final_use_authority = None;
        let mut updater_helper = None;
        let mut state_dir = None;
        let mut allowed_roots = Vec::new();
        let mut allow_clipboard = false;
        let mut allow_notifications = false;
        let mut index = 0;
        while index < args.len() {
            match args[index].as_str() {
                "--endpoint-manifest" => {
                    index += 1;
                    endpoint_manifest = Some(absolute_arg(args.get(index), "--endpoint-manifest")?);
                }
                "--trusted-keys" => {
                    index += 1;
                    trusted_keys = Some(absolute_arg(args.get(index), "--trusted-keys")?);
                }
                "--final-use-authority" => {
                    index += 1;
                    final_use_authority =
                        Some(absolute_arg(args.get(index), "--final-use-authority")?);
                }
                "--updater-helper" => {
                    index += 1;
                    updater_helper = Some(absolute_arg(args.get(index), "--updater-helper")?);
                }
                "--state-dir" => {
                    index += 1;
                    state_dir = Some(absolute_arg(args.get(index), "--state-dir")?);
                }
                "--allow-root" => {
                    index += 1;
                    allowed_roots.push(absolute_arg(args.get(index), "--allow-root")?);
                }
                "--allow-clipboard" => allow_clipboard = true,
                "--allow-notifications" => allow_notifications = true,
                value => return Err(format!("unexpected argument {value}").into()),
            }
            index += 1;
        }
        Ok(Self {
            endpoint_manifest: endpoint_manifest.ok_or("missing --endpoint-manifest")?,
            trusted_keys: trusted_keys.ok_or("missing --trusted-keys")?,
            final_use_authority,
            updater_helper,
            state_dir: state_dir.ok_or("missing --state-dir")?,
            allowed_roots,
            allow_clipboard,
            allow_notifications,
        })
    }
}

fn absolute_arg(
    value: Option<&String>,
    option: &'static str,
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let path = PathBuf::from(value.ok_or_else(|| format!("{option} requires a path"))?);
    if !path.is_absolute() {
        return Err(format!("{option} path must be absolute").into());
    }
    Ok(path)
}

fn default_updater_helper(current_exe: &Path) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let executable_dir = current_exe
        .parent()
        .ok_or("native executable has no parent directory")?;
    #[cfg(target_os = "macos")]
    {
        if executable_dir.file_name().is_some_and(|name| name == "MacOS") {
            let contents = executable_dir
                .parent()
                .ok_or("macOS native executable has no Contents directory")?;
            return Ok(contents.join("Helpers").join("hepta-native-updater"));
        }
    }
    #[cfg(target_os = "windows")]
    let name = "hepta-native-updater.exe";
    #[cfg(not(target_os = "windows"))]
    let name = "hepta-native-updater";
    Ok(executable_dir.join(name))
}
