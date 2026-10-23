//! Existing Fleet/AuthBus test producer, actual Agentd + embedded App Server.
//! Audio bytes/policy below exist only in disposable private test directories.
use crate::authbus_fixture::{hex, signed_text, write_checkpoint, write_trust};
use crate::support::fleet::{AgentFixture, FleetHarness, connect_app_server_with_experimental};
use anyhow::{Context,Result,ensure};
use app_test_support::MockResponsesConfig;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_protocol::{ClientRequest,RequestId,ThreadReadParams,ThreadReadResponse,ThreadStartParams,ThreadStartResponse};
use codex_hepta_agentd::{AuthBusTextIngress,AudioObservationBodyV1,SignedAudioObservationV1,audio_observation_claims,authbus_text_claims};
use codex_hepta_codex_adapter::hmi::{HmiCapturedAudioRefV1,HmiCaptureStreamV1};
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::Digest32;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::{Signer,SigningKey};
use serde_json::{Value,json};
use std::os::unix::fs::{OpenOptionsExt,PermissionsExt};
use std::path::PathBuf;
use std::time::{Duration,Instant,SystemTime,UNIX_EPOCH};
use tokio::io::{AsyncBufReadExt,AsyncWriteExt,BufReader,ReadHalf,WriteHalf};
pub(crate) const INPUT: &str="请在原来的同一个线程回答中文";
pub(crate) const ANSWER: &str="你好，同一个线程";
pub(crate) enum Profile { Text, TemporaryAudio }
pub(crate) struct Fixture {
    pub(crate) fleet:FleetHarness,
    pub(crate) agent:AgentFixture,
    client:Option<RemoteAppServerClient>,
    pub(crate) thread:String,
    pub(crate) key:SigningKey,
    pub(crate) trust:PathBuf,
    pub(crate) audio_policy:Option<PathBuf>,
    pub(crate) generation:u64,
    pub(crate) pid:u32,
    _checkpoint:tempfile::TempDir,
}
impl Fixture {
    pub(crate) async fn new(model:&wiremock::MockServer, profile:Profile)->Result<Self> {
        let mut fleet=FleetHarness::new()?;
        let agent=fleet.register("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13","hmi-product-workspace")?;
        MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
        let key=SigningKey::from_bytes(&[91;32]); // Existing test identity; private key never persisted.
        let trust=agent.layout.home_root().join("authbus-trust.json");
        std::fs::set_permissions(agent.layout.home_root(),std::fs::Permissions::from_mode(0o700))?;
        write_trust(&trust,&agent.agent_id,&key,&[],/*revoked*/false)?;
        let checkpoint=tempfile::tempdir()?;
        std::fs::set_permissions(checkpoint.path(),std::fs::Permissions::from_mode(0o700))?;
        let checkpoint_file=checkpoint.path().join("authbus-replay-checkpoint.json");
        let store=HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(agent.layout.home_root())?)).await?;
        let frontier=store.authbus_replay_frontier_digest().await?; drop(store);
        write_checkpoint(&checkpoint_file,&agent.agent_id,1,frontier)?;
        let audio_policy=match profile {
            Profile::Text=>{fleet.start_with_hmi_text(&agent,&trust,&checkpoint_file)?;None},
            Profile::TemporaryAudio=>{
                let root=agent.layout.home_root().join("media"); std::fs::create_dir(&root)?;
                std::fs::set_permissions(&root,std::fs::Permissions::from_mode(0o700))?;
                let path=agent.layout.home_root().join("audio-authority.json");
                let policy=json!({"schema_version":1,"agent_id":agent.agent_id.as_str(),"issuer_id":"issuer:native-authbus-test","key_epoch":1,
                    "device_id":"device:temporary-pcm-fixture","device_generation":7,"organ_id":"pipecat:fixture","organ_generation":11,
                    "capture_generation":3,"media_root":root,"max_segment_bytes":1048576,"expires_at_ms":now_ms()?+300000,"revoked":false});
                write_policy(&path,&policy)?;
                // All fixture agents are already registered. Start the same
                // supervised binary with this explicit disposable profile.
                let command=codex_hepta_supervisor::AgentCommand::new(codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?,vec![
                    "--hmi-text".into(),"--authbus-trust-file".into(),trust.as_os_str().to_owned(),
                    "--authbus-checkpoint-file".into(),checkpoint_file.as_os_str().to_owned(),
                    "--hmi-audio-authority-file".into(),path.as_os_str().to_owned(),
                ])?;
                fleet.supervisor.start(&agent.agent_id,command,Instant::now())?;Some(path)
            }
        };
        let (control,health)=fleet.wait_ready(&agent,1).await?;
        let ingress=control.session_ingress().await?;
        let client=connect_app_server_with_experimental(&ingress.socket_path,"hmi-product-fixture",64,/*experimental_api*/true).await?;
        let response:ThreadStartResponse=client.request_typed(ClientRequest::ThreadStart {request_id:RequestId::Integer(1),params:ThreadStartParams {
            cwd:Some(agent.workspace.to_string_lossy().into_owned()),ephemeral:Some(false),..Default::default()
        }}).await?;
        let thread=response.thread.id;
        write_trust(&trust,&agent.agent_id,&key,std::slice::from_ref(&thread),/*revoked*/false)?;
        Ok(Self {fleet,agent,client:Some(client),thread,key,trust,audio_policy,generation:1,pid:health.process_id,_checkpoint:checkpoint})
    }
    pub(crate) fn request(&self,sequence:u64)->Result<AuthBusTextIngress> {
        let mut request=signed_text(&self.agent.agent_id,&self.key,&self.thread,sequence)?;
        request.body.spawn_generation=self.generation;request.body.text=INPUT.into();
        request.signature_hex=hex(&self.key.sign(&authbus_text_claims(&self.agent.agent_id,&request)?.signing_bytes()).to_bytes());Ok(request)
    }
    pub(crate) fn audio(&self,sequence:u64,pcm:&[u8])->Result<SignedAudioObservationV1> {
        use std::io::Write;
        let policy_path=self.audio_policy.as_ref().context("no fixture audio policy")?;
        let bytes=std::fs::read(policy_path)?;let policy:Value=serde_json::from_slice(&bytes)?;
        let source=HmiCapturedAudioRefV1 {stream:HmiCaptureStreamV1 {
            principal_id:"issuer:native-authbus-test".into(),device_id:"device:temporary-pcm-fixture".into(),device_generation:7,
            organ_id:"pipecat:fixture".into(),organ_generation:11,logical_session_id:format!("thread:{}",self.thread),
        },capture_generation:3,sequence,asset_id:format!("capture-3-{sequence}.pcm16"),sha256:Digest32::of_bytes(pcm).to_string(),
            byte_length:pcm.len() as u64,sample_rate:16000,num_channels:1,start_sample:160,end_sample:160+(pcm.len()/2) as u64};
        let mut file=std::fs::OpenOptions::new().create_new(true).write(true).mode(0o600).open(PathBuf::from(policy["media_root"].as_str().context("media root")?).join(&source.asset_id))?;
        file.write_all(pcm)?;file.sync_all()?;
        let mut request=SignedAudioObservationV1 {issuer_id:"issuer:native-authbus-test".into(),key_epoch:1,message_id:format!("audio:fixture:{sequence}"),sequence,
            expires_at_ms:now_ms()?+300000,signature_hex:String::new(),body:AudioObservationBodyV1 {spawn_generation:self.generation,thread_id:self.thread.clone(),text:INPUT.into(),authority_sha256:Digest32::of_bytes(&bytes).to_string(),source}};
        self.sign_audio(&mut request)?;Ok(request)
    }
    pub(crate) fn sign_audio(&self,request:&mut SignedAudioObservationV1)->Result<()> {
        request.signature_hex=hex(&self.key.sign(&audio_observation_claims(&self.agent.agent_id,request)?.signing_bytes()).to_bytes());Ok(())
    }
    pub(crate) async fn ui(&self)->Result<Ui> {
        let path=self.agent.layout.run_root().join("hmi-text.sock");
        let stream=tokio::time::timeout(Duration::from_secs(10),async {loop {match codex_uds::UnixStream::connect(&path).await {
            Ok(stream)=>return Ok::<_,std::io::Error>(stream),
            Err(e) if matches!(e.kind(),std::io::ErrorKind::NotFound|std::io::ErrorKind::ConnectionRefused)=>tokio::time::sleep(Duration::from_millis(25)).await,
            Err(e)=>return Err(e),
        }}}).await.with_context(||format!("HMI socket connect timed out; supervisor={:?}",self.fleet.supervisor.snapshot(&self.agent.agent_id)))??;
        let (read,write)=tokio::io::split(stream);Ok(Ui {read:BufReader::new(read),write})
    }
    pub(crate) async fn restart(&mut self)->Result<()> {
        if let Some(client)=self.client.take() {client.shutdown().await?;}
        let previous=self.generation;let pid=self.pid;
        self.fleet.supervisor.restart(&self.agent.agent_id,Instant::now())?;
        let (control,health)=self.fleet.wait_new_spawn(&self.agent,previous).await?;
        ensure!(health.process_id!=pid,"restart did not replace the actual Agentd/App Server process");
        self.generation=self.fleet.supervisor.snapshot(&self.agent.agent_id).and_then(|s|s.spawn_generation).context("new spawn generation")?;
        self.pid=health.process_id;
        let ingress=control.session_ingress().await?;
        self.client=Some(connect_app_server_with_experimental(&ingress.socket_path,"hmi-product-after-restart",64,/*experimental_api*/true).await?);
        println!("ACTUAL_HMI_PROCESS_RESTART={{\"previousPid\":{pid},\"newPid\":{},\"generation\":{}}}",self.pid,self.generation);
        Ok(())
    }
    pub(crate) async fn crash_and_restart(&mut self)->Result<()> {
        self.fleet.supervisor.kill(&self.agent.agent_id)?;
        let deadline=Instant::now()+Duration::from_secs(15);
        loop {
            let report=self.fleet.supervisor.tick(Instant::now());
            ensure!(report.faults.is_empty(),"crash retirement faults: {:?}",report.faults);
            if self.fleet.supervisor.snapshot(&self.agent.agent_id).is_some_and(|s|!s.active) {break;}
            ensure!(Instant::now()<deadline,"actual Agentd did not exit after supervised crash");
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        self.restart().await
    }
    pub(crate) async fn read_thread(&self)->Result<ThreadReadResponse> {
        Ok(self.client.as_ref().context("client missing")?.request_typed(ClientRequest::ThreadRead {request_id:RequestId::Integer(5),params:ThreadReadParams {thread_id:self.thread.clone(),include_turns:true}}).await?)
    }
    pub(crate) async fn evidence_pool(&self)->Result<sqlx::SqlitePool> {
        let sqlite=SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(self.agent.layout.home_root())?);
        Ok(sqlite.open_read_only_pool(&self.agent.layout.home_root().join(codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE)).await?)
    }
}
pub(crate) fn write_policy(path:&std::path::Path,policy:&Value)->Result<()> {
    let mut file=tempfile::NamedTempFile::new_in(path.parent().context("policy parent")?)?;
    file.as_file().set_permissions(std::fs::Permissions::from_mode(0o600))?;
    serde_json::to_writer(file.as_file_mut(),policy)?;file.as_file().sync_all()?;file.persist(path)?;Ok(())
}
pub(crate) struct Ui {read:BufReader<ReadHalf<codex_uds::UnixStream>>,pub(crate) write:WriteHalf<codex_uds::UnixStream>}
impl Ui {
    pub(crate) async fn send(&mut self,value:Value)->Result<()> {self.write.write_all(format!("{value}\n").as_bytes()).await?;Ok(())}
    pub(crate) async fn next(&mut self)->Result<Value> {
        let mut line=String::new();let n=tokio::time::timeout(Duration::from_secs(20),self.read.read_line(&mut line)).await??;
        ensure!(n>0 && n<=65536,"HMI closed or exceeded frame bound");Ok(serde_json::from_str(&line)?)
    }
    pub(crate) async fn until(&mut self,kind:&str)->Result<Value> {loop {let event=self.next().await?;ensure!(event["type"]!="sessionError" && event["type"]!="inputError","{event}");if event["type"]==kind {return Ok(event);}}}
    pub(crate) async fn completed(&mut self)->Result<Value> {loop {let event=self.next().await?;ensure!(event["type"]!="sessionError" && event["type"]!="inputError","{event}");if event["type"]=="output" && event["outcome"]["event"]["kind"]["type"]=="terminal" {
        ensure!(event["outcome"]["event"]["kind"]["outcome"]["status"]=="completed","{event}");return Ok(event);
    }}}
}
pub(crate) async fn sends(server:&wiremock::MockServer)->usize {server.received_requests().await.unwrap_or_default().iter().filter(|r|r.url.path().ends_with("/responses")).count()}
fn now_ms()->Result<u64> {Ok(u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?)}
