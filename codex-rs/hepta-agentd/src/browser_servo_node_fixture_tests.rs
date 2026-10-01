//! Actual Rust caller / Node owner interoperability. The driver is a fixture;
//! this test does not qualify Servo, Bubblewrap, or the production import closure.

use std::collections::BTreeSet;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

use super::BrowserFinalUseInvocation;
use super::BrowserServoCall;
use super::BrowserServoError;
use super::BrowserServoMethod;
use super::BrowserServoPort;
use super::BrowserServoProcessConfig;
use super::ChildBrowserTransport;
use super::hex_lower;
use super::sha256_bytes;

#[test]
#[ignore = "requires Node and a source workspace; explicit interoperability fixture"]
fn rust_port_and_node_owner_replay_after_revocation_without_another_dispatch() {
    let workspace = std::env::current_dir()
        .expect("working directory")
        .ancestors()
        .find(|path| path.join("apps/hepta-browser/src/runtime.js").is_file())
        .expect("run from the source workspace")
        .to_path_buf();
    let node = Command::new("node")
        .args(["-p", "process.execPath"])
        .output()
        .expect("Node is required for the explicit interoperability fixture");
    assert!(node.status.success());
    let node_path = PathBuf::from(String::from_utf8(node.stdout).expect("Node path").trim());
    let state = tempfile::tempdir().expect("fixture state");
    let trace = state.path().join("trace.json");
    let runtime = json!(workspace.join("apps/hepta-browser/src/runtime.js"));
    let service = json!(workspace.join("apps/hepta-browser/src/agentd-service.js"));
    let journal = json!(workspace.join("apps/hepta-browser/src/journal.js"));
    let trace_path = json!(trace);
    let digest_text = "1".repeat(64);
    let source = format!(
        r#"import {{ writeFileSync }} from "node:fs";
import {{ BrowserProfileHost }} from {runtime};
import {{ AgentdBrowserChannel, BrowserAgentdService, ParentFinalUseAuthority }} from {service};
import {{ MemoryBrowserOperationJournal }} from {journal};
const counts = {{ authority: 0, dispatch: 0 }};
const save = () => writeFileSync({trace_path}, JSON.stringify(counts));
const channel = new AgentdBrowserChannel({{ input: process.stdin, output: process.stdout }});
const authority = new ParentFinalUseAuthority(channel);
const enter = authority.withVerifiedUse.bind(authority);
authority.withVerifiedUse = async (...args) => {{ counts.authority += 1; save(); return enter(...args); }};
const host = new BrowserProfileHost({{
  authority, journal: new MemoryBrowserOperationJournal(),
  driver: {{
    async start() {{ return {{ started: true, processId: "servo.process.fixture" }}; }},
    async observe() {{ return {{ pageGeneration: 1, documentDigest: "{digest_text}", origin: "https://example.com" }}; }},
    async dispatch() {{ counts.dispatch += 1; save(); return {{ terminalObserved: true, status: "succeeded", outcomeDigest: "{digest_text}" }}; }},
    async reconcile() {{ return {{ terminalObserved: false }}; }},
    async stop() {{ return {{ stopped: true }}; }}
  }}
}});
save();
await new BrowserAgentdService({{ host, channel, authority }}).run();
"#
    );
    let service_path = state.path().join("fixture.mjs");
    let worker_path = state.path().join("fixture-worker");
    fs::write(&service_path, &source).expect("fixture source");
    fs::write(&worker_path, "unused driver fixture").expect("fixture worker");
    let config = BrowserServoProcessConfig {
        node_path,
        service_path,
        service_sha256: sha256_bytes(source.as_bytes()),
        worker_path,
        worker_sha256: sha256_bytes(b"unused driver fixture"),
        profile_root: state.path().join("profiles"),
        journal_path: state.path().join("journal.json"),
        bwrap_path: PathBuf::from("/bin/false"),
        driver_timeout_ms: 5_000,
    };
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let deadline = now + 30_000;
    // These fixed ASCII fixture values follow the owner request-semantics field
    // order. This digest is distinct from canonical protocol-frame serialization.
    let action = format!(
        r#"{{"kind":"navigate","url":"https://example.com/path","policyDigest":"{digest_text}","expectedRevision":7}}"#
    );
    let payload_digest = hex_lower(&sha256_bytes(action.as_bytes()));
    let request = format!(
        r#"{{"profileId":"profile.fixture","principalId":"principal.fixture","processId":"servo.process.fixture","profileGeneration":1,"pageGeneration":1,"documentDigest":"{digest_text}","operationId":"operation.fixture","action":"navigate","typedAction":{action},"destinationOrigin":"https://example.com","finalPayloadDigest":"{payload_digest}","profileGrantDigest":"{digest_text}","effectGrantDigest":"{digest_text}","authorityEpoch":7,"deadlineMs":{deadline}}}"#
    );
    let binding = FinalUseBinding {
        subject_id: "principal.fixture".to_string(),
        destination_id: "browser.profile.fixture".to_string(),
        request_sha256: sha256_bytes(request.as_bytes()),
        scope_sha256: [0x22; 32],
        payload_sha256: sha256_bytes(action.as_bytes()),
    };
    let signing = SigningKey::from_bytes(&[7; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &state.path().join("authority"),
        "browser-fixture-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "browser-fixture-issuer".to_string(),
        authority_epoch: 7,
        grant_id: "browser-fixture-grant.1".to_string(),
        nonce: [0x44; 32],
        binding: binding.clone(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let invocation = BrowserFinalUseInvocation {
        signed_grant: SignedFinalUseGrant { grant, signature },
        binding,
    };
    let port = BrowserServoPort::new(
        authority.clone(),
        ChildBrowserTransport::spawn(&config).expect("snapshot and spawn Node fixture"),
    );
    port.call(
        BrowserServoCall::read(
            BrowserServoMethod::OpenProfile,
            json!({"profileId":"profile.fixture","principalId":"principal.fixture",
                "generation":1,"manifestDigest":digest_text,"grantDigest":digest_text,
                "expiresAtMs":now+60_000,"allowedOrigins":["https://example.com"],
                "effectGrants":[{"grantDigest":digest_text,"action":"navigate",
                    "destinationOrigin":"https://example.com","finalPayloadDigest":payload_digest,
                    "authorityEpoch":7,"expiresAtMs":now+60_000}]}),
        )
        .expect("open call"),
    )
    .expect("open actual Node owner");
    port.call(
        BrowserServoCall::read(
            BrowserServoMethod::ObservePage,
            json!({"profileId":"profile.fixture","principalId":"principal.fixture",
                "generation":1,"observationBudget":128}),
        )
        .expect("observe call"),
    )
    .expect("observe fixture page");
    let mut input = json!({"profileId":"profile.fixture","principalId":"principal.fixture",
        "generation":1.0,"operationId":"operation.fixture","pageGeneration":1,
        "typedAction":serde_json::from_str::<Value>(&action).expect("action"),
        "destinationOrigin":"https://example.com","finalPayloadDigest":payload_digest,
        "effectGrantDigest":digest_text,"authorityEpoch":7,"deadlineMs":deadline});
    let first = port
        .call(BrowserServoCall::effect(input.clone(), invocation.clone()).expect("first call"))
        .expect("first dispatch");
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 7,
            revision: 2,
            revoked_grant_ids: BTreeSet::from(["browser-fixture-grant.1".to_string()]),
        })
        .expect("revoke original grant");
    let replay = port
        .call(BrowserServoCall::effect(input.clone(), invocation.clone()).expect("replay call"))
        .expect("historical observation after revocation");
    assert_eq!(first, replay);
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(&trace).expect("trace")).expect("trace JSON"),
        json!({"authority":1,"dispatch":1}),
    );
    input["deadlineMs"] = json!(deadline - 1);
    assert!(matches!(
        port.call(BrowserServoCall::effect(input, invocation).expect("changed call")),
        Err(BrowserServoError::Rejected(_))
    ));
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(trace).expect("trace")).expect("trace JSON"),
        json!({"authority":1,"dispatch":1}),
    );
}
