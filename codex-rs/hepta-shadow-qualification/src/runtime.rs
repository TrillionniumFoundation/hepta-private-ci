use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::Read;
use std::net::SocketAddr;
use std::path::Path;
use std::path::PathBuf;

use sha2::Digest;
use sha2::Sha256;

use crate::QualificationError;
use crate::Surface;
use crate::durable::create_private_directory;
use crate::durable::same_file_snapshot;
use crate::durable::sync_directory;
use crate::durable::write_private_new;
use crate::request::FIXED_MODEL;
use crate::request::FIXED_PROVIDER;

const PRODUCT_SHA256: &str = "8843df374eac70246a9398feaf25045558ac0aa7a25e6af92d186df7d7b3434c";
const PRODUCT_SIZE_BYTES: u64 = 556_410_456;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenProductBinary {
    path: PathBuf,
}

impl FrozenProductBinary {
    pub fn verify(path: impl AsRef<Path>) -> Result<Self, QualificationError> {
        let path = path.as_ref();
        if !path.is_absolute() {
            return Err(invalid("frozen product binary path must be absolute"));
        }
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
        }
        let mut file = options.open(path)?;
        let before = file.metadata()?;
        if !before.is_file() || before.len() != PRODUCT_SIZE_BYTES {
            return Err(invalid(
                "frozen product binary type or size differs from pin",
            ));
        }
        let mut hasher = Sha256::new();
        let mut buffer = [0_u8; 128 * 1024];
        loop {
            let count = file.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            hasher.update(&buffer[..count]);
        }
        let after = file.metadata()?;
        if !same_file_snapshot(&before, &after)
            || format!("{:x}", hasher.finalize()) != PRODUCT_SHA256
        {
            return Err(invalid(
                "frozen product binary changed or differs from SHA-256 pin",
            ));
        }
        Ok(Self {
            path: path.to_path_buf(),
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn sha256(&self) -> &'static str {
        PRODUCT_SHA256
    }

    pub fn size_bytes(&self) -> u64 {
        PRODUCT_SIZE_BYTES
    }
}

#[derive(Clone, Debug)]
pub struct QualificationRuntimeLayout {
    app_server: SurfaceRuntimeLayout,
    mcp: SurfaceRuntimeLayout,
    observer: PathBuf,
    root: PathBuf,
    work: PathBuf,
}

impl QualificationRuntimeLayout {
    pub fn create(root: impl AsRef<Path>) -> Result<Self, QualificationError> {
        let root = root.as_ref();
        if !root.is_absolute() || root.exists() {
            return Err(invalid(
                "qualification runtime root must be absolute and absent",
            ));
        }
        create_private_directory(root)?;
        let work = create_child(root, "work")?;
        let observer = root.join("observer");
        let app_server = SurfaceRuntimeLayout::create(root, &work, Surface::AppServer)?;
        let mcp = SurfaceRuntimeLayout::create(root, &work, Surface::Mcp)?;
        Ok(Self {
            app_server,
            mcp,
            observer,
            root: root.to_path_buf(),
            work,
        })
    }

    pub fn app_server(&self) -> &SurfaceRuntimeLayout {
        &self.app_server
    }

    pub fn mcp(&self) -> &SurfaceRuntimeLayout {
        &self.mcp
    }

    pub fn observer_root(&self) -> &Path {
        &self.observer
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn work(&self) -> &Path {
        &self.work
    }

    pub(crate) fn harden_known_product_permissions(&self) -> Result<(), QualificationError> {
        for layout in [&self.app_server, &self.mcp] {
            let path = layout.home().join("installation_id");
            let mut options = OpenOptions::new();
            options.read(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
            }
            let mut file = options.open(&path)?;
            let metadata = file.metadata()?;
            let mut contents = String::new();
            file.read_to_string(&mut contents)?;
            let valid_uuid = contents.len() == 36
                && contents.bytes().enumerate().all(|(index, byte)| {
                    if matches!(index, 8 | 13 | 18 | 23) {
                        byte == b'-'
                    } else {
                        byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()
                    }
                });
            if !metadata.is_file() || !valid_uuid {
                return Err(invalid(
                    "product installation fixture is not one regular lowercase UUID",
                ));
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let mode = metadata.permissions().mode() & 0o777;
                if !matches!(mode, 0o600 | 0o644) {
                    return Err(invalid(
                        "product installation fixture has an unexpected mode",
                    ));
                }
                let mut permissions = metadata.permissions();
                permissions.set_mode(0o600);
                file.set_permissions(permissions)?;
            }
            file.sync_all()?;
            sync_directory(layout.home())?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct SurfaceRuntimeLayout {
    config: PathBuf,
    environment: BTreeMap<String, String>,
    home: PathBuf,
    sqlite: PathBuf,
    surface: Surface,
    work: PathBuf,
}

impl SurfaceRuntimeLayout {
    fn create(root: &Path, work: &Path, surface: Surface) -> Result<Self, QualificationError> {
        let surface_root = create_child(root, surface.as_str())?;
        let home = create_child(&surface_root, "home")?;
        let sqlite = create_child(&surface_root, "sqlite")?;
        let tmp = create_child(&surface_root, "tmp")?;
        let xdg_config = create_child(&surface_root, "xdg-config")?;
        let xdg_cache = create_child(&surface_root, "xdg-cache")?;
        let xdg_data = create_child(&surface_root, "xdg-data")?;
        let xdg_state = create_child(&surface_root, "xdg-state")?;
        let environment = BTreeMap::from([
            ("CODEX_HOME".to_string(), home.display().to_string()),
            (
                "CODEX_SQLITE_HOME".to_string(),
                sqlite.display().to_string(),
            ),
            ("HEPTA_HOME".to_string(), home.display().to_string()),
            ("HOME".to_string(), home.display().to_string()),
            ("LANG".to_string(), "C".to_string()),
            ("LC_ALL".to_string(), "C".to_string()),
            ("NO_PROXY".to_string(), "127.0.0.1,localhost".to_string()),
            (
                "PATH".to_string(),
                "/usr/bin:/bin:/usr/sbin:/sbin".to_string(),
            ),
            ("PWD".to_string(), work.display().to_string()),
            ("RUST_BACKTRACE".to_string(), "1".to_string()),
            ("RUST_LOG".to_string(), "warn".to_string()),
            ("TERM".to_string(), "dumb".to_string()),
            ("TMPDIR".to_string(), tmp.display().to_string()),
            (
                "XDG_CACHE_HOME".to_string(),
                xdg_cache.display().to_string(),
            ),
            (
                "XDG_CONFIG_HOME".to_string(),
                xdg_config.display().to_string(),
            ),
            ("XDG_DATA_HOME".to_string(), xdg_data.display().to_string()),
            (
                "XDG_STATE_HOME".to_string(),
                xdg_state.display().to_string(),
            ),
            ("no_proxy".to_string(), "127.0.0.1,localhost".to_string()),
        ]);
        Ok(Self {
            config: home.join("config.toml"),
            environment,
            home,
            sqlite,
            surface,
            work: work.to_path_buf(),
        })
    }

    pub fn write_config(&self, address: SocketAddr) -> Result<String, QualificationError> {
        if !address.ip().is_loopback() {
            return Err(invalid("provider endpoint must be loopback"));
        }
        let config = format!(
            r#"model = {model}
model_provider = {provider}
approval_policy = "never"
sandbox_mode = "workspace-write"
sqlite_home = {sqlite}
check_for_update_on_startup = false
cli_auth_credentials_store = "ephemeral"
mcp_oauth_credentials_store = "file"
suppress_unstable_features_warning = true

[history]
persistence = "none"

[analytics]
enabled = false

[feedback]
enabled = false

[otel]
log_user_prompt = false
environment = "qualification"
exporter = "none"
trace_exporter = "none"
metrics_exporter = "none"

[features]
shell_tool = true
hooks = false
unified_exec = false
code_mode = false
web_search_request = false
web_search_cached = false
standalone_web_search = false
remote_models = false
network_proxy = false
respect_system_proxy = false
apps = false
enable_mcp_apps = false
recommended_plugins = false
plugins = false
plugin_hooks = false
in_app_updates = false
external_migration = false
memories = false
multi_agent = false
multi_agent_v2 = false
remote_control = false
hepta_governance = true

[model_providers.{provider_key}]
name = "Hepta Shadow Qualification Loopback"
base_url = "http://{address}/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0

[projects.{project}]
trust_level = "trusted"
"#,
            model = toml_string(FIXED_MODEL)?,
            provider = toml_string(FIXED_PROVIDER)?,
            sqlite = toml_string(&self.sqlite.to_string_lossy())?,
            provider_key = FIXED_PROVIDER,
            project = toml_string(&self.work.to_string_lossy())?,
        );
        let _: toml::Value = toml::from_str(&config)
            .map_err(|error| invalid(format!("generated config is invalid TOML: {error}")))?;
        write_private_new(&self.config, config.as_bytes())?;
        Ok(crate::digest::sha256(config.as_bytes()))
    }

    pub fn config(&self) -> &Path {
        &self.config
    }

    pub fn environment(&self) -> &BTreeMap<String, String> {
        &self.environment
    }

    pub fn home(&self) -> &Path {
        &self.home
    }

    pub fn sqlite(&self) -> &Path {
        &self.sqlite
    }

    pub fn surface(&self) -> Surface {
        self.surface
    }

    pub fn work(&self) -> &Path {
        &self.work
    }
}

fn create_child(parent: &Path, name: &str) -> Result<PathBuf, QualificationError> {
    let child = parent.join(name);
    create_private_directory(&child)?;
    Ok(child)
}

fn toml_string(value: &str) -> Result<String, QualificationError> {
    serde_json::to_string(value)
        .map_err(|error| QualificationError::Serialization(error.to_string()))
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
