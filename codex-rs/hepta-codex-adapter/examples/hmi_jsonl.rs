//! Owner-operated JSONL bridge. No thread creation, model client or history store.
//! Run: cargo run -p codex-hepta-codex-adapter --example hmi_jsonl -- CONFIG.json
//! The existing authenticated channel owner supplies CONFIG and authorizes every
//! input. A config file is not an authentication, device grant or memory receipt.

use std::io::{BufRead, Read};
use tokio::io::AsyncWriteExt;
use std::time::Duration;
use codex_app_server_client::{RemoteAppServerConnectArgs, RemoteAppServerEndpoint};
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_hepta_codex_adapter::hmi::{HmiBindingV1, HmiConnectionV1};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Config {
    binding: HmiBindingV1,
    socket_path: Option<String>,
    websocket_url: Option<String>,
}
impl Config {
    fn args(&self) -> Result<RemoteAppServerConnectArgs, Box<dyn std::error::Error>> {
        let endpoint = match (&self.socket_path, &self.websocket_url) {
            (Some(path), None) => RemoteAppServerEndpoint::UnixSocket { socket_path: path.as_str().try_into()? },
            (None, Some(url)) => RemoteAppServerEndpoint::WebSocket { websocket_url: url.clone(),
                auth_token: std::env::var("HEPTA_HMI_AUTH_TOKEN").ok() },
            _ => return Err("configure exactly one existing owner endpoint".into()),
        };
        Ok(RemoteAppServerConnectArgs { endpoint, client_name: "hepta-hmi-jsonl".into(),
            client_version: env!("CARGO_PKG_VERSION").into(), experimental_api: true,
            mcp_server_openai_form_elicitation: false, opt_out_notification_methods: Vec::new(), channel_capacity: 16 })
    }
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "camelCase", deny_unknown_fields)]
enum Command {
    #[serde(rename_all = "camelCase")]
    Submit { generation: u64, sequence: u64, request_id: String, text: String, mode: ThreadQueueReconcileMode },
    Interrupt { generation: u64 },
    Reconnect,
    Stop,
}

struct Output {
    queue: tokio::sync::mpsc::Sender<Vec<u8>>,
}
impl Output {
    fn emit(&self, requests: &codex_hepta_codex_adapter::hmi::HmiRequestsV1, value: Value)
        -> Result<(), Box<dyn std::error::Error>> {
        let mut bytes = serde_json::to_vec(&value)?;
        bytes.push(b'\n');
        if self.queue.try_send(bytes).is_err() {
            requests.revoke()?;
            return Err("bounded output writer unavailable; session fenced".into());
        }
        Ok(())
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let runtime = tokio::runtime::Builder::new_multi_thread().enable_all().build()?;
    let result = runtime.block_on(run());
    runtime.shutdown_timeout(Duration::from_secs(1));
    result
}

async fn run() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args().nth(1).ok_or("expected owner config path")?;
    let mut bytes = Vec::new();
    std::fs::File::open(path)?.take(65537).read_to_end(&mut bytes)?;
    if bytes.len() > 65536 { return Err("owner config too large".into()); }
    let config: Config = serde_json::from_slice(&bytes)?;
    let mut connection = HmiConnectionV1::connect(config.args()?, config.binding.clone(), 128, Duration::from_secs(10)).await?;
    let (writer_queue, mut output_queue) = tokio::sync::mpsc::channel::<Vec<u8>>(32);
    let mut writer = tokio::spawn(async move {
        let mut stdout = tokio::io::stdout();
        while let Some(bytes) = output_queue.recv().await {
            tokio::time::timeout(Duration::from_secs(1), stdout.write_all(&bytes)).await??;
            tokio::time::timeout(Duration::from_secs(1), stdout.flush()).await??;
        }
        Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
    });
    let output = Output { queue: writer_queue };
    let (sender, mut receiver) = tokio::sync::mpsc::channel(8);
    std::thread::spawn(move || {
        let mut input = std::io::stdin().lock();
        loop {
            let mut line = String::new();
            match (&mut input).take(131073).read_line(&mut line) {
                Ok(0) => break,
                Ok(_) if line.len() <= 131072 => if sender.blocking_send(Ok(line)).is_err() { break; },
                _ => { let _ = sender.blocking_send(Err("invalid or oversized command")); break; }
            }
        }
    });
    let mut submissions = tokio::task::JoinSet::new();
    let mut event_stream_ended = false;
    loop {
        tokio::select! {
            result = &mut writer => {
                connection.requests.revoke()?;
                return Err(format!("output writer stopped; session fenced: {result:?}").into());
            },
            event = connection.events.next(), if !event_stream_ended => match event? {
                Some(event) => output.emit(&connection.requests,serde_json::to_value(event)?)?,
                None => { event_stream_ended = true; output.emit(&connection.requests,json!({"type":"disconnected","requiresReconciliation":true}))?; }
            },
            result = submissions.join_next(), if !submissions.is_empty() => {
                let result: Result<Value, String> = result.ok_or("submission task missing")?.map_err(|error| error.to_string())?;
                match result { Ok(value) => output.emit(&connection.requests,value)?, Err(error) => output.emit(&connection.requests,json!({"type":"requestError","error":error,"requiresReconciliation":true}))? }
            },
            line = receiver.recv() => {
                let Some(line) = line else { break; };
                match serde_json::from_str::<Command>(&line?)? {
                    Command::Submit { generation, sequence, request_id, text, mode } => {
                        if !submissions.is_empty() { output.emit(&connection.requests,json!({"type":"busy"}))?; continue; }
                        let requests = connection.requests.clone();
                        submissions.spawn(async move {
                            requests.submit_text(generation, sequence, &request_id, &text, mode).await
                                .map(|response| json!({"type":"admission","requestId":request_id,"response":response}))
                                .map_err(|error| error.to_string())
                        });
                    }
                    Command::Interrupt { generation } => {
                        match connection.requests.interrupt(generation).await {
                            Ok(()) => output.emit(&connection.requests,json!({"type":"interruptRequested","terminalObserved":false}))?,
                            Err(error) => output.emit(&connection.requests,json!({"type":"requestError","error":error.to_string(),"requiresReconciliation":true}))?,
                        }
                    }
                    Command::Reconnect => {
                        if !submissions.is_empty() { output.emit(&connection.requests,json!({"type":"busy"}))?; continue; }
                        connection = connection.reconnect(config.args()?,128).await?;
                        event_stream_ended = false;
                        output.emit(&connection.requests,json!({"type":"reattached","threadId":config.binding.thread_id,"replayedAudio":false}))?;
                    }
                    Command::Stop => break,
                }
            }
        }
    }
    connection.requests.revoke()?;
    submissions.abort_all();
    while submissions.join_next().await.is_some() {}
    connection.events.shutdown().await?;
    drop(output);
    if tokio::time::timeout(Duration::from_secs(1), &mut writer).await.is_err() { writer.abort(); }
    // main uses shutdown_timeout because Tokio's OS stdio worker is not safely
    // abortable. Supervision may terminate this standalone process afterwards.
    Ok(())
}
