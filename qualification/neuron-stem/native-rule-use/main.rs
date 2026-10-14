//! Bounded JSON-lines research bridge; never installed in the native runtime.
#![forbid(unsafe_code)]
mod fixture;
mod revision;
#[path = "../../../codex-rs/hepta-agentd/src/rule_artifact.rs"]
mod rule_artifact;

use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use rule_artifact::RuleArtifactConsumerV1;
use rule_artifact::RuleUseBindingV1;
use serde_json::json;
use serde_json::Value;
use std::fs;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::io::{self};
use std::path::PathBuf;
use std::str::FromStr;
use std::time::Duration;
use std::time::Instant;

const MAX_LINE: u64 = 64 * 1024;
const Q: i64 = 1 << 24;
const OPS: [[i64; 3]; 6] = [
    [0, 1, 2],
    [0, 2, 1],
    [1, 0, 2],
    [1, 2, 0],
    [2, 0, 1],
    [2, 1, 0],
];

struct Session {
    owner: codex_hepta_learning_artifacts::LearningArtifactOwnerService,
    consumer: RuleArtifactConsumerV1,
    authority: codex_hepta_contracts::FinalUseAuthority,
    control: DurableInferenceControl,
    payload: Vec<u8>,
    descriptor: Value,
    lifetime: u64,
    expires: u64,
    driver_log: PathBuf,
    native_trust: codex_hepta_learning_artifacts::ArtifactOwnerTrustV1,
    manifest: codex_hepta_learning_artifacts::LearningArtifactManifestV2,
    artifact_id: codex_hepta_types::StableId,
    head_generation: u64,
    reload: fixture::ReloadSpec,
}

fn number(value: &Value, key: &str) -> Result<u64, String> {
    value[key]
        .as_u64()
        .ok_or_else(|| format!("missing integer {key}"))
}
fn pin(value: &Value, key: &str) -> Result<Digest32, String> {
    Digest32::from_str(
        value[key]
            .as_str()
            .ok_or_else(|| format!("missing digest {key}"))?,
    )
    .map_err(|e| e.to_string())
}
fn triple(value: &Value) -> Result<Vec<i64>, String> {
    let values = value.as_array().ok_or("missing triple")?;
    if values.len() != 3 {
        return Err("triple width".into());
    }
    values
        .iter()
        .map(|x| x.as_i64().ok_or_else(|| "integer triple".into()))
        .collect()
}
fn decode_hex(value: &str) -> Result<Vec<u8>, String> {
    if value.len() > 32 * 1024 || !value.len().is_multiple_of(2) {
        return Err("payload bound".into());
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let text = std::str::from_utf8(pair).map_err(|e| e.to_string())?;
            u8::from_str_radix(text, 16).map_err(|e| e.to_string())
        })
        .collect()
}

fn open(root: &std::path::Path, command: &Value) -> Result<Session, String> {
    let payload = decode_hex(
        command["payload_hex"]
            .as_str()
            .ok_or("payload_hex required")?,
    )?;
    let descriptor = json!({"checkpoint_digest":pin(command,"checkpoint_digest")?.to_string(), "rule_revision":number(command,"rule_revision")?, "authority_epoch":number(command,"authority_epoch")?, "generation":number(command,"generation")?, "scope_digest":pin(command,"scope_digest")?.to_string()});
    if Digest32::of_bytes(&payload) != pin(command, "checkpoint_digest")?
        || number(command, "authority_epoch")? != 1
    {
        return Err("descriptor content/epoch mismatch".into());
    }
    let bundle: Value = serde_json::from_slice(&payload).map_err(|e| e.to_string())?;
    if bundle["schema"] != "hepta.rule-artifact.research.v1"
        || bundle["revision"] != descriptor["rule_revision"]
        || bundle["generation"] != descriptor["generation"]
    {
        return Err("bundle descriptor mismatch".into());
    }
    validate_effects(&bundle)?;
    let generation = Generation::new(number(command, "generation")?).map_err(|e| e.to_string())?;
    let lifetime = command["selection_lifetime_s"]
        .as_u64()
        .or_else(|| command["selection_lifetime_secs"].as_u64())
        .unwrap_or(3600)
        .clamp(1, 3600);
    let built = fixture::open(root, &payload, generation, lifetime)?;
    let artifact_id = built.selected.artifact_id().clone();
    let consumer = RuleArtifactConsumerV1::new(
        fixture::id("research.principal")?,
        fixture::id("research.worker")?,
        built.selected,
    );
    let control = DurableInferenceControl::open(root.join("inference.journal"), 4096)
        .map_err(|e| e.to_string())?;
    Ok(Session {
        owner: built.owner,
        consumer,
        authority: built.authority,
        control,
        payload,
        descriptor,
        lifetime,
        expires: built.selection_expires_at,
        driver_log: root.join("inference-driver.jsonl"),
        native_trust: built.native_trust,
        manifest: built.manifest,
        artifact_id,
        head_generation: 1,
        reload: built.reload,
    })
}

fn validate_effects(bundle: &Value) -> Result<Vec<usize>, String> {
    let values = bundle["table"]["effects"]
        .as_array()
        .ok_or("effects absent")?;
    if values.len() != 6 {
        return Err("effects width".into());
    }
    values
        .iter()
        .map(|v| {
            let x = v.as_u64().ok_or("integer effect")?;
            if x > 5 {
                Err("effect range".into())
            } else {
                Ok(x as usize)
            }
        })
        .collect()
}

fn driver(
    trace: &std::path::Path,
    manifest_digest: Digest32,
    payload: &[u8],
    request: &NeuronFeatureRequestV1,
    delay_ms: u64,
    fail: bool,
    panic_after_entry: bool,
) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, String> {
    let started = Instant::now();
    let mut log = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(trace)
        .map_err(|e| e.to_string())?;
    writeln!(log,"{}",json!({"event":"entry","request_id":request.request_id.as_str(),"input_digest":request.input_digest.to_string(),"selected_payload_digest":Digest32::of_bytes(payload).to_string(),"observed_unix_ms":fixture::now_ms()?})).map_err(|e|e.to_string())?;
    log.sync_all().map_err(|e| e.to_string())?;
    let bundle: Value = serde_json::from_slice(payload).map_err(|e| e.to_string())?;
    let effects = validate_effects(&bundle)?;
    let normalized: Vec<i64> = request.feature_vector_q24.iter().map(|x| x / Q).collect();
    let index = OPS
        .iter()
        .position(|op| op.as_slice() == normalized)
        .ok_or("input permutation")?;
    let result: Vec<i64> = OPS[effects[index]]
        .iter()
        .map(|coordinate| normalized[*coordinate as usize] * Q)
        .collect();
    let known_vector_bytes = (effects.capacity() * std::mem::size_of::<usize>()
        + normalized.capacity() * std::mem::size_of::<i64>()
        + 2 * result.capacity() * std::mem::size_of::<i64>()) as u64;
    assert!(
        !panic_after_entry,
        "injected research callback panic after actual table execution"
    );
    if delay_ms > 0 {
        std::thread::sleep(Duration::from_millis(delay_ms));
    }
    if fail {
        return Err("injected research callback failure after actual table execution".into());
    }
    build_neuron_feature_receipt_v1(
        request,
        NeuronModelRuntimeTupleV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: manifest_digest,
            weights_digest: request.weights_digest,
            tokenizer_digest: fixture::digest("research.no-tokenizer"),
            preprocessor_digest: fixture::digest("research.role.normalize"),
            quantization_digest: fixture::digest("research.q24"),
            runtime_digest: fixture::digest("research.finite.driver"),
            device_digest: fixture::digest("research.cpu"),
        },
        NeuronFeatureObservationV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            drive_q24: result.clone(),
            prediction_q24: result,
            observed_memory_bytes: payload.len() as u64,
            transient_allocation_bytes: known_vector_bytes,
            queue_age_micros: 0,
            latency_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
            status: NeuronFeatureTerminalStatusV1::Succeeded,
        },
    )
    .map_err(|e| e.to_string())
}

fn execute(session: &mut Session, command: &Value) -> Result<Value, String> {
    for key in [
        "checkpoint_digest",
        "rule_revision",
        "authority_epoch",
        "generation",
        "scope_digest",
    ] {
        if !command[key].is_null() && command[key] != session.descriptor[key] {
            return Err(format!("descriptor changed: {key}"));
        }
    }
    let sequence = number(command, "sequence")?;
    let input = triple(&command["input_state"])?;
    if !OPS.iter().any(|op| op.as_slice() == input) {
        return Err("input role permutation".into());
    }
    let expected = triple(&command["expected_prediction_q24"])?;
    let timeout = command["timeout_ms"]
        .as_u64()
        .unwrap_or(5000)
        .clamp(1, 30_000);
    let now = fixture::now_ms()?;
    let binding = RuleUseBindingV1 {
        checkpoint_digest: pin(&session.descriptor, "checkpoint_digest")?,
        rule_revision: number(&session.descriptor, "rule_revision")?,
        authority_epoch: 1,
        generation: Generation::new(number(&session.descriptor, "generation")?)
            .map_err(|e| e.to_string())?,
        scope_digest: pin(&session.descriptor, "scope_digest")?,
        inference: NeuronFeatureRequestV1 {
            request_id: fixture::id(&format!("research.request.{sequence}"))?,
            generation: Generation::new(number(&session.descriptor, "generation")?)
                .map_err(|e| e.to_string())?,
            model_id: session.artifact_id.clone(),
            encoder_digest: fixture::digest("research.role.encoder"),
            head_digest: fixture::digest("research.rule.head"),
            weights_digest: pin(&session.descriptor, "checkpoint_digest")?,
            input_digest: Digest32::of_bytes(
                &serde_json::to_vec(command).map_err(|e| e.to_string())?,
            ),
            feature_vector_q24: input.iter().map(|x| x * Q).collect(),
            expected_output_width: 3,
        },
        expected_prediction_q24: expected,
        deadline_unix_ms: now + timeout,
    };
    let proposal = session
        .consumer
        .final_use_binding(&binding)
        .map_err(|e| e.to_string())?;
    let grant = fixture::signed_grant(proposal.clone(), sequence, now + timeout)?;
    let token = session
        .authority
        .claim(&grant, &proposal)
        .map_err(|e| e.to_string())?;
    if command["revoke_after_claim"].as_bool() == Some(true) {
        let mut head = session
            .authority
            .revocation_head()
            .map_err(|e| e.to_string())?;
        head.revision += 1;
        head.revoked_grant_ids.insert(grant.grant.grant_id);
        session
            .authority
            .update_revocations(head)
            .map_err(|e| e.to_string())?;
    }
    let delay = command["driver_delay_ms"].as_u64().unwrap_or(0).min(1000);
    let fail = command["driver_fail"].as_bool().unwrap_or(false);
    let panic_after_entry = command["driver_panic"].as_bool().unwrap_or(false);
    let trace = session.driver_log.clone();
    let manifest_digest = session
        .owner
        .registry()
        .manifest(&binding.inference.model_id)
        .ok_or("native manifest missing")?
        .support_digest;
    let result = session.consumer.execute(
        &mut session.owner,
        &mut session.control,
        &session.authority,
        token,
        &binding,
        |payload, request| {
            driver(
                &trace,
                manifest_digest,
                payload,
                request,
                delay,
                fail,
                panic_after_entry,
            )
        },
    );
    match result {
        Ok(receipt) => Ok(
            json!({"ok":true,"sequence":sequence,"revision":binding.rule_revision,"rule_revision":binding.rule_revision,"generation":binding.generation.get(),"checkpoint_digest":binding.checkpoint_digest.to_string(),"effect":receipt.inference.prediction_q24.iter().map(|x|x/Q).collect::<Vec<_>>(),"output_digest":receipt.inference.output_digest.to_string(),"receipt_digest":receipt.inference.receipt_digest.to_string(),"rule_binding_digest":receipt.rule_binding_digest.to_string(),"elapsed_micros":receipt.elapsed_micros,"callback_micros":receipt.callback_micros,"journal_bytes":receipt.journal_bytes,"observed_memory_bytes":receipt.inference.observed_memory_bytes,"transient_allocation_bytes":receipt.inference.transient_allocation_bytes,"memory_observation_scope":"selected payload length and finite vector capacity bytes; JSON heap and process peak unmeasured","production_qualified":false}),
        ),
        Err(error) => {
            let evidence = error.evidence.as_deref();
            Ok(
                json!({"ok":false,"error":error.to_string(),"kind":format!("{:?}",error.kind),"sequence":sequence,"callback_entered":evidence.is_some_and(|x|x.callback_entered),"elapsed_micros":evidence.map(|x|x.elapsed_micros),"callback_micros":evidence.map(|x|x.callback_micros),"journal_bytes":evidence.map(|x|x.journal_bytes),"observed_output_digest":evidence.and_then(|x|x.inference.as_ref()).map(|x|x.output_digest.to_string()),"production_qualified":false}),
            )
        }
    }
}

fn command(
    root: &std::path::Path,
    session: &mut Option<Session>,
    value: &Value,
) -> Result<Value, String> {
    match value["command"]
        .as_str()
        .or_else(|| value["cmd"].as_str())
        .ok_or("command required")?
    {
        "init" => {
            if session.is_some() {
                return Err("already initialized".into());
            }
            *session = Some(open(root, value)?);
            Ok(
                json!({"ok":true,"native_current":true,"independent_selection":true,"production_qualified":false}),
            )
        }
        "execute" => execute(session.as_mut().ok_or("init required")?, value),
        "install_revision" => {
            revision::install(root, session.as_mut().ok_or("init required")?, value)
        }
        "corrupt_current" => {
            fixture::corrupt_current(root)?;
            Ok(json!({"ok":true,"corrupted":true}))
        }
        "revoke_finaluse" => {
            let active = session.as_ref().ok_or("init required")?;
            let mut head = active
                .authority
                .revocation_head()
                .map_err(|e| e.to_string())?;
            head.revision += 1;
            head.revoked_grant_ids
                .insert(format!("research.use.{}", number(value, "sequence")?));
            active
                .authority
                .update_revocations(head)
                .map_err(|e| e.to_string())?;
            Ok(json!({"ok":true,"revoked":true}))
        }
        "expire_selection" => {
            let active = session.as_ref().ok_or("init required")?;
            let now = fixture::now_ms()?;
            let wait = (active.expires + 1) * 1000;
            if wait > now + 2500 {
                return Err("initialize selection_lifetime_s=1 for bounded expiry test".into());
            }
            if wait > now {
                std::thread::sleep(Duration::from_millis(wait - now));
            }
            Ok(json!({"ok":true,"selection_expired":true}))
        }
        "restart" => {
            let old = session.take().ok_or("init required")?;
            *session = Some(revision::restart(root, old)?);
            Ok(json!({"ok":true,"reopened":true,"production_qualified":false}))
        }
        "status" => {
            let bytes = fs::metadata(root.join("inference.journal")).map_or(0, |x| x.len());
            Ok(
                json!({"ok":true,"initialized":session.is_some(),"inference_journal_bytes":bytes,"production_qualified":false}),
            )
        }
        "quit" => Ok(json!({"ok":true,"quit":true})),
        _ => Err("unknown command".into()),
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(
        std::env::args()
            .nth(1)
            .ok_or("usage: native-rule-use RESEARCH_ROOT")?,
    );
    let mut session = None;
    let stdin = io::stdin();
    let mut reader = stdin.lock();
    let mut stdout = io::stdout().lock();
    loop {
        let mut line = Vec::new();
        let count = (&mut reader)
            .take(MAX_LINE + 1)
            .read_until(b'\n', &mut line)?;
        if count == 0 {
            break;
        }
        if count as u64 > MAX_LINE || line.last() != Some(&b'\n') {
            writeln!(
                stdout,
                "{}",
                json!({"ok":false,"error":"bounded complete line required"})
            )?;
            stdout.flush()?;
            break;
        }
        let parsed: Result<Value, _> = serde_json::from_slice(&line);
        let quit = parsed
            .as_ref()
            .ok()
            .is_some_and(|x| x["command"] == "quit" || x["cmd"] == "quit");
        let response = match parsed {
            Ok(value) => command(&root, &mut session, &value).unwrap_or_else(
                |error| json!({"ok":false,"error":error,"production_qualified":false}),
            ),
            Err(error) => {
                json!({"ok":false,"error":error.to_string(),"production_qualified":false})
            }
        };
        writeln!(stdout, "{response}")?;
        stdout.flush()?;
        if quit {
            break;
        }
    }
    Ok(())
}
