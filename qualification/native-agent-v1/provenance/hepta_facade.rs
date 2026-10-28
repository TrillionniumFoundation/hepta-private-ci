#![recursion_limit = "256"]

//! Qualification-only stdio bridge to the official 0.164.0 in-process facade.
//! Agent logic, tools, persistence, approvals and dynamic calls remain upstream.

use std::collections::HashSet;
use std::io;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_app_server_client::EmbeddedNetworkPolicy;
use codex_app_server_client::EnvironmentManager;
use codex_app_server_client::ExecServerRuntimeOptions;
use codex_app_server_client::InProcessAppServerClient;
use codex_app_server_client::InProcessClientStartArgs;
use codex_app_server_client::InProcessServerEvent;
use codex_app_server_client::DEFAULT_IN_PROCESS_CHANNEL_CAPACITY;
use codex_app_server_protocol::ClientNotification;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::ConfigWarningNotification;
use codex_app_server_protocol::InitializeParams;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::RequestId;
use codex_arg0::Arg0DispatchPaths;
use codex_config::CloudConfigBundleLoader;
use codex_config::LoaderOverrides;
use codex_core::config::ConfigBuilder;
use codex_feedback::CodexFeedback;
use codex_protocol::protocol::SessionSource;
use serde_json::json;
use serde_json::Value;
use tokio::sync::mpsc;
use tokio::task::JoinSet;

type Error = Box<dyn std::error::Error + Send + Sync>;
type Output = Arc<Mutex<io::Stdout>>;
const MAX_INPUT_BYTES: u64 = 1_048_576;
const MAX_REQUESTS: usize = 64;

struct Options {
    codex_home: PathBuf,
    codex_exe: PathBuf,
    sandbox_exe: Option<PathBuf>,
    cwd: Option<PathBuf>,
    overrides: Vec<(String, toml::Value)>,
}

fn options() -> Result<Options, Error> {
    let mut args = std::env::args().skip(1);
    let mut home = None;
    let mut executable = None;
    let mut sandbox_exe = None;
    let mut cwd = None;
    let mut overrides = Vec::new();
    while let Some(flag) = args.next() {
        let value = args.next().ok_or("missing option value")?;
        match flag.as_str() {
            "--codex-home" => home = Some(PathBuf::from(value)),
            "--codex-exe" => executable = Some(PathBuf::from(value)),
            "--codex-linux-sandbox-exe" => sandbox_exe = Some(PathBuf::from(value)),
            "--cwd" => cwd = Some(PathBuf::from(value)),
            "-c" | "--config" => {
                let (key, value) = value.split_once('=').ok_or("expected key=TOML-value")?;
                overrides.push((key.to_owned(), value.parse::<toml::Value>()?));
            }
            _ => return Err(format!("unknown option: {flag}").into()),
        }
    }
    Ok(Options {
        codex_home: home.ok_or("--codex-home is required")?,
        codex_exe: executable.ok_or("--codex-exe is required")?,
        sandbox_exe,
        cwd,
        overrides,
    })
}

fn emit(output: &Output, value: &Value) -> io::Result<()> {
    let mut output = output
        .lock()
        .map_err(|_| io::Error::other("stdout lock poisoned"))?;
    serde_json::to_writer(&mut *output, value)?;
    output.write_all(b"\n")?;
    output.flush()
}

fn input_lines() -> mpsc::Receiver<io::Result<Value>> {
    let (sender, receiver) = mpsc::channel(32);
    std::thread::spawn(move || {
        let input = io::stdin();
        let mut input = input.lock();
        loop {
            let mut bytes = Vec::new();
            let value = match (&mut input)
                .take(MAX_INPUT_BYTES + 1)
                .read_until(b'\n', &mut bytes)
            {
                Ok(0) => break,
                Ok(size) if size as u64 > MAX_INPUT_BYTES => Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "input line exceeds limit",
                )),
                Ok(_) => serde_json::from_slice(&bytes).map_err(io::Error::other),
                Err(error) => Err(error),
            };
            let failed = value.is_err();
            if sender.blocking_send(value).is_err() || failed {
                break;
            }
        }
    });
    receiver
}

async fn start(
    options: Options,
    initialize: InitializeParams,
) -> Result<(InProcessAppServerClient, Value), Error> {
    let loader_overrides = LoaderOverrides::default();
    let policy = EmbeddedNetworkPolicy::load(&loader_overrides).await;
    let mut config = ConfigBuilder::default()
        .codex_home(options.codex_home)
        .fallback_cwd(options.cwd)
        .cli_overrides(options.overrides.clone())
        .loader_overrides(loader_overrides.clone())
        .build()
        .await?;
    policy.activate(&mut config);
    let arg0_paths = Arg0DispatchPaths {
        codex_self_exe: Some(options.codex_exe),
        codex_linux_sandbox_exe: options.sandbox_exe,
        main_execve_wrapper_exe: None,
    };
    let runtime_paths = ExecServerRuntimeOptions::from_optional_paths(
        arg0_paths.codex_self_exe.clone(),
        arg0_paths.codex_linux_sandbox_exe.clone(),
    )?;
    let environment_manager = EnvironmentManager::from_codex_home(
        config.codex_home.clone(),
        Some(runtime_paths),
        policy.bind(config.http_client_factory()),
    )
    .await?;
    let state_db = codex_core::init_state_db(&config).await;
    let config_warnings = config
        .startup_warnings
        .iter()
        .map(|warning| ConfigWarningNotification {
            summary: warning.clone(),
            details: None,
            path: None,
            range: None,
        })
        .collect();
    let capabilities = initialize.capabilities.clone().unwrap_or_default();
    Ok(InProcessAppServerClient::start_with_initialize_response(
        InProcessClientStartArgs {
            arg0_paths,
            config: Arc::new(config),
            cli_overrides: options.overrides,
            loader_overrides,
            strict_config: false,
            cloud_config_bundle: CloudConfigBundleLoader::default(),
            embedded_network_policy: policy,
            feedback: CodexFeedback::new(),
            log_db: None,
            state_db,
            environment_manager: Arc::new(environment_manager),
            config_warnings,
            session_source: SessionSource::Exec,
            enable_codex_api_key_env: true,
            client_name: initialize.client_info.name.clone(),
            client_version: initialize.client_info.version.clone(),
            experimental_api: capabilities.experimental_api,
            mcp_server_openai_form_elicitation: capabilities.mcp_server_openai_form_elicitation,
            opt_out_notification_methods: capabilities
                .opt_out_notification_methods
                .unwrap_or_default(),
            channel_capacity: DEFAULT_IN_PROCESS_CHANNEL_CAPACITY,
        },
        initialize,
    )
    .await?)
}

async fn run(options: Options) -> Result<(), Error> {
    let output = Arc::new(Mutex::new(io::stdout()));
    let mut input = input_lines();
    let initialize: ClientRequest =
        serde_json::from_value(input.recv().await.ok_or("EOF before initialize")??)?;
    let ClientRequest::Initialize { request_id, params } = initialize else {
        return Err("first request must be initialize".into());
    };
    let (mut client, response) = start(options, params).await?;
    emit(&output, &json!({"id": request_id, "result": response}))?;
    let mut initialized = false;
    let mut server_requests = HashSet::new();
    let mut requests: JoinSet<io::Result<()>> = JoinSet::new();
    let result: Result<(), Error> = async {
        loop {
            tokio::select! {
                line = input.recv() => {
                    let Some(line) = line else { break; };
                    let value = line?;
                    if value.get("method").is_some() {
                        if value.get("id").is_none() {
                            let notification: ClientNotification = serde_json::from_value(value)?;
                            // The facade has already sent this exact lifecycle notification.
                            if matches!(notification, ClientNotification::Initialized) && !initialized {
                                initialized = true;
                            } else {
                                client.notify(notification).await?;
                            }
                        } else {
                            let request: ClientRequest = serde_json::from_value(value)?;
                            let id = request.id().clone();
                            if requests.len() >= MAX_REQUESTS {
                                emit(&output, &json!({"id": id, "error": {
                                    "code": -32001, "message": "qualification bridge overloaded"
                                }}))?;
                                continue;
                            }
                            let handle = client.request_handle();
                            let output = Arc::clone(&output);
                            requests.spawn(async move {
                                let value = match handle.request(request).await? {
                                    Ok(result) => json!({"id": id, "result": result}),
                                    Err(error) => json!({"id": id, "error": error}),
                                };
                                emit(&output, &value)
                            });
                        }
                    } else {
                        let id: RequestId = serde_json::from_value(value.get("id").cloned().ok_or("response has no id")?)?;
                        if !server_requests.remove(&serde_json::to_string(&id)?) {
                            return Err("response does not name an outstanding server request".into());
                        }
                        match (value.get("result"), value.get("error")) {
                            (Some(result), None) => client.resolve_server_request(id, result.clone()).await?,
                            (None, Some(error)) => {
                                let error: JSONRPCErrorError = serde_json::from_value(error.clone())?;
                                client.reject_server_request(id, error).await?;
                            }
                            _ => return Err("response requires exactly one result or error".into()),
                        }
                    }
                }
                event = client.next_event(), if initialized => {
                    match event.ok_or("embedded app-server disconnected")? {
                        InProcessServerEvent::ServerRequest(request) => {
                            let value = serde_json::to_value(request.as_ref())?;
                            let id = value.get("id").ok_or("server request has no id")?;
                            if !server_requests.insert(serde_json::to_string(id)?) {
                                return Err("duplicate outstanding server request id".into());
                            }
                            emit(&output, &value)?;
                        }
                        InProcessServerEvent::ServerNotification(notification) => {
                            emit(&output, &serde_json::to_value(notification.as_ref())?)?;
                        }
                        InProcessServerEvent::Lagged { skipped } => {
                            return Err(format!("embedded event stream dropped {skipped} events").into());
                        }
                    }
                }
                finished = requests.join_next(), if !requests.is_empty() => {
                    let finished = finished.ok_or("request task disappeared")?;
                    finished??;
                }
            }
        }
        Ok(())
    }.await;
    let shutdown = client.shutdown().await;
    requests.abort_all();
    result?;
    shutdown?;
    Ok(())
}

fn main() -> Result<(), Error> {
    let options = options()?;
    codex_utils_rustls_provider::ensure_rustls_crypto_provider();
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?
        .block_on(run(options))
}
