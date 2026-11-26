//! The renderer sends bounded intents to the original desktop runtime owner.
use std::sync::mpsc::Receiver;
use std::sync::mpsc::SyncSender;
use std::sync::mpsc::sync_channel;
use std::thread::JoinHandle;

use hepta_native::fleet_lifecycle::FleetLifecycleOperation;
use hepta_native::native_host::NativeHost;
use hepta_native::native_host::NativeHostObservation;
use makepad_widgets::SignalToUI;

pub enum OwnerCommand {
    Refresh,
    Inspect,
    OpenChat {
        agent_id: String,
        revision: u64,
    },
    ChatCreate,
    ChatSelect(String),
    ChatTimeline,
    ChatSend(String),
    ChatInspect,
    ChatAbandonCreation,
    ChatCancel,
    Lifecycle {
        agent_id: String,
        operation: FleetLifecycleOperation,
        revision: u64,
    },
}

pub struct OwnerResponse {
    pub observation: Option<NativeHostObservation>,
    pub message: String,
    pub chat: Option<hepta_native::chat_presentation::ChatPresentation>,
    pub clear_composer: bool,
}

pub struct OwnerWorker {
    commands: Option<SyncSender<OwnerCommand>>,
    responses: Receiver<OwnerResponse>,
    thread: Option<JoinHandle<()>>,
}

impl OwnerWorker {
    pub fn start(arguments: Vec<String>) -> std::io::Result<Self> {
        let (commands, requests) = sync_channel(1);
        let (results, responses) = sync_channel(1);
        let thread = std::thread::Builder::new().name("hepta-desktop-owner".into()).spawn(move || {
            let mut host = match NativeHost::open(&arguments) {
                Ok(host) => host,
                Err(error) => {
                    eprintln!("Hepta desktop connection unavailable: {error}");
                    let _ = results.send(OwnerResponse { observation: None, message: "Runtime connection is unavailable. Check the desktop configuration.".into(), chat: None, clear_composer: false });
                    SignalToUI::set_ui_signal();
                    return;
                }
            };
            let mut next = Some(OwnerCommand::Refresh);
            while let Some(command) = next.take().or_else(|| requests.recv().ok()) {
                // No refresh can silently change the revision before an action.
                let sending = matches!(&command, OwnerCommand::ChatSend(_));
                let action = match command {
                    OwnerCommand::Refresh => Ok(()),
                    OwnerCommand::OpenChat { agent_id, revision } => host.chat.as_mut().ok_or_else(|| hepta_native::error::ShellError::State("Chat is not configured".into()))
                        .and_then(|chat| chat.attach(&mut host.runtime, &agent_id, revision).and_then(|_| chat.list(&mut host.runtime))),
                    OwnerCommand::ChatCreate => with_chat(&mut host, |chat, runtime| chat.create(runtime)),
                    OwnerCommand::ChatSelect(thread) => with_chat(&mut host, |chat, runtime| chat.select(runtime, &thread)),
                    OwnerCommand::ChatTimeline => with_chat(&mut host, |chat, runtime| chat.timeline(runtime)),
                    OwnerCommand::ChatSend(text) => with_chat(&mut host, |chat, runtime| chat.send(runtime, text)),
                    OwnerCommand::ChatInspect => with_chat(&mut host, |chat, runtime| chat.inspect(runtime)),
                    OwnerCommand::ChatAbandonCreation => with_chat(&mut host, |chat, runtime| chat.abandon_creation(runtime)),
                    OwnerCommand::ChatCancel => with_chat(&mut host, |chat, runtime| chat.cancel(runtime)),
                    OwnerCommand::Inspect => host.runtime.inspect_fleet_lifecycle_receipt().map(|_| ()),
                    OwnerCommand::Lifecycle { agent_id, operation, revision } =>
                        host.runtime.execute_fleet_lifecycle(&agent_id, operation, revision),
                };
                let clear_composer = sending && action.is_ok() && host.chat.as_ref().is_some_and(|chat|
                    matches!(chat.presentation().last_submission, Some(hepta_native::chat_protocol::wire::SubmissionState::Queued { .. } | hepta_native::chat_protocol::wire::SubmissionState::Persisted { .. })));
                let response = match action {
                    Ok(()) => match host.refresh() {
                        Ok(observation) => OwnerResponse { observation: Some(observation), message: "Connected to the installed runtime.".into(), chat: host.chat.as_ref().map(|chat| chat.presentation()), clear_composer },
                        Err(error) => {
                            eprintln!("Hepta runtime refresh unavailable: {error}");
                            OwnerResponse { observation: None, message: "Runtime connection is unavailable. Check the desktop configuration.".into(), chat: host.chat.as_ref().map(|chat| chat.presentation()), clear_composer }
                        },
                    },
                    Err(error) => OwnerResponse { observation: None, message: error.to_string(), chat: host.chat.as_ref().map(|chat| chat.presentation()), clear_composer: false },
                };
                // Only one intent is in flight. A blocked presentation never
                // creates an unbounded queue or retries an unknown mutation.
                if results.try_send(response).is_err() { break; }
                SignalToUI::set_ui_signal();
            }
            let _ = host.runtime.close();
        })?;
        Ok(Self {
            commands: Some(commands),
            responses,
            thread: Some(thread),
        })
    }

    pub fn submit(&self, command: OwnerCommand) -> Result<(), String> {
        self.commands
            .as_ref()
            .ok_or("desktop owner is closed")?
            .try_send(command)
            .map_err(|_| "desktop owner is busy or unavailable".into())
    }

    pub fn poll(&self) -> Option<OwnerResponse> {
        self.responses.try_recv().ok()
    }
}

impl Drop for OwnerWorker {
    fn drop(&mut self) {
        self.commands.take();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

fn with_chat(
    host: &mut NativeHost,
    run: impl FnOnce(
        &mut hepta_native::chat_presentation::DesktopChat,
        &mut hepta_native::NativeShellRuntime,
    ) -> Result<(), hepta_native::error::ShellError>,
) -> Result<(), hepta_native::error::ShellError> {
    let chat = host
        .chat
        .as_mut()
        .ok_or_else(|| hepta_native::error::ShellError::State("Chat is not configured".into()))?;
    run(chat, &mut host.runtime)
}
