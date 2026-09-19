use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use hepta_native::backend::LoopbackGatewayBackend;
use hepta_native::journal::OperationJournal;
use hepta_native::model::EndpointManifest;
use hepta_native::platform::PlatformPolicy;
use hepta_native::platform::SystemPlatformAdapter;
use hepta_native::runtime::NativeShellRuntime;
use hepta_native::security::ReloadingGrantVerifier;
use hepta_native::security::SignedEndpointManifestV1;
use hepta_native::security::TrustedKeySet;
use hepta_native::session_store::GatewayCredentialStore;
use hepta_native::ui::HeptaNativeApp;

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
    let grant_verifier = ReloadingGrantVerifier::new(config.trusted_keys.clone())?;
    let signed_manifest: SignedEndpointManifestV1 =
        serde_json::from_slice(&std::fs::read(&config.endpoint_manifest)?)?;
    let verified_endpoint = signed_manifest.verify(&trusted_keys)?;
    let manifest: EndpointManifest = verified_endpoint.manifest;
    let address: SocketAddr = manifest.address.parse()?;
    let bearer_token =
        GatewayCredentialStore::default().load(&verified_endpoint.gateway_credential_account)?;
    let backend = LoopbackGatewayBackend::new(address, bearer_token)?;
    let policy = PlatformPolicy::new(
        config.allowed_roots,
        config.allow_clipboard,
        config.allow_notifications,
    )?;
    let platform = SystemPlatformAdapter::new(policy);
    let journal = OperationJournal::open(config.state_dir.join("operation-journal.json"))?;
    let runtime = NativeShellRuntime::new(
        Box::new(backend),
        Box::new(platform),
        Arc::new(grant_verifier),
        journal,
    );
    let app = HeptaNativeApp::new(
        runtime,
        manifest,
        config.state_dir.join("updates/pending-update.json"),
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
    Ok(())
}

#[derive(Debug)]
struct AppConfig {
    endpoint_manifest: PathBuf,
    trusted_keys: PathBuf,
    state_dir: PathBuf,
    allowed_roots: Vec<PathBuf>,
    allow_clipboard: bool,
    allow_notifications: bool,
}

impl AppConfig {
    fn parse(args: &[String]) -> Result<Self, Box<dyn std::error::Error>> {
        let mut endpoint_manifest = None;
        let mut trusted_keys = None;
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
