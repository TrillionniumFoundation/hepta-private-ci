//! Owner for isolated, read-only qualification sessions, not a production writer.
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_native_agent::ModelRequest;
use codex_hepta_native_agent::ToolAdmission;
use codex_hepta_native_agent::ToolCall;
use codex_hepta_native_agent::TurnBinding;
use codex_hepta_native_agent::TurnOwner;
use codex_hepta_native_agent::TurnState;
use codex_hepta_types::*;
use hepta_runtime::mcp::runtime::jobs::ProcessStartParams;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::path::PathBuf;

use crate::persist::Store;
use crate::persist::read_regular;
use crate::runtime_bridge::AdmissionResolver;
use crate::runtime_bridge::AdmittedTool;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FixtureConfig {
    pub host: String,
    pub script: String,
    pub script_sha256: String,
    pub data: String,
    pub data_sha256: String,
    pub cwd: String,
    pub tool_timeout_seconds: u64,
}

pub struct SessionOwner {
    pub store: Store,
    pub binding: TurnBinding,
    fixture: FixtureConfig,
    manifest: Vec<u8>,
}

impl SessionOwner {
    pub fn open(
        root: PathBuf,
        session: &str,
        input: &str,
        fixture: FixtureConfig,
        policy: Value,
    ) -> Result<(Self, TurnState)> {
        let digest = Digest32::of_bytes(session.as_bytes()).to_string();
        let binding = TurnBinding {
            thread_id: StableId::new(format!("qualification:thread:{digest}"))?,
            turn_id: StableId::new(format!("qualification:turn:{digest}"))?,
            operation_id: StableId::new(format!("qualification:operation:{digest}"))?,
            generation: Generation::new(1)?,
        };
        let manifest = json!({"schema":"native.qualification.session.v1","session":session,
            "input":input,"fixture":fixture,"policy":policy,"binding":crate::snapshot::binding_json(&binding)});
        let (store, latest) = Store::open(root, &manifest)?;
        let owner = Self {
            store,
            binding: binding.clone(),
            fixture,
            manifest: serde_json::to_vec(&manifest)?,
        };
        let state = match latest {
            Some(value) => crate::snapshot::restore(&owner, value)?,
            None => TurnState::new(binding, input.to_owned()),
        };
        Ok((owner, state))
    }

    pub fn check(&self, binding: &TurnBinding) -> Result<()> {
        if binding != &self.binding
            || read_regular(&self.store.root.join("manifest.json"))? != self.manifest
        {
            bail!("stale or altered qualification session binding");
        }
        Ok(())
    }

    fn admission_name(&self, call_id: &str) -> String {
        format!("tool-{}.json", Digest32::of_bytes(call_id.as_bytes()))
    }

    pub fn load_call(&self, call: &ToolCall) -> Result<AdmittedTool> {
        self.check(&self.binding)?;
        let record: Value = serde_json::from_slice(&read_regular(
            &self.store.root.join(self.admission_name(&call.call_id)),
        )?)?;
        if record["call"] != crate::snapshot::call_json(call) {
            bail!("model proposal changed after admission");
        }
        let params: ProcessStartParams = serde_json::from_value(record["params"].clone())?;
        let arguments = serde_json::to_vec(&params)?;
        let intent = self.intent(
            call,
            &params,
            &arguments,
            record["deadline_ms"].as_u64().context("deadline missing")?,
        )?;
        if record["intent_digest"] != intent.intent_digest().to_string() {
            bail!("admitted tool binding changed");
        }
        Ok(AdmittedTool {
            intent,
            arguments,
            params,
        })
    }

    fn intent(
        &self,
        call: &ToolCall,
        params: &ProcessStartParams,
        arguments: &[u8],
        deadline: u64,
    ) -> Result<RuntimeToolIntentV1> {
        let digest = Digest32::of_parts(&[
            self.binding.operation_id.as_str().as_bytes(),
            b"\0",
            call.call_id.as_bytes(),
        ]);
        let operation = StableId::new(format!("qualification:tool:{digest}"))?;
        let organ = StableId::new("qualification:organ")?;
        let arguments_digest = Digest32::of_bytes(arguments);
        let intent = RuntimeToolIntentV1 {
            cell: CellExecutionIntentV1 {
                operation_id: operation.clone(),
                cell_id: StableId::new("qualification:cell")?,
                organ_id: organ.clone(),
                generation: self.binding.generation,
                kind: ExecutionIntentKindV1::RuntimeTool,
                codex_binding: None,
                input_digest: Digest32::of_bytes(&call.arguments),
                final_payload: FinalPayloadDigestV1 {
                    scope_id: organ,
                    generation: self.binding.generation,
                    payload_kind: StableId::new("hepta.process.start.json.v1")?,
                    digest: arguments_digest,
                },
                deadline_ms: deadline,
            },
            tool_id: StableId::new("process_start")?,
            arguments_digest,
            idempotency_key: StableId::new(
                params
                    .idempotency_key
                    .as_deref()
                    .context("original key missing")?,
            )?,
            host_scope: StableId::new(&params.host)?,
        };
        if intent.idempotency_key != operation || params.host != self.fixture.host {
            bail!("compiled owner identity changed");
        }
        intent.validate()?;
        Ok(intent)
    }
}

impl TurnOwner for SessionOwner {
    async fn verify_current(&self, binding: &TurnBinding) -> Result<()> {
        self.check(binding)
    }

    async fn checkpoint(&self, state: &TurnState) -> Result<()> {
        self.check(&state.binding)?;
        self.store.checkpoint(crate::snapshot::encode(state)?)
    }

    async fn admit_model(
        &self,
        binding: &TurnBinding,
        sequence: usize,
        exact_body: &[u8],
    ) -> Result<ModelRequest> {
        self.check(binding)?;
        let operation_id = format!("{}:model:{sequence}", binding.operation_id);
        let record =
            json!({"operation_id":operation_id,"body":String::from_utf8(exact_body.to_vec())?});
        self.store.immutable(
            &format!("model-{sequence:08}.json"),
            &serde_json::to_vec(&record)?,
        )?;
        Ok(ModelRequest {
            operation_id,
            body: exact_body.to_vec(),
        })
    }

    async fn admit_tool(&self, binding: &TurnBinding, call: &ToolCall) -> Result<ToolAdmission> {
        self.check(binding)?;
        let path = self.store.root.join(self.admission_name(&call.call_id));
        if path.try_exists()? {
            let admitted = self.load_call(call)?;
            return Ok(ToolAdmission {
                intent: admitted.intent,
                arguments: admitted.arguments,
            });
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Args {
            task: String,
        }
        let args: Args = serde_json::from_slice(&call.arguments)?;
        if call.name != "hepta_probe" || !["sum", "lines", "digest"].contains(&args.task.as_str()) {
            bail!("qualification tool proposal outside the frozen three-operation fixture");
        }
        for (path, expected) in [
            (&self.fixture.script, &self.fixture.script_sha256),
            (&self.fixture.data, &self.fixture.data_sha256),
        ] {
            if Digest32::of_reader(std::fs::File::open(path)?, 1024 * 1024)?.to_string()
                != *expected
            {
                bail!("qualification fixture artifact changed");
            }
        }
        let digest = Digest32::of_parts(&[
            binding.operation_id.as_str().as_bytes(),
            b"\0",
            call.call_id.as_bytes(),
        ]);
        let key = format!("qualification:tool:{digest}");
        let params: ProcessStartParams = serde_json::from_value(json!({
            "host":self.fixture.host,"executable":"/usr/bin/python3",
            "args":["-I","-S",self.fixture.script,args.task,self.fixture.data],"cwd":self.fixture.cwd,
            "idempotency_key":key,"timeout_seconds":self.fixture.tool_timeout_seconds,
            "cpu_quota_percent":100,"memory_max_bytes":268435456,"nice":10
        }))?;
        let arguments = serde_json::to_vec(&params)?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis() as u64;
        let deadline = now.checked_add(300_000).context("deadline overflow")?;
        let intent = self.intent(call, &params, &arguments, deadline)?;
        let record = json!({"call":crate::snapshot::call_json(call),"params":params,"deadline_ms":deadline,
            "intent_digest":intent.intent_digest().to_string()});
        self.store.immutable(
            &self.admission_name(&call.call_id),
            &serde_json::to_vec(&record)?,
        )?;
        Ok(ToolAdmission { intent, arguments })
    }
}

impl AdmissionResolver for SessionOwner {
    fn resolve(&self, intent: &RuntimeToolIntentV1) -> Result<AdmittedTool> {
        self.check(&self.binding)?;
        for entry in std::fs::read_dir(&self.store.root)? {
            let entry = entry?;
            if !entry.file_name().to_string_lossy().starts_with("tool-") {
                continue;
            }
            let value: Value = serde_json::from_slice(&read_regular(&entry.path())?)?;
            if value["intent_digest"] == intent.intent_digest().to_string() {
                let call = crate::snapshot::parse_call(&value["call"])?;
                let admitted = self.load_call(&call)?;
                if admitted.intent != *intent {
                    bail!("runtime intent changed");
                }
                return Ok(admitted);
            }
        }
        bail!("original tool admission is unavailable")
    }
}
