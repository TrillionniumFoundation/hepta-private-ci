//! Actual AF_UNIX, signed host config, SQLite/FinalUse and sealed ELF ingress.
//! The tiny C provider records bytes/contact and supplies controlled observations;
//! it is not Chain, Supervisor installation or neural improvement evidence.
use super::*;
use tokio::io::AsyncBufReadExt;

const CHILD: &str = r#"
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    const char *root = NULL;
    for (int i = 2; i + 1 < argc; ++i)
        if (strcmp(argv[i], "--store") == 0) root = argv[i + 1];
    if (root == NULL) return 2;
    char path[4096], buffer[4096];
    int n = snprintf(path, sizeof path, "%s/last-payload", root);
    if (n <= 0 || (size_t)n >= sizeof path) return 3;
    FILE *file = fopen(path, "wb"); if (file == NULL) return 4;
    size_t count;
    while ((count = fread(buffer, 1, sizeof buffer, stdin)) > 0)
        if (fwrite(buffer, 1, count, file) != count) return 5;
    if (ferror(stdin) || fclose(file) != 0) return 6;
    int submit = strcmp(argv[1], "submit") == 0;
    n = snprintf(path, sizeof path, "%s/%s", root, submit ? "dispatches" : "lookups");
    if (n <= 0 || (size_t)n >= sizeof path) return 3;
    file = fopen(path, "ab"); if (file == NULL) return 4;
    if (fputc('x', file) == EOF || fclose(file) != 0) return 6;
    if (submit) return 7;
    n = snprintf(path, sizeof path, "%s/observation.json", root);
    if (n <= 0 || (size_t)n >= sizeof path) return 3;
    file = fopen(path, "rb"); if (file == NULL) return 7;
    while ((count = fread(buffer, 1, sizeof buffer, file)) > 0)
        if (fwrite(buffer, 1, count, stdout) != count) return 5;
    return ferror(file) || fclose(file) != 0;
}
"#;

struct PacketFixture {
    effect: EffectFixture,
    _directory: tempfile::TempDir,
    packet: crate::AutomationPonPacketFile,
    bytes: Vec<u8>,
    config: Value,
}

impl PacketFixture {
    async fn new() -> anyhow::Result<Self> {
        let mut effect = EffectFixture::new().await?;
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let source = root.join("provider.c");
        let binary = root.join("provider");
        fs::write(&source, CHILD)?;
        let output = Command::new("cc").args(["-std=c11", "-O0", "-Wall", "-Wextra", "-Werror"])
            .arg(&source).arg("-o").arg(&binary).output()?;
        anyhow::ensure!(output.status.success(), "compile fixture: {}", String::from_utf8_lossy(&output.stderr));
        fs::set_permissions(&binary, fs::Permissions::from_mode(0o700))?;
        fs::write(root.join("native.sqlite"), b"provider-fixture-not-chain")?;
        let bytes = vec![0xa5; 49_733];
        effect.intent.payload_digest = Sha256Digest::for_bytes(&bytes);
        effect.grant = signed_final_use(&effect.intent, effect.now_ms, &SigningKey::from_bytes(&[29; 32]))?;
        let packet = crate::AutomationPonPacketFile {
            path: root.join("accept.packet"), byte_length: bytes.len() as u64,
            payload_sha256: effect.intent.payload_digest.clone(),
        };
        fs::write(&packet.path, &bytes)?;
        let original: Value = serde_json::from_slice(&fs::read(&effect.host_file)?)?;
        let config = serde_json::json!({
            "schema_version":3,"provider_kind":"trillionnium-pon-local-v1",
            "provider_scope":"provider/fixture-v1","destination_id":effect.intent.destination_id,
            "final_use_scope_sha256":effect.intent.final_use_scope_digest,
            "chain_binary":binary,"chain_binary_sha256":Sha256Digest::for_bytes(&fs::read(&binary)?),
            "chain_store":root,"pon_packet_root":root,"chain_state_backend":"authenticated-v1",
            "chain_genesis_time":1,"chain_evaluation_policy":"fixture","chain_task_profile":"fixture",
            "chain_model_profile":"fixture","chain_workers":1,"chain_min_confirmation_depth":1,
            "chain_min_confirmation_work_depth_hex":format!("{}01", "00".repeat(63)),"timeout_ms":5000,
            "contract_id":"packet-file-fixture","contract_sha256":"00".repeat(32),"contract_authority_epoch":1,
            "contract_signature_hex":"00".repeat(64),"contract_verifying_key_hex":original["contract_verifying_key_hex"],
            "final_use_signer_id":original["final_use_signer_id"],"final_use_verifying_key_hex":original["final_use_verifying_key_hex"],
            "final_use_revocations_file":original["final_use_revocations_file"],
        });
        let fixture = Self { effect, _directory: directory, packet, bytes, config };
        fixture.write_config(fixture.config.clone())?;
        Ok(fixture)
    }

    fn write_config(&self, mut config: Value) -> anyhow::Result<()> {
        let parsed: AutomationEffectHostFileV3 = serde_json::from_value(config.clone())?;
        let digest = pon_contract_digest(&parsed)?;
        config["contract_sha256"] = serde_json::json!(digest);
        config["contract_signature_hex"] = serde_json::json!(hex(&SigningKey::from_bytes(&[23; 32])
            .sign(&HttpProviderEffectContractAttestation::statement_for("packet-file-fixture", &digest, 1)).to_bytes()));
        fs::write(&self.effect.host_file, serde_json::to_vec(&config)?)?;
        Ok(())
    }

    async fn resume(&self, owner: &RunningOwner, packet: crate::AutomationPonPacketFile) -> Result<crate::AutomationEffectReconcileSnapshot, AgentdError> {
        owner.client.automation_resume_pon_packet(self.effect.intent.clone(), packet,
            self.effect.grant.clone(), "dispatch".to_owned()).await
    }

    async fn no_dispatch(&self, owner: &RunningOwner) -> anyhow::Result<()> {
        assert_eq!(owner.host.authority.capacity()?.used_nonces, 0);
        assert!(self.effect.base.store.taskflow_run(&self.effect.intent.run_id).await?.is_none());
        assert!(self.effect.base.store.authorized_taskflow_effect_attempt(&self.effect.intent.run_id, "effect", 1).await?.is_none());
        assert!(!self.packet.path.parent().context("root")?.join("last-payload").try_exists()?);
        Ok(())
    }
}

async fn rejected_raw(owner: &RunningOwner, request: crate::AgentdRequest) -> anyhow::Result<()> {
    let mut stream = codex_uds::UnixStream::connect(&owner.state.identity().control_socket).await?;
    let mut bytes = serde_json::to_vec(&request)?; bytes.push(b'\n');
    anyhow::ensure!(bytes.len() as u64 <= crate::MAX_CONTROL_FRAME_BYTES, "negative request must reach the original method decoder");
    stream.write_all(&bytes).await?;
    let mut response = String::new();
    tokio::time::timeout(Duration::from_secs(2), tokio::io::BufReader::new(stream).read_line(&mut response)).await??;
    let response: crate::AgentdResponse = serde_json::from_str(&response)?;
    assert!(matches!(response.payload, crate::AgentdPayload::Error { .. }));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn pon_packet_file_refuses_unowned_or_changed_material_before_effect() -> anyhow::Result<()> {
    let fixture = PacketFixture::new().await?;
    fixture.effect.fleet()?.compare_and_transition(&fixture.effect.base.identity.agent_id, 0, AgentLifecycle::Starting)?;
    let owner = fixture.effect.start(1).await?;
    assert!(owner.client.automation_resume_effect(fixture.effect.intent.clone(), &fixture.bytes,
        fixture.effect.grant.clone(), "dispatch".to_owned()).await.is_err());
    rejected_raw(&owner, crate::AgentdRequest::automation_resume_effect(701, 1, fixture.effect.intent.clone(),
        hex(&vec![0xa5; crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES + 1]), fixture.effect.grant.clone(), "dispatch".to_owned())).await?;
    for byte_length in [0, codex_hepta_automation::MAX_EFFECT_DISPATCH_WIRE_BYTES as u64 + 1] {
        let mut wrong = fixture.packet.clone(); wrong.byte_length = byte_length;
        assert!(fixture.resume(&owner, wrong).await.is_err());
    }
    let mut wrong = fixture.packet.clone();
    wrong.byte_length -= 1;
    assert!(fixture.resume(&owner, wrong).await.is_err());
    let mut wrong = fixture.packet.clone();
    wrong.payload_sha256 = Sha256Digest::for_bytes(b"wrong");
    assert!(fixture.resume(&owner, wrong).await.is_err());
    let mut wrong = fixture.packet.clone();
    wrong.path = fixture.effect.base.identity.workspace.join("outside.packet");
    fs::write(&wrong.path, &fixture.bytes)?;
    assert!(fixture.resume(&owner, wrong).await.is_err());
    let alias = fixture.packet.path.with_extension("alias");
    std::os::unix::fs::symlink(&fixture.packet.path, &alias)?;
    let mut wrong = fixture.packet.clone(); wrong.path = alias.clone();
    assert!(fixture.resume(&owner, wrong).await.is_err());
    fs::remove_file(&alias)?;
    fs::hard_link(&fixture.packet.path, &alias)?;
    assert!(fixture.resume(&owner, fixture.packet.clone()).await.is_err());
    fs::remove_file(alias)?;
    fs::write(&fixture.packet.path, vec![0xa5; codex_hepta_automation::MAX_EFFECT_DISPATCH_WIRE_BYTES + 1])?;
    assert!(fixture.resume(&owner, fixture.packet.clone()).await.is_err());
    fs::write(&fixture.packet.path, vec![0xa4; fixture.bytes.len()])?;
    assert!(fixture.resume(&owner, fixture.packet.clone()).await.is_err());
    let root = fixture.packet.path.parent().context("root")?;
    let displaced = root.with_extension("displaced");
    fs::rename(root, &displaced)?;
    fs::create_dir(root)?;
    fs::write(&fixture.packet.path, &fixture.bytes)?;
    assert!(fixture.resume(&owner, fixture.packet.clone()).await.is_err());
    fs::remove_file(&fixture.packet.path)?;
    fs::remove_dir(root)?;
    fs::rename(displaced, root)?;
    fixture.no_dispatch(&owner).await?;
    fs::write(&fixture.packet.path, &fixture.bytes)?;
    assert_eq!(fixture.resume(&owner, fixture.packet.clone()).await?.state, crate::AutomationEffectReconcileState::Indeterminate);
    assert_eq!(fs::read(fixture.packet.path.parent().context("root")?.join("last-payload"))?, fixture.bytes);
    assert_eq!(owner.host.authority.capacity()?.used_nonces, 1);
    owner.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn pon_packet_file_unknown_reopens_without_file_or_second_dispatch() -> anyhow::Result<()> {
    let fixture = PacketFixture::new().await?;
    fixture.effect.fleet()?.compare_and_transition(&fixture.effect.base.identity.agent_id, 0, AgentLifecycle::Starting)?;
    let owner = fixture.effect.start(1).await?;
    let pending = fixture.resume(&owner, fixture.packet.clone()).await?;
    assert_eq!(pending.state, crate::AutomationEffectReconcileState::Indeterminate);
    let before = fixture.effect.base.store.authorized_taskflow_effect_attempt(&fixture.effect.intent.run_id, "effect", 1).await?.context("durable input")?;
    assert_eq!(before.wire_payload.as_deref(), Some(fixture.bytes.as_slice()));
    owner.stop().await?;
    fs::remove_file(&fixture.packet.path)?;
    for (generation, lifecycle) in [(2, AgentLifecycle::Draining), (3, AgentLifecycle::Stopped), (4, AgentLifecycle::Starting)] {
        fixture.effect.fleet()?.compare_and_transition(&fixture.effect.base.identity.agent_id, generation, lifecycle)?;
    }
    let owner = fixture.effect.start(5).await?;
    assert_eq!(fixture.resume(&owner, fixture.packet.clone()).await?, pending);
    let root = fixture.packet.path.parent().context("root")?;
    let lookups = fs::read(root.join("lookups"))?;
    assert!(owner.client.automation_resume_pon_packet(fixture.effect.intent.clone(), fixture.packet.clone(),
        fixture.effect.grant.clone(), "wrong-command".to_owned()).await.is_err());
    let mut wrong = fixture.packet.clone(); wrong.byte_length -= 1;
    assert!(fixture.resume(&owner, wrong).await.is_err());
    assert_eq!(fs::read(root.join("lookups"))?, lookups);
    fs::write(root.join("observation.json"), serde_json::to_vec(&super::super::pon_lifecycle_tests::observation())?)?;
    let terminal = fixture.resume(&owner, fixture.packet.clone()).await?;
    assert_eq!(terminal.state, crate::AutomationEffectReconcileState::Terminal);
    assert_eq!(terminal.effect.as_ref().context("receipt")?.observation, crate::AutomationEffectObservation::Succeeded);
    assert_eq!(fixture.resume(&owner, fixture.packet.clone()).await?, terminal);
    assert_eq!(owner.client.automation_observe_effect(fixture.effect.intent.clone(), "dispatch".to_owned()).await?, terminal);
    assert_eq!(fs::read(root.join("last-payload"))?, fixture.bytes);
    assert_eq!(fs::read(root.join("dispatches"))?, b"x");
    assert_eq!(owner.host.authority.capacity()?.used_nonces, 1);
    assert_eq!(fixture.effect.base.store.authorized_taskflow_effect_attempt(&fixture.effect.intent.run_id, "effect", 1).await?, Some(before));
    owner.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn pon_packet_file_root_is_opt_in_signed_and_separate_from_agent_namespaces() -> anyhow::Result<()> {
    let fixture = PacketFixture::new().await?;
    let identity = &fixture.effect.base.identity;
    for root in [identity.home_root.as_path(), identity.run_root.as_path(), identity.workspace.as_path(), identity.workspace.parent().context("workspace parent")?] {
        let mut config = fixture.config.clone(); config["pon_packet_root"] = serde_json::json!(root);
        fixture.write_config(config)?;
        assert!(AgentdAutomationEffectHost::open(identity, &fixture.effect.host_file).is_err());
    }
    fixture.write_config(fixture.config.clone())?;
    let mut changed: Value = serde_json::from_slice(&fs::read(&fixture.effect.host_file)?)?;
    changed["pon_packet_root"] = Value::Null;
    fs::write(&fixture.effect.host_file, serde_json::to_vec(&changed)?)?;
    assert!(AgentdAutomationEffectHost::open(identity, &fixture.effect.host_file).is_err());
    let mut legacy = fixture.config.clone(); legacy.as_object_mut().context("host")?.remove("pon_packet_root");
    fixture.write_config(legacy)?;
    fixture.effect.fleet()?.compare_and_transition(&identity.agent_id, 0, AgentLifecycle::Starting)?;
    let owner = fixture.effect.start(1).await?;
    assert!(!owner.client.capabilities().await?.capabilities.iter().any(|cap| cap.id == crate::AUTOMATION_PON_PACKET_FILE_CAPABILITY));
    assert!(fixture.resume(&owner, fixture.packet.clone()).await.is_err());
    rejected_raw(&owner, crate::AgentdRequest::automation_resume_pon_packet(702, 1, fixture.effect.intent.clone(),
        fixture.packet.clone(), fixture.effect.grant.clone(), "dispatch".to_owned())).await?;
    fixture.no_dispatch(&owner).await?;
    owner.stop().await?;
    Ok(())
}
