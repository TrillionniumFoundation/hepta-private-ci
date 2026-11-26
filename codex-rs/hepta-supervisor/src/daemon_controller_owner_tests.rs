//! Real Unix child processes and the original durable lifecycle owner.
//! The enrolled client and Agentd protocol peer are controlled test fixtures.
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;

use super::*;
use crate::SupervisorControllerMethod;
use crate::controller_peer::tests::RootCgroup;
use crate::controller_peer::tests::principal;
use crate::daemon::shutdown_tests::Fixture;

const AGENT: &str = r#"#!/usr/bin/python3
import glob,json,os,socket,sys
p=sys.argv[1]; os.makedirs(os.path.dirname(p),mode=0o700,exist_ok=True)
try: os.unlink(p)
except FileNotFoundError: pass
s=socket.socket(socket.AF_UNIX); s.bind(p); s.listen(8)
while True:
 c,_=s.accept()
 try:
  request=json.loads(c.makefile('rb').readline(65537))
  root=os.environ['HEPTA_AGENT_RUN_ROOT']; files=glob.glob(sys.argv[2]+'/lifecycle-*.json')
  state=json.load(open(max(files,key=lambda p:int(p.rsplit('-',1)[1][:-5]))))
  payload={'type':'health','promotion_ready':True,'ready':state['lifecycle']=='running','fenced':False,'lifecycle':state['lifecycle'],'process_id':os.getpid(),'workspace':os.getcwd(),'home_root':os.environ['HEPTA_AGENT_HOME'],'run_root':root}
  if request['method']['type']=='drain': payload={'type':'drain','admission_closed':True,'running_turns':0,'drained':True,'lifecycle':state['lifecycle'],'fenced':False}
  c.sendall((json.dumps({'schema_version':2,'request_id':request['request_id'],'agent_id':os.environ['HEPTA_AGENT_ID'],'spawn_generation':int(os.environ['HEPTA_AGENT_GENERATION']),'current_generation':state['generation'],'payload':payload})+'\n').encode())
 except (BrokenPipeError,ConnectionResetError): pass
 finally: c.close()
"#;

const CLIENT: &str = r#"
import ctypes,os,socket,sys
with open(sys.argv[2]+'/cgroup.procs','w') as f: f.write(str(os.getpid()))
os.setgroups([]); os.setgid(int(sys.argv[4])); os.setuid(int(sys.argv[3]))
assert ctypes.CDLL(None).prctl(4,1)==0
s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.sendall(sys.argv[5].encode()); s.shutdown(socket.SHUT_WR)
if sys.argv[6]=='lost_ack':
 sys.stdin.readline(); s.close()
else:
 b=b''
 while not b.endswith(b'\n'):
  more=s.recv(4096)
  if not more: break
  b+=more
 sys.stdout.buffer.write(b)
"#;

fn client(
    path: &Path,
    cgroup: &RootCgroup,
    request: SupervisorControllerRequest,
    lost_ack: bool,
) -> Result<std::process::Child> {
    let mut frame = serde_json::to_string(&request)?;
    frame.push('\n');
    Ok(Command::new("sudo")
        .args(["-n", "/usr/bin/python3", "-c", CLIENT])
        .arg(path)
        .arg(&cgroup.0)
        .arg(unsafe { libc::geteuid() }.to_string())
        .arg(unsafe { libc::getegid() }.to_string())
        .arg(frame)
        .arg(if lost_ack { "lost_ack" } else { "reply" })
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()?)
}

async fn exchange(
    path: &Path,
    cgroup: &RootCgroup,
    request: SupervisorControllerRequest,
) -> Result<SupervisordPayload> {
    let mut peer = client(path, cgroup, request, false)?;
    let output = tokio::task::spawn_blocking(move || {
        let mut bytes = Vec::new();
        peer.stdout
            .take()
            .context("controller stdout")?
            .read_to_end(&mut bytes)?;
        anyhow::ensure!(peer.wait()?.success(), "controller fixture exited");
        Ok::<_, anyhow::Error>(bytes)
    })
    .await??;
    Ok(serde_json::from_slice::<SupervisordResponse>(&output)?.payload)
}

async fn wait_agent(
    state: &Arc<DaemonState<UnixProcessDriver>>,
    agent: &AgentId,
    running: bool,
) -> Result<SupervisordAgentStatus> {
    let result = timeout(Duration::from_secs(30), async {
        loop {
            let observed = agent_status(state, agent).await?;
            if if running {
                observed.healthy
            } else {
                !observed.active && observed.lifecycle == AgentLifecycle::Stopped
            } {
                return Ok(observed);
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await;
    if result.is_err() {
        eprintln!(
            "controller actual owner deadline agent={:?}",
            agent_status(state, agent).await
        );
        eprintln!(
            "controller actual owner diagnostics={:?}",
            execution::handle_with_request_id(
                Arc::clone(state),
                9999,
                SupervisordMethod::AgentDiagnostics {
                    agent_id: agent.clone()
                }
            )
            .await
        );
    }
    result?
}

async fn committed(path: &Path, cgroup: &RootCgroup, agent: &AgentId, id: u64) -> Result<()> {
    timeout(Duration::from_secs(30), async {
        loop {
            let status = exchange(
                path,
                cgroup,
                SupervisorControllerRequest::new(
                    id + 10_000,
                    SupervisorControllerMethod::Receipt {
                        agent_id: agent.clone(),
                        mutation_request_id: id,
                    },
                ),
            )
            .await?;
            if matches!(status,SupervisordPayload::OrdinaryMutationStatus{status:Some(ref status)}
                if status.request_id==id && status.phase==crate::DurableMutationPhaseV1::Committed)
            {
                return Ok::<_, anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await??;
    Ok(())
}

fn accepted_or_indeterminate(payload: &SupervisordPayload, operation: SupervisordMutation) {
    assert!(
        matches!(payload,SupervisordPayload::MutationAccepted{operation:actual,..}if *actual==operation)
            || matches!(payload,SupervisordPayload::Error{code,..}if code=="operation_indeterminate"),
        "owner outcome: {payload:?}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires sudo and an independent root-owned Linux cgroup"]
async fn controller_original_owner_real_start_stop_restart_stale_and_lost_ack_receipt() -> Result<()>
{
    let fixture = Fixture::new()?;
    let workspace = fixture.temp.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let root = fixture.state.registry.layout().fleet_root().clone();
    let registered = execution::handle_with_request_id(
        Arc::clone(&fixture.state),
        1001,
        SupervisordMethod::RegisterAgent {
            manifest: AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
                ResourceBudget::local_default(),
            )?,
        },
    )
    .await;
    let SupervisordPayload::AgentRegistered { agent: registered } = registered else {
        panic!("registration: {registered:?}")
    };
    let source = fixture.temp.path().join("agentd-fixture");
    std::fs::write(&source, AGENT)?;
    std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o700))?;
    let release = ReleaseId::parse("controller-fixture-v1")?;
    let record = fixture.state.registry.load_agent(&agent)?;
    fixture.state.registry.install_release(
        release.clone(),
        &source,
        vec![
            record.layout.agentd_control_socket().display().to_string(),
            record.layout.owner_run_root().display().to_string(),
        ],
    )?;
    let admitted = execution::handle_with_request_id(
        Arc::clone(&fixture.state),
        1002,
        SupervisordMethod::AllowInstalledRelease {
            fence: registered.control_fence,
            release_id: release.clone(),
        },
    )
    .await;
    let SupervisordPayload::InstalledReleaseAllowed { agent: admitted } = admitted else {
        panic!("admission: {admitted:?}")
    };
    let initial = execution::handle_with_request_id(
        Arc::clone(&fixture.state),
        1003,
        SupervisordMethod::Start {
            fence: admitted.control_fence,
            release_id: release,
        },
    )
    .await;
    assert!(
        matches!(initial, SupervisordPayload::MutationAccepted { .. }),
        "initial owner start: {initial:?}"
    );
    eprintln!("controller actual owner privileged initial start: {initial:?}");
    let state = Arc::clone(&fixture.state);
    let cancellation = fixture.cancellation.clone();
    let ticker = tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = cancellation.cancelled() => break,
                _ = tokio::time::sleep(Duration::from_millis(25)) => execution::tick(Arc::clone(&state), Instant::now()).await,
            }
        }
    });
    let before = wait_agent(&fixture.state, &agent, true).await?;
    eprintln!(
        "controller actual owner initial healthy PID={:?}",
        before.process_id
    );
    let enrolled = RootCgroup::new()?;
    let path = fixture
        .state
        .registry
        .layout()
        .run_root()
        .join("controller/ctl");
    let server = ControllerServer::bind(
        path.clone(),
        Arc::clone(&fixture.state),
        fixture.cancellation.clone(),
        ControllerPeerGate::open(principal(&enrolled)?, "hepta-fleet-test")?,
    )
    .await?;
    let serving = tokio::spawn(server.run());
    let stopped = exchange(
        &path,
        &enrolled,
        SupervisorControllerRequest::new(
            1101,
            SupervisorControllerMethod::Stop {
                fence: before.control_fence.clone(),
            },
        ),
    )
    .await?;
    accepted_or_indeterminate(&stopped, SupervisordMutation::Stop);
    committed(&path, &enrolled, &agent, 1101).await?;
    let idle = wait_agent(&fixture.state, &agent, false).await?;
    let stale = exchange(
        &path,
        &enrolled,
        SupervisorControllerRequest::new(
            1102,
            SupervisorControllerMethod::Restart {
                fence: before.control_fence,
            },
        ),
    )
    .await?;
    assert!(
        matches!(stale, SupervisordPayload::Error { ref code, .. } if code == "stale_control_fence")
    );
    let request = SupervisorControllerRequest::new(
        1103,
        SupervisorControllerMethod::Start {
            fence: idle.control_fence,
        },
    );
    let mut lost = client(&path, &enrolled, request, true)?;
    let started = wait_agent(&fixture.state, &agent, true).await?;
    use std::io::Write;
    lost.stdin
        .take()
        .context("lost ACK stdin")?
        .write_all(b"disconnect\n")?;
    assert!(lost.wait()?.success());
    let receipt = exchange(
        &path,
        &enrolled,
        SupervisorControllerRequest::new(
            1104,
            SupervisorControllerMethod::Receipt {
                agent_id: agent.clone(),
                mutation_request_id: 1103,
            },
        ),
    )
    .await?;
    assert!(
        matches!(receipt, SupervisordPayload::OrdinaryMutationStatus { status: Some(ref status) }
        if status.request_id == 1103 && status.phase == crate::DurableMutationPhaseV1::Committed)
    );
    assert_eq!(
        agent_status(&fixture.state, &agent).await?.process_id,
        started.process_id
    );
    let restarted = exchange(
        &path,
        &enrolled,
        SupervisorControllerRequest::new(
            1105,
            SupervisorControllerMethod::Restart {
                fence: started.control_fence,
            },
        ),
    )
    .await?;
    accepted_or_indeterminate(&restarted, SupervisordMutation::Restart);
    committed(&path, &enrolled, &agent, 1105).await?;
    let after = timeout(Duration::from_secs(30), async {
        loop {
            let after = agent_status(&fixture.state, &agent).await?;
            if after.healthy && after.process_id != started.process_id {
                return Ok::<_, SupervisorError>(after);
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await??;
    assert_ne!(after.process_id, started.process_id);
    let stopped = exchange(
        &path,
        &enrolled,
        SupervisorControllerRequest::new(
            1106,
            SupervisorControllerMethod::Stop {
                fence: after.control_fence,
            },
        ),
    )
    .await?;
    accepted_or_indeterminate(&stopped, SupervisordMutation::Stop);
    committed(&path, &enrolled, &agent, 1106).await?;
    wait_agent(&fixture.state, &agent, false).await?;
    fixture.cancellation.cancel();
    serving.await??;
    ticker.await?;
    assert!(!path.exists());
    Ok(())
}
