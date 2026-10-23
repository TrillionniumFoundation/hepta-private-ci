//! One bounded UI connection, with an existing thread and canonical AuthBus IDs.
use super::*;
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
    Reconcile { delivery_id: String, text: String },
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
    request: &AuthBusTextIngress,
) -> Result<HmiConnectionV1, AgentdError> {
    authenticate(state, request)?;
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
                    thread_id: request.body.thread_id.clone(),
                    include_turns: false,
                },
            })
            .await
            .map_err(invalid)?;
        if read.thread.ephemeral || read.thread.id != request.body.thread_id {
            return Err(invalid("existing persistent thread required"));
        }
        Ok(HmiBindingV1 {
            principal_id: request.issuer_id.clone(),
            device_id: format!("agent-ui:{}", state.identity().agent_id),
            device_generation: request.key_epoch,
            organ_id: "hmi:text".into(),
            organ_generation: state.identity().spawn_generation,
            logical_session_id: format!("thread:{}", read.thread.id),
            thread_id: read.thread.id,
            app_server_session_id: read.thread.session_id,
            codex_home: state.identity().home_root.to_string_lossy().into_owned(),
            app_server_version: version,
        })
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
    request: AuthBusTextIngress,
    tx: &Sender,
) -> Result<Pending, AgentdError> {
    let delivery = authenticate(&state, &request)?;
    if request.body.thread_id != requests.binding().thread_id
        || request.issuer_id != requests.binding().principal_id
        || request.key_epoch != requests.binding().device_generation
    {
        return Err(invalid(
            "signed input belongs to another attached owner/thread",
        ));
    }
    requests
        .observe_owner_submission(
            state.identity().spawn_generation,
            request.sequence,
            &format!("hepta.authbus:{delivery}"),
            &request.body.text,
        )
        .map_err(invalid)?;
    let context = json!({"deliveryId":delivery,"messageId":request.message_id,"threadId":request.body.thread_id,"text":request.body.text});
    emit(tx, json!({"type":"admissionPending","input":context}))?;
    Ok(Box::pin(async move {
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            crate::authbus_ingress::submit(&state, request),
        )
        .await;
        match result {
            Ok(Ok(receipt)) if receipt.delivery_id == delivery => {
                json!({"type":"admission","input":context,"receipt":receipt})
            }
            other => {
                let _ = requests.stop_output(state.identity().spawn_generation);
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
    let Some(Command::Submit { request }) = first else {
        return Err(invalid(
            "first command must carry a signed Submit for an existing thread",
        ));
    };
    let mut connection = Some(connect(state, &request).await?);
    let mut requests = connection
        .as_ref()
        .ok_or_else(|| invalid("connection missing"))?
        .requests
        .clone();
    let mut owner = bridge(
        connection
            .as_ref()
            .ok_or_else(|| invalid("connection missing"))?,
        state.clone(),
        active.clone(),
        tx.clone(),
    )?;
    let mut pending = Some(submit(state.clone(), requests.clone(), request, tx)?);
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
                let authority=TextAuthority {state:state.clone(),active:active.clone(),binding:requests.binding().clone()};
                if let Err(error)=authority.check_current(requests.binding()){break Err(invalid(error));}
            }
            result=async {match &mut pending {Some(future)=>future.await,None=>std::future::pending().await}}=>{
                pending.take();
                let authority=TextAuthority {state:state.clone(),active:active.clone(),binding:requests.binding().clone()};
                if let Err(error)=authority.check_current(requests.binding()){last_diagnostic=Some(result);break Err(invalid(error));}
                if let Err(error)=emit(tx,result){break Err(error);}
            }
            incoming=command(read,&mut partial)=>{
                let incoming=match incoming {Ok(Some(command))=>command,Ok(None)=>break Ok(()),Err(error)=>break Err(error)};
                let authority=TextAuthority {state:state.clone(),active:active.clone(),binding:requests.binding().clone()};
                if let Err(error)=authority.check_current(requests.binding()){break Err(invalid(error));}
                match incoming {
                    Command::Stop=>break Ok(()),
                    Command::Submit {request}=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        match submit(state.clone(),requests.clone(),request,tx){Ok(future)=>pending=Some(future),Err(error)=>{if let Err(error)=emit(tx,json!({"type":"inputError","error":error.to_string()})){break Err(error);}}}
                    }
                    Command::Reconcile {delivery_id,text}=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        if delivery_id.len()!=64 || !delivery_id.bytes().all(|b|b.is_ascii_digit()||(b'a'..=b'f').contains(&b)){if let Err(error)=emit(tx,json!({"type":"inputError","error":"invalid delivery ID"})){break Err(error);}continue;}
                        let requests=requests.clone();let generation=state.identity().spawn_generation;
                        pending=Some(Box::pin(async move {match requests.reconcile_owner_submission(generation,&format!("hepta.authbus:{delivery_id}"),&text).await {
                            Ok(receipt)=>json!({"type":"reconciled","deliveryId":delivery_id,"receipt":receipt}),Err(error)=>json!({"type":"inputError","deliveryId":delivery_id,"error":error.to_string()}),
                        }}));
                    }
                    Command::Interrupt=>{let outcome=owner.interrupt().await;if let Err(error)=emit(tx,json!({"type":"interruptRequested","outcome":outcome})){break Err(error);}}
                    Command::Reconnect=>{
                        if pending.is_some(){if let Err(error)=emit(tx,json!({"type":"inputError","error":"input slot busy"})){break Err(error);}continue;}
                        let _=owner.interrupt().await;
                        let Some(old)=connection.take() else{break Err(invalid("connection missing"));};
                        match old.reconnect(args(state)?,32).await {
                            Ok(new)=>{requests=new.requests.clone();owner=bridge(&new,state.clone(),active.clone(),tx.clone())?;connection=Some(new);
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
                let authority=TextAuthority {state:state.clone(),active:active.clone(),binding:requests.binding().clone()};
                if tx.try_send(UiEnvelope {value:json!({"type":"output","outcome":outcome}),guard:Some(UiGate {requests:requests.clone(),scope,authority,kind})}).is_err(){break Err(invalid("UI output queue full or closed"));}
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
        json!({"type":"sessionTerminal","error":result.as_ref().err().map(|e|e.to_string()),"interruption":interrupted,
        "pendingOutcome":pending_outcome,"shutdownError":shutdown,"binding":requests.binding(),"lastDiagnostic":last_diagnostic}),
    )?;
    result
}
