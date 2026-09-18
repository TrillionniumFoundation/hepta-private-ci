use std::collections::BTreeMap;
use std::path::PathBuf;

use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use tokio::runtime::Runtime;

use crate::runtime::BackendPort;
use crate::runtime::BackendSession;
use crate::runtime::BackendView;
use crate::runtime::EndpointManifest;
use crate::runtime::NativeError;
use crate::runtime::SessionFence;

pub struct AgentdBackend {
    runtime: Runtime,
    client: AgentdClient,
    agent_id: AgentId,
    spawn_generation: u64,
    socket_path: PathBuf,
}

impl AgentdBackend {
    pub fn new(
        socket_path: PathBuf,
        agent_id: AgentId,
        spawn_generation: u64,
    ) -> Result<Self, NativeError> {
        if spawn_generation == 0 {
            return Err(NativeError::Backend(
                "Agentd spawn generation must be non-zero".to_string(),
            ));
        }
        let client = AgentdClient::new(socket_path.clone(), agent_id.clone(), spawn_generation)
            .map_err(|error| NativeError::Backend(error.to_string()))?;
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .map_err(|error| NativeError::Backend(format!("build Agentd client runtime: {error}")))?;
        Ok(Self {
            runtime,
            client,
            agent_id,
            spawn_generation,
            socket_path,
        })
    }

    pub fn endpoint_manifest(&self) -> EndpointManifest {
        EndpointManifest {
            endpoint_id: self.agent_id.to_string(),
            manifest_digest: self.expected_manifest_digest(),
            protocol_version: AGENTD_CONTROL_SCHEMA_VERSION,
        }
    }

    fn expected_manifest_digest(&self) -> Sha256Digest {
        #[derive(Serialize)]
        struct Binding<'a> {
            schema: &'static str,
            agent_id: &'a str,
            generation: u64,
            socket: String,
            protocol: u32,
        }
        let binding = Binding {
            schema: "hepta.ui.native.agentd-endpoint.v1",
            agent_id: self.agent_id.as_str(),
            generation: self.spawn_generation,
            socket: self.socket_path.to_string_lossy().into_owned(),
            protocol: AGENTD_CONTROL_SCHEMA_VERSION,
        };
        let bytes = serde_json::to_vec(&binding).unwrap_or_default();
        Sha256Digest::for_bytes(&bytes)
    }

    fn session_observation(&self) -> Result<(codex_hepta_agentd::HealthSnapshot, String), NativeError> {
        let health = self
            .runtime
            .block_on(self.client.health())
            .map_err(|error| NativeError::Backend(format!("Agentd health: {error}")))?;
        if !health.ready || health.fenced {
            return Err(NativeError::Backend(
                "Agentd is not an unfenced running owner".to_string(),
            ));
        }
        let ingress = self
            .runtime
            .block_on(self.client.session_ingress())
            .map_err(|error| NativeError::Backend(format!("Agentd session ingress: {error}")))?;
        let identity = format!(
            "{}:{}:{}:{}:{:?}",
            self.agent_id,
            self.spawn_generation,
            health.process_id,
            ingress.socket_path.display(),
            ingress.transport
        );
        let digest = Sha256Digest::for_bytes(identity.as_bytes());
        Ok((health, format!("native.{}", &digest.as_str()[..48])))
    }
}

impl BackendPort for AgentdBackend {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<BackendSession, NativeError> {
        manifest.validate()?;
        if manifest.endpoint_id != self.agent_id.as_str()
            || manifest.protocol_version != AGENTD_CONTROL_SCHEMA_VERSION
            || manifest.manifest_digest != self.expected_manifest_digest()
        {
            return Err(NativeError::Backend(
                "native endpoint manifest does not match configured Agentd owner".to_string(),
            ));
        }
        let (_health, session_id) = self.session_observation()?;
        let capabilities = self
            .runtime
            .block_on(self.client.capabilities())
            .map_err(|error| NativeError::Backend(format!("Agentd capabilities: {error}")))?;
        capabilities
            .validate()
            .map_err(|error| NativeError::Backend(format!("Agentd capabilities invalid: {error}")))?;
        Ok(BackendSession {
            fence: SessionFence {
                session_id,
                generation: self.spawn_generation,
            },
            endpoint_id: manifest.endpoint_id.clone(),
            manifest_digest: manifest.manifest_digest.clone(),
            protocol_version: manifest.protocol_version,
        })
    }

    fn read_view(&mut self, session: &BackendSession) -> Result<BackendView, NativeError> {
        if session.fence.generation != self.spawn_generation {
            return Err(NativeError::Backend(
                "requested view belongs to another Agentd generation".to_string(),
            ));
        }
        let (health, current_session_id) = self.session_observation()?;
        if current_session_id != session.fence.session_id {
            return Err(NativeError::Backend(
                "Agentd process/session identity changed; reconnect required".to_string(),
            ));
        }
        let lifecycle = self
            .runtime
            .block_on(self.client.lifecycle())
            .map_err(|error| NativeError::Backend(format!("Agentd lifecycle: {error}")))?;
        if lifecycle.fenced {
            return Err(NativeError::Backend(
                "Agentd lifecycle became fenced".to_string(),
            ));
        }
        let events = self
            .runtime
            .block_on(self.client.events(0, 1))
            .map_err(|error| NativeError::Backend(format!("Agentd events: {error}")))?;
        let capabilities = self
            .runtime
            .block_on(self.client.capabilities())
            .map_err(|error| NativeError::Backend(format!("Agentd capabilities: {error}")))?;
        capabilities
            .validate()
            .map_err(|error| NativeError::Backend(format!("Agentd capabilities invalid: {error}")))?;

        let modules: Vec<String> = capabilities
            .capabilities
            .iter()
            .map(|capability| {
                format!(
                    "{}@{}.{}",
                    capability.id, capability.major, capability.minor
                )
            })
            .collect();

        let mut fields = BTreeMap::new();
        fields.insert("agent_id", self.agent_id.to_string());
        fields.insert("generation", self.spawn_generation.to_string());
        fields.insert("process_id", health.process_id.to_string());
        fields.insert("ready", health.ready.to_string());
        fields.insert("promotion_ready", health.promotion_ready.to_string());
        fields.insert("fenced", health.fenced.to_string());
        fields.insert("lifecycle", format!("{:?}", health.lifecycle));
        fields.insert("app_server_ready", lifecycle.app_server_ready.to_string());
        fields.insert("latest_event_cursor", events.latest_cursor.to_string());
        fields.insert("workspace", health.workspace.display().to_string());
        fields.insert("home_root", health.home_root.display().to_string());
        fields.insert("run_root", health.run_root.display().to_string());
        let canonical = serde_json::to_vec(&fields)
            .map_err(|error| NativeError::Backend(format!("encode Agentd view: {error}")))?;
        let summary = serde_json::to_string_pretty(&fields)
            .map_err(|error| NativeError::Backend(format!("encode Agentd summary: {error}")))?;

        Ok(BackendView {
            fence: session.fence.clone(),
            generation: self.spawn_generation,
            revision: events.latest_cursor.saturating_add(1),
            digest: Sha256Digest::for_bytes(&canonical),
            modules,
            summary,
        })
    }

    fn close(&mut self, _session: &BackendSession) -> Result<(), NativeError> {
        Ok(())
    }
}


#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::io::BufRead;
    use std::io::BufReader;
    use std::io::Write;
    use std::os::unix::net::UnixListener;

    use codex_hepta_agentd::AgentdCapabilitySet;
    use codex_hepta_agentd::AgentdMethod;
    use codex_hepta_agentd::AgentdPayload;
    use codex_hepta_agentd::AgentdRequest;
    use codex_hepta_agentd::AgentdResponse;
    use codex_hepta_agentd::EventBatch;
    use codex_hepta_agentd::HealthSnapshot;
    use codex_hepta_agentd::LifecycleSnapshot;
    use codex_hepta_agentd::SessionIngress;
    use codex_hepta_agentd::SessionTransport;
    use codex_hepta_fleet::AgentLifecycle;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

    #[test]
    fn real_agentd_wire_contract_composes_native_backend() -> Result<(), NativeError> {
        let temp = tempfile::tempdir()
            .map_err(|error| NativeError::Backend(format!("create temp dir: {error}")))?;
        let socket = temp.path().join("agentd.sock");
        let app_server = temp.path().join("app-server.sock");
        let workspace = temp.path().join("workspace");
        let home_root = temp.path().join("home");
        let run_root = temp.path().join("run");
        for directory in [&workspace, &home_root, &run_root] {
            std::fs::create_dir(directory)
                .map_err(|error| NativeError::Backend(format!("create test root: {error}")))?;
        }

        let listener = UnixListener::bind(&socket)
            .map_err(|error| NativeError::Backend(format!("bind Agentd fixture: {error}")))?;
        let agent_id =
            AgentId::parse(AGENT_ID).map_err(|error| NativeError::Backend(error.to_string()))?;
        let server_agent = agent_id.clone();
        let server_workspace = workspace.clone();
        let server_home = home_root.clone();
        let server_run = run_root.clone();
        let server_app = app_server.clone();
        let server = std::thread::spawn(move || -> Result<(), String> {
            for _ in 0..7 {
                let (stream, _) = listener.accept().map_err(|error| error.to_string())?;
                let mut reader = BufReader::new(stream);
                let mut bytes = Vec::new();
                reader
                    .read_until(b'\n', &mut bytes)
                    .map_err(|error| error.to_string())?;
                let request: AgentdRequest =
                    serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
                let payload = match request.method {
                    AgentdMethod::Health => AgentdPayload::Health(HealthSnapshot {
                        promotion_ready: true,
                        ready: true,
                        fenced: false,
                        lifecycle: AgentLifecycle::Running,
                        process_id: 4242,
                        workspace: server_workspace.clone(),
                        home_root: server_home.clone(),
                        run_root: server_run.clone(),
                    }),
                    AgentdMethod::Lifecycle => AgentdPayload::Lifecycle(LifecycleSnapshot {
                        lifecycle: AgentLifecycle::Running,
                        app_server_ready: true,
                        fenced: false,
                    }),
                    AgentdMethod::SessionIngress => AgentdPayload::SessionIngress(SessionIngress {
                        socket_path: server_app.clone(),
                        transport: SessionTransport::CodexAppServerWebsocketOverUds,
                    }),
                    AgentdMethod::Events { .. } => AgentdPayload::Events(EventBatch {
                        events: Vec::new(),
                        gap: false,
                        next_cursor: 6,
                        latest_cursor: 5,
                    }),
                    AgentdMethod::Capabilities => {
                        AgentdPayload::Capabilities(AgentdCapabilitySet::empty())
                    }
                    other => {
                        return Err(format!("unexpected native backend request: {other:?}"));
                    }
                };
                let response = AgentdResponse {
                    schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                    request_id: request.request_id,
                    agent_id: server_agent.clone(),
                    spawn_generation: 7,
                    current_generation: 7,
                    payload,
                };
                let mut response_bytes =
                    serde_json::to_vec(&response).map_err(|error| error.to_string())?;
                response_bytes.push(b'\n');
                reader
                    .into_inner()
                    .write_all(&response_bytes)
                    .map_err(|error| error.to_string())?;
            }
            Ok(())
        });

        let mut backend = AgentdBackend::new(socket.clone(), agent_id, 7)?;
        let manifest = backend.endpoint_manifest();
        let session = backend.connect(&manifest)?;
        assert_eq!(session.fence.generation, 7);
        let view = backend.read_view(&session)?;
        assert_eq!(view.revision, 6);
        assert_eq!(view.generation, 7);
        assert!(view.modules.is_empty());
        assert!(view.summary.contains("\"ready\": \"true\""));
        server
            .join()
            .map_err(|_| NativeError::Backend("Agentd fixture panicked".to_string()))?
            .map_err(NativeError::Backend)?;
        Ok(())
    }
}
