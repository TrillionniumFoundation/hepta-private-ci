//! Fixed ingress barriers plus an independent durable/admission state oracle.
//! The peer is protocol software; no STT/TTS, hardware or production signer.
use super::*;
use futures::SinkExt;
use std::sync::atomic::AtomicUsize;
use tokio::sync::Notify;
use tokio_tungstenite::tungstenite::Message;

#[derive(Clone, Copy, PartialEq)]
enum PauseAt { Verified, Committed }
struct Gate { point: PauseAt, used: AtomicBool, reached: Notify, resume: Notify }
impl Gate {
    async fn pause(&self, point: PauseAt) {
        if self.point == point && !self.used.swap(true, Ordering::SeqCst) {
            self.reached.notify_one();
            self.resume.notified().await;
        }
    }
}
struct DelayedMedia { inner: FixtureMedia, gate: Arc<Gate> }
impl HmiOwnerMediaV1 for DelayedMedia {
    fn connection_id(&self)->u64 { self.inner.connection_id() }
    fn capture_generation(&self)->u64 { self.inner.capture_generation() }
    async fn verify_source(&self, source:&HmiCapturedAudioRefV1)->Result<(),HmiError> {
        self.inner.verify_source(source).await?;
        self.gate.pause(PauseAt::Verified).await;
        Ok(())
    }
    async fn attach_turn(&self,scope:&HmiOutputScopeV1)->Result<(),HmiError> { self.inner.attach_turn(scope).await }
    async fn speak(&self,request:HmiSpeechRequestV1)->Result<HmiMediaPresentationV1,HmiError> { self.inner.speak(request).await }
    async fn retire_output(&self,epoch:u64)->Result<(),HmiError> { self.inner.retire_output(epoch).await }
    async fn revoke_capture(&self)->Result<(),HmiError> { self.inner.revoke_capture().await }
}
struct DelayedObservations { inner: FixtureObservations, gate: Arc<Gate> }
impl HmiOwnerObservationsV1 for DelayedObservations {
    async fn observe_final(&self,binding:&HmiBindingV1,input:&HmiOwnerTranscriptV1,client:&str,digest:&str,mode:ThreadQueueReconcileMode)->Result<HmiObservationReceiptV1,HmiError> {
        let receipt=self.inner.observe_final(binding,input,client,digest,mode).await?;
        self.gate.pause(PauseAt::Committed).await;
        Ok(receipt)
    }
}

async fn check_cancelled_ingress(point:PauseAt)->Result<(),Box<dyn std::error::Error+Send+Sync>> {
    let (listener,url)=listener().await;
    let admissions=Arc::new(AtomicUsize::new(0));
    let reads=Arc::new(AtomicUsize::new(0));
    let count=admissions.clone();let lookups=reads.clone();
    let (finish,mut done)=tokio::sync::oneshot::channel();
    let peer=tokio::spawn(async move {
        let mut socket=accept_async(listener.accept().await?.0).await?;
        initialize(&mut socket).await;
        loop {
            tokio::select! {
                _=&mut done=>break,
                event=socket.next()=>{
                    let Some(event)=event else {break};
                    match event? {
                        Message::Text(text)=>{
                            let request:serde_json::Value=serde_json::from_str(text.as_str())?;
                            assert_eq!(request["method"],"thread/queue/reconcile");
                            if request["params"]["mode"]=="allowIfAbsent" {count.fetch_add(1,Ordering::SeqCst);} else {lookups.fetch_add(1,Ordering::SeqCst);}
                            reply(&mut socket,&request,admission(&request,true)).await;
                        }
                        Message::Close(_)=>break,
                        Message::Ping(bytes)=>socket.send(Message::Pong(bytes)).await?,
                        _=>{}
                    }
                }
            }
        }
        let _=socket.close(None).await;
        Ok::<(),Box<dyn std::error::Error+Send+Sync>>(())
    });
    let connection=HmiConnectionV1::connect(args(&url),binding(),16,Duration::from_secs(3)).await?;
    let (authority,media,observations,input)=ports(connection.requests.connection_id());
    let receipts=observations.records.clone();
    let gate=Arc::new(Gate {point,used:AtomicBool::new(false),reached:Notify::new(),resume:Notify::new()});
    let owner=Arc::new(HmiOwnerBridgeV1::attach(connection.requests.clone(),authority,DelayedMedia {inner:media,gate:gate.clone()},DelayedObservations {inner:observations,gate:gate.clone()})?);
    let held=owner.clone();let original=input.clone();
    let pending=tokio::spawn(async move {held.route_transcript(original,ThreadQueueReconcileMode::AllowIfAbsent).await});
    tokio::time::timeout(Duration::from_secs(3),gate.reached.notified()).await?;
    // Independent oracle: cancellation wins before Core admission; a source
    // observation already committed at the barrier remains retained once.
    let durable_count=usize::from(point==PauseAt::Committed);
    assert_eq!(receipts.lock().map_err(|_|HmiError::Fenced)?.len(),durable_count);
    let stopped=owner.interrupt().await;
    assert!(!stopped.terminal_observed);
    gate.resume.notify_one();
    let outcome=tokio::time::timeout(Duration::from_secs(3),pending).await??;
    assert_eq!(outcome.error,Some(HmiError::Fenced.to_string()),"a pre-cancel input rearmed: {outcome:?}");
    assert!(outcome.admission.is_none());
    assert_eq!(usize::from(outcome.observation.is_some()),durable_count);
    assert_eq!(admissions.load(Ordering::SeqCst),0,"cancelled original request reached Core");
    assert_eq!(receipts.lock().map_err(|_|HmiError::Fenced)?.len(),durable_count);
    assert!(!connection.requests.shared.state.lock().map_err(|_|HmiError::Fenced)?.output_enabled);
    if point==PauseAt::Committed {
        let recovered=owner.route_transcript(input.clone(),ThreadQueueReconcileMode::ReconcileOnly).await;
        assert!(recovered.error.is_none(),"{recovered:?}");
        assert!(recovered.observation.is_some());
        assert_eq!(admissions.load(Ordering::SeqCst),0);
        assert_eq!(reads.load(Ordering::SeqCst),1);
        assert!(!connection.requests.shared.state.lock().map_err(|_|HmiError::Fenced)?.output_enabled);
    }
    // A later distinct intent is allowed; cancellation is no permanent revoke.
    let mut next=input;next.source.sequence=2;next.source.asset_id="capture-1-2.pcm16".into();
    let fresh=owner.route_transcript(next,ThreadQueueReconcileMode::AllowIfAbsent).await;
    assert!(fresh.error.is_none(),"{fresh:?}");
    assert_eq!(admissions.load(Ordering::SeqCst),1);
    assert_eq!(receipts.lock().map_err(|_|HmiError::Fenced)?.len(),durable_count+1);
    let _=finish.send(());
    connection.events.shutdown().await?;
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn interrupt_during_source_verification_cannot_create_observation_or_rearm_same_input()->Result<(),Box<dyn std::error::Error+Send+Sync>> {
    check_cancelled_ingress(PauseAt::Verified).await
}
#[tokio::test]
async fn interrupt_after_source_commit_retains_receipt_without_core_admission_or_replay()->Result<(),Box<dyn std::error::Error+Send+Sync>> {
    check_cancelled_ingress(PauseAt::Committed).await
}

#[tokio::test]
async fn fixed_seed_late_events_cannot_cross_reconnection_and_organ_generation()->Result<(),Box<dyn std::error::Error+Send+Sync>> {
    // Four fixed schedules cover final/completion on either side of a late
    // partial. The model's only durable state is the exact client ID/digest map.
    for seed in [0xC0FFEE00_u64,0xC0FFEE01,0xC0FFEE02,0xC0FFEE03] {
        let (listener,url)=listener().await;
        let durable=Arc::new(Mutex::new(BTreeMap::<String,String>::new()));
        let oracle=durable.clone();
        let interrupts=Arc::new(AtomicUsize::new(0));let interrupted=interrupts.clone();
        let peer=tokio::spawn(async move {
            for incarnation in 0..2 {
                let mut socket=accept_async(listener.accept().await?.0).await?;
                initialize(&mut socket).await;
                while let Some(event)=socket.next().await {
                    let request:serde_json::Value=match event? {
                        Message::Text(text)=>serde_json::from_str(text.as_str())?,
                        Message::Close(_)=>break,
                        Message::Ping(bytes)=>{socket.send(Message::Pong(bytes)).await?;continue;}
                        _=>continue,
                    };
                    match request["method"].as_str() {
                        Some("thread/queue/reconcile")=>{
                            let id=request["params"]["clientUserMessageId"].as_str().ok_or(HmiError::Identity)?.to_owned();
                            let digest=request["params"]["expectedPayloadSha256"].as_str().ok_or(HmiError::Identity)?.to_owned();
                            let created={
                                let mut records=oracle.lock().map_err(|_|HmiError::Fenced)?;
                                if let Some(previous)=records.get(&id) {assert_eq!(previous,&digest);false}
                                else {assert_eq!(request["params"]["mode"],"allowIfAbsent");records.insert(id,digest);true}
                            };
                            reply(&mut socket,&request,admission(&request,true)).await;
                            if created {
                                started(&mut socket,&request).await;
                                if incarnation==0 {delta(&mut socket,"thread:test","before cancellation").await;}
                            }
                        }
                        Some("turn/interrupt")=>{
                            interrupted.fetch_add(1,Ordering::SeqCst);
                            reply(&mut socket,&request,json!({})).await;
                            let order=match seed&3 {0=>[0,1,2],1=>[2,0,1],2=>[1,2,0],_=>[1,0,2]};
                            for kind in order {
                                match kind {
                                    0=>delta(&mut socket,"thread:test","late partial").await,
                                    1=>notification(&mut socket,"item/completed",json!({"threadId":"thread:test","turnId":"turn:test","item":{"type":"agentMessage","id":"answer:test","text":"late final","phase":null}})).await,
                                    _=>completed(&mut socket,"completed").await,
                                }
                            }
                        }
                        method=>panic!("unexpected model operation {method:?}"),
                    }
                }
            }
            Ok::<(),Box<dyn std::error::Error+Send+Sync>>(())
        });
        let mut old=HmiConnectionV1::connect(args(&url),binding(),16,Duration::from_secs(3)).await?;
        old.requests.submit_text(7,1,"original-request","input",ThreadQueueReconcileMode::AllowIfAbsent).await?;
        let _=old.events.next().await?.ok_or(HmiError::Fenced)?;
        let stale_partial=old.events.next().await?.ok_or(HmiError::Fenced)?;
        old.requests.interrupt(7).await?;
        let retired=old.events.next().await?.ok_or(HmiError::Fenced)?;
        assert!(matches!(retired.kind,HmiEventKindV1::Terminal {..}),"seed {seed}: late text escaped cancellation");
        assert_eq!(old.requests.take_completed_speech(7)?,None);
        let old_handle=old.requests.clone();
        old.events.shutdown().await?;
        let mut next_binding=binding();next_binding.organ_generation=8;
        let mut current=HmiConnectionV1::connect(args(&url),next_binding,16,Duration::from_secs(3)).await?;
        assert_eq!(old_handle.client_message_id("original-request")?,current.requests.client_message_id("original-request")?);
        assert_eq!(old_handle.take_completed_speech(7),Err(HmiError::Fenced));
        current.requests.submit_text(8,1,"original-request","input",ThreadQueueReconcileMode::ReconcileOnly).await?;
        assert_eq!(current.requests.take_completed_speech(8)?,None);
        current.requests.submit_text(8,2,"fresh-request","fresh",ThreadQueueReconcileMode::AllowIfAbsent).await?;
        let fresh=current.events.next().await?.ok_or(HmiError::Fenced)?;
        assert!(current.requests.permits_output(&fresh.scope)?);
        let (authority,media,observations,_)=ports(current.requests.connection_id());
        let calls=media.calls.clone();
        let owner=HmiOwnerBridgeV1::attach_text(current.requests.clone(),authority,media,observations)?;
        let mut stale_final=stale_partial.clone();
        stale_final.kind=HmiEventKindV1::TextFinal {item_id:"answer:test".into(),text:"late final".into()};
        for event in [stale_partial,stale_final,retired] {
            let outcome=owner.route_output(event).await;
            assert_eq!(outcome.error,Some(HmiError::Fenced.to_string()));
            assert!(outcome.interruption.is_none(),"old generation interrupted the new output");
            assert!(current.requests.permits_output(&fresh.scope)?);
        }
        assert!(calls.lock().map_err(|_|HmiError::Fenced)?.is_empty());
        current.requests.submit_text(8,2,"fresh-request","fresh",ThreadQueueReconcileMode::AllowIfAbsent).await?;
        assert!(current.requests.permits_output(&fresh.scope)?);
        assert_eq!(durable.lock().map_err(|_|HmiError::Fenced)?.len(),2,"duplicate/recovery dispatched a replacement");
        assert_eq!(interrupts.load(Ordering::SeqCst),1);
        current.events.shutdown().await?;
        peer.await??;
    }
    Ok(())
}
