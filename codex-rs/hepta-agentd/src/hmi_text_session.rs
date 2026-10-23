//! One bounded UI connection, with an existing thread and canonical AuthBus IDs.
use super::*;
use crate::hmi_input::SignedInput;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use std::future::Future;
use std::pin::Pin;
use tokio::io::AsyncBufRead;
use tokio::io::AsyncBufReadExt;

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "camelCase", deny_unknown_fields)]
enum Command {
    Submit { request: AuthBusTextIngress },
    SubmitAudio { request: Box<crate::SignedAudioObservationV1> },
    ReconcileAudio { request: Box<crate::SignedAudioObservationV1> },
    Attach { request: AuthBusTextIngress },
    Reconcile { delivery_id: String, text: String },
    CancelRecovered { delivery_id: String, text: String },
    Interrupt,
    Reconnect,
    Stop,
}
type Pending = Pin<Box<dyn Future<Output = Value> + Send>>;
fn args(state: &AgentdState) -> Result<RemoteAppServerConnectArgs, AgentdError> {
    Ok(RemoteAppServerConnectArgs {
        endpoint: RemoteAppServerEndpoint::UnixSocket {
            socket_path: AbsolutePathBuf::from_absolute_path(&state.identity().app_server_socket)?,
        },
        client_name: "hepta-agentd-hmi-text".into(),
        client_version: env!("CARGO_PKG_VERSION").into(),
        experimental_api: true,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity: 8,
    })
}
async fn connect(
    state: &AgentdState,
    input: &SignedInput,
) -> Result<HmiConnectionV1, AgentdError> {
    input.authenticate(state)?;
    let probe = tokio::time::timeout(
        Duration::from_secs(3),
        RemoteAppServerClient::connect(args(state)?),
    )
    .await
    .map_err(|_| invalid("App Server discovery timed out"))?
    .map_err(invalid)?;
    let discovered = tokio::time::timeout(Duration::from_secs(3), async {
        if probe.codex_home() != Some(state.identity().home_root.to_string_lossy().as_ref()) {
            return Err(invalid("App Server escaped owner home"));
        }
        let version = probe
            .server_version()
            .ok_or_else(|| invalid("App Server version missing"))?
            .to_owned();
        let read: ThreadReadResponse = probe
            .request_typed(ClientRequest::ThreadRead {
                request_id: RequestId::Integer(1),
                params: ThreadReadParams {
                    thread_id: input.thread().to_owned(),
                    include_turns: false,
                },
            })
            .await
            .map_err(invalid)?;
        if read.thread.ephemeral || read.thread.id != input.thread() {
            return Err(invalid("existing persistent thread required"));
        }
        let mut binding = HmiBindingV1 {
            principal_id: String::new(),
            device_id: String::new(),
            device_generation: 0,
            organ_id: String::new(),
            organ_generation: 0,
            logical_session_id: String::new(),
            thread_id: read.thread.id,
            app_server_session_id: read.thread.session_id,
            codex_home: state.identity().home_root.to_string_lossy().into_owned(),
            app_server_version: version,
        };
        input.set_binding(state, &mut binding);
        Ok(binding)
    })
    .await
    .unwrap_or_else(|_| Err(invalid("existing-thread discovery timed out")));
    let shutdown = tokio::time::timeout(Duration::from_secs(3), probe.shutdown())
        .await
        .map_err(|_| invalid("discovery client shutdown timed out"))
        .and_then(|result| result.map_err(invalid));
    let binding = discovered?;
    shutdown?;
    HmiConnectionV1::connect(args(state)?, binding, 32, Duration::from_secs(3))
        .await
        .map_err(invalid)
}

// Keep partial bytes in the actor across select cancellation; bound before JSON.
async fn command<R: AsyncBufRead + Unpin>(
    read: &mut R,
    partial: &mut Vec<u8>,
) -> Result<Option<Command>, AgentdError> {
    loop {
        let bytes = read.fill_buf().await?;
        if bytes.is_empty() {
            if partial.is_empty() {
                return Ok(None);
            }
            return Err(invalid("incomplete HMI input"));
        }
        let count = bytes
            .iter()
            .position(|b| *b == b'\n')
            .map_or(bytes.len(), |n| n + 1);
        if count > 65_536 - partial.len() {
            return Err(invalid("HMI input exceeds 64 KiB"));
        }
        partial.extend_from_slice(&bytes[..count]);
        read.consume(count);
        if partial.last() == Some(&b'\n') {
            return serde_json::from_slice(&std::mem::take(partial))
                .map(Some)
                .map_err(invalid);
        }
    }
}
fn submit(
    state: Arc<AgentdState>,
    requests: HmiRequestsV1,
    input: SignedInput,
    tx: &Sender,
) -> Result<Pending, AgentdError> {
    let delivery = input.authenticate(&state)?;
    if !input.matches(&state, requests.binding()) {
        return Err(invalid(
            "signed input belongs to another attached owner/thread",
        ));
    }
    let fence = requests.owner_admission_fence().map_err(invalid)?;
    let context = input.context(&delivery);
    emit(tx, json!({"type":"admissionPending","input":context}))?;
    Ok(Box::pin(async move {
        let lookup = async {
            let host = crate::authbus_ingress::attached(&state)?;
            let id = delivery.parse().map_err(invalid)?;
            match host.evidence.authbus_delivery_status(id).await {
                Ok(_) => Ok(()), // Existing durable input never rearms presentation after reconnect.
                Err(codex_hepta_evidence::AuthBusOutboxError::NotFound) => requests
                    .observe_owner_submission(
                        fence,
                        requests.binding().organ_generation,
                        input.sequence(),
                        &format!("hepta.authbus:{delivery}"),
                        input.text(),
                    )
                    .map_err(invalid),
                Err(error) => Err(invalid(error)),
            }
        }
        .await;
        if let Err(error) = lookup {
            return json!({"type":"inputError","input":context,"error":error.to_string()});
        }
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            input.admit(&state),
        )
        .await;
        match result {
            Ok(Ok(receipt)) if receipt["delivery_id"] == delivery => {
                json!({"type":"admission","input":context,"receipt":receipt})
            }
            other => {
                let _ = requests.stop_output(requests.binding().organ_generation);
                json!({"type":"inputError","input":context,"error":format!("admission rejected or unknown: {other:?}")})
            }
        }
    }))
}

pub(super) async fn serve<R: AsyncBufRead + Unpin>(
    state: &Arc<AgentdState>,
    active: &Arc<AtomicBool>,
    cancel: &CancellationToken,
    read: &mut R,
    tx: &Sender,
) -> Result<(), AgentdError> {
    let mut partial = Vec::new();
    let first = tokio::select! {_=cancel.cancelled()=>return Ok(()),first=tokio::time::timeout(Duration::from_secs(10),command(read,&mut partial))=>first.map_err(|_|invalid("signed initial input timed out"))??};
    let (input,admit) = match first {
        Some(Command::Submit {request})=>(SignedInput::Text(request),true),
        Some(Command::SubmitAudio {request})=>(SignedInput::Audio(request),true),
        Some(Command::Attach {request})=>(SignedInput::Text(request),false),
        _=>return Err(invalid("first command must carry signed input or an authenticated attach for an existing thread")),
    };
    let mut connection = Some(connect(state, &input).await?);
    let mut requests = connection
        .as_ref()
        .ok_or_else(|| invalid("connection missing"))?
        .requests
        .clone();
    let authority = OwnerAuthority {
        state:state.clone(),active:active.clone(),binding:requests.binding().clone(),
        key_epoch:input.key_epoch(),audio_policy:input.audio_policy(),
    };
    let mut owner = bridge(
        connection
            .as_ref()
            .ok_or_else(|| invalid("connection missing"))?,
        authority.clone(),
        tx.clone(),
    )?;
    let mut pending = if admit {Some(submit(state.clone(), requests.clone(), input, tx)?)} else {None};
    emit(
        tx,
        json!({"type":"attached","binding":requests.binding(),"connectionId":requests.connection_id()}),
    )?;
    let mut revalidate = tokio::time::interval(Duration::from_millis(100));
    let mut last_diagnostic = None;
    let result: Result<(), AgentdError> = loop {
        tokio::select! {
            _=cancel.cancelled()=>break Ok(()),
            _=revalidate.tick()=>{

                if let Err(error)=authority.check_current(requests.binding()){break Err(invalid(error));}
            }
            result=async {match &mut pending {Some(future)=>future.await,None=>std::future::pending().await}}=>{
                pending.take();

                if let Err(error)=authority.check_current(requests.binding()){last_diagnostic=Some(result);break Err(invalid(error));}
                if let Err(error)=emit(tx,result){break Err(error);}
            }
            incoming=command(read,&mut partial)=>{
                let incoming=match incoming {Ok(Some(command))=>command,Ok(None)=>break Ok(()),Err(error)=>break Err(error)};

                if let Err(error)=authority.check_current(requests.binding()){break Err(invalid(error));}
                match incoming {
                    Command::Stop=>break Ok(()),
                    Command::Submit {request}=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        match submit(state.clone(),requests.clone(),SignedInput::Text(request),tx){Ok(future)=>pending=Some(future),Err(error)=>{if let Err(error)=emit(tx,json!({"type":"inputError","error":error.to_string()})){break Err(error);}}}
                    }
                    Command::SubmitAudio {request}=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        match submit(state.clone(),requests.clone(),SignedInput::Audio(request),tx){Ok(future)=>pending=Some(future),Err(error)=>{if let Err(error)=emit(tx,json!({"type":"inputError","error":error.to_string()})){break Err(error);}}}
                    }
                    Command::Attach {..}=>{if let Err(error)=emit(tx,json!({"type":"inputError","error":"attach is only valid as the first command"})){break Err(error);}}
                    Command::ReconcileAudio {request}=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        if request.body.thread_id!=requests.binding().thread_id || request.issuer_id!=requests.binding().principal_id {
                            if let Err(error)=emit(tx,json!({"type":"inputError","error":"observation belongs to another attached owner/thread"})){break Err(error);}continue;
                        }
                        let state=state.clone();
                        pending=Some(Box::pin(async move {match crate::audio_observation::reconcile(&state,*request).await {
                            Ok(receipt)=>json!({"type":"audioReconciled","observation":receipt}),Err(error)=>json!({"type":"inputError","error":error.to_string()}),
                        }}));
                    }
                    Command::Reconcile {delivery_id,text}=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        if delivery_id.len()!=64 || !delivery_id.bytes().all(|b|b.is_ascii_digit()||(b'a'..=b'f').contains(&b)){if let Err(error)=emit(tx,json!({"type":"inputError","error":"invalid delivery ID"})){break Err(error);}continue;}
                        let requests=requests.clone();let generation=requests.binding().organ_generation;
                        pending=Some(Box::pin(async move {match requests.reconcile_owner_submission(generation,&format!("hepta.authbus:{delivery_id}"),&text).await {
                            Ok(receipt)=>json!({"type":"reconciled","deliveryId":delivery_id,"receipt":receipt}),Err(error)=>json!({"type":"inputError","deliveryId":delivery_id,"error":error.to_string()}),
                        }}));
                    }
                    Command::CancelRecovered {delivery_id,text}=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        if delivery_id.len()!=64 || !delivery_id.bytes().all(|b|b.is_ascii_digit()||(b'a'..=b'f').contains(&b)){if let Err(error)=emit(tx,json!({"type":"inputError","error":"invalid delivery ID"})){break Err(error);}continue;}
                        let local=owner.interrupt().await;
                        if let Err(error)=emit(tx,json!({"type":"recoveryCancellationPending","deliveryId":delivery_id,"local":local})){break Err(error);}
                        let requests=requests.clone();let generation=requests.binding().organ_generation;
                        pending=Some(Box::pin(async move {match requests.cancel_owner_submission(generation,&format!("hepta.authbus:{delivery_id}"),&text).await {
                            Ok(receipt)=>json!({"type":"recoveredInterruptRequested","deliveryId":delivery_id,"reconciliation":receipt,"terminalObserved":false}),
                            Err(error)=>json!({"type":"inputError","deliveryId":delivery_id,"error":error.to_string()}),
                        }}));
                    }
                    Command::Interrupt=>{let outcome=owner.interrupt().await;if let Err(error)=emit(tx,json!({"type":"interruptRequested","outcome":outcome})){break Err(error);}}
                    Command::Reconnect=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        let _=owner.interrupt().await;
                        let Some(old)=connection.take() else{break Err(invalid("connection missing"));};
                        match old.reconnect(args(state)?,32).await {
                            Ok(new)=>{requests=new.requests.clone();owner=bridge(&new,authority.clone(),tx.clone())?;connection=Some(new);
                                if let Err(error)=emit(tx,json!({"type":"reconnected","connectionId":requests.connection_id(),"binding":requests.binding()})){break Err(error);}},
                            Err(error)=>break Err(invalid(error)),
                        }
                    }
                }
            }
            event=async {match &mut connection {Some(connection)=>connection.events.next().await,None=>Err(HmiError::Fenced)}}=>{
                let event=match event {Ok(Some(event))=>event,Ok(None)=>break Err(invalid("App Server event stream ended")),Err(error)=>break Err(invalid(error))};
                let kind=if matches!(event.kind,HmiEventKindV1::Terminal {..}){UiKind::Context}else{UiKind::Output};
                let scope=event.scope.clone();let outcome=owner.route_output(event).await;
                last_diagnostic=Some(json!({"scope":scope,"error":outcome.error,"interruption":outcome.interruption,
                    "terminal":match &outcome.event.kind {HmiEventKindV1::Terminal {outcome}=>Some(json!({"status":outcome.status,"error":outcome.error})),_=>None}}));

                if tx.try_send(UiEnvelope {value:json!({"type":"output","outcome":outcome}),guard:Some(UiGate {requests:requests.clone(),scope,authority:authority.clone(),kind})}).is_err(){break Err(invalid("UI output queue full or closed"));}
            }
        }
    };
    let interrupted = owner.interrupt().await;
    let pending_outcome=match pending {Some(future)=>Some(tokio::time::timeout(Duration::from_secs(5),future).await.unwrap_or_else(|_|json!({"type":"unknown","error":"original admission still ambiguous; reconcile original delivery ID"}))),None=>None};
    let _ = requests.revoke();
    let shutdown = match connection {
        Some(connection) => connection
            .events
            .shutdown()
            .await
            .err()
            .map(|e| e.to_string()),
        None => None,
    };
    emit(
        tx,
        json!({"type":"sessionTerminal","error":result.as_ref().err().map(std::string::ToString::to_string),"interruption":interrupted,
        "pendingOutcome":pending_outcome,"shutdownError":shutdown,"binding":requests.binding(),"lastDiagnostic":last_diagnostic}),
    )?;
    result
}
