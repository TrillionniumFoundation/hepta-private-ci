//! Shared native launch parsing; both renderers use the original checked options.
use std::path::PathBuf;

#[derive(Debug)]
pub struct NativeLaunchOptions {
    pub check_connection: bool,
    pub chat_keyring_account: Option<String>,
    pub lifecycle_keyring_account: Option<String>,
    pub font_file: Option<PathBuf>,
    pub update_handoff: Option<String>,
    pub endpoint_manifest: PathBuf,
    pub trusted_keys: PathBuf,
    pub final_use_authority: Option<PathBuf>,
    pub updater_helper: Option<PathBuf>,
    pub state_dir: PathBuf,
    pub allowed_roots: Vec<PathBuf>,
    pub allow_clipboard: bool,
    pub allow_notifications: bool,
}

impl NativeLaunchOptions {
    pub fn parse(args: &[String]) -> Result<Self, Box<dyn std::error::Error>> {
        let mut check_connection = false;
        let mut chat_keyring_account = None;
        let mut lifecycle_keyring_account = None;
        let mut font_file = None;
        let mut update_handoff = None;
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
                "--chat-keyring-account" => {
                    index += 1;
                    let account = args
                        .get(index)
                        .ok_or("--chat-keyring-account requires an account")?
                        .clone();
                    crate::model::validate_stable_id(&account, "chat keyring account")?;
                    if chat_keyring_account.replace(account).is_some() {
                        return Err("duplicate chat keyring account".into());
                    }
                }
                "--lifecycle-keyring-account" => {
                    index += 1;
                    let account = args
                        .get(index)
                        .ok_or("--lifecycle-keyring-account requires an account")?
                        .clone();
                    crate::model::validate_stable_id(&account, "lifecycle keyring account")?;
                    if lifecycle_keyring_account.replace(account).is_some() {
                        return Err("duplicate lifecycle keyring account".into());
                    }
                }
                "--check-connection" => check_connection = true,
                "--font-file" => {
                    index += 1;
                    font_file = Some(absolute_arg(args.get(index), "--font-file")?);
                }
                "--update-handoff" => {
                    index += 1;
                    let nonce = args
                        .get(index)
                        .ok_or("--update-handoff requires a nonce")?
                        .clone();
                    if update_handoff.replace(nonce).is_some() {
                        return Err("duplicate --update-handoff".into());
                    }
                }
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
            check_connection,
            lifecycle_keyring_account,
            chat_keyring_account,
            font_file,
            update_handoff,
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
