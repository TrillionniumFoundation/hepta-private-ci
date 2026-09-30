//! Unprivileged native generator. It owns only its Generator signing key.
use super::events::EventBindings;
use super::events::ExecutedPolicy;
use super::events::decision;
use super::files::Access;
use super::files::ReviewResult;
use super::files::read_root;
use super::generator_wire::GeneratorBatch;
use super::generator_wire::GeneratorContract;
use super::generator_wire::SignedDecisionRow;
use super::generator_wire::encode_hex;
use super::generator_wire::generator_evidence;
use super::generator_wire::now_ms;
use super::generator_wire::program_digest;
use super::observations::NativeInput;
use super::observations::NativeObservation;
use super::observations::PinnedModel;
use super::observations::SourceMapping;
use super::observations::validate_observation;
use crate::decision_signing_payload_v2;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;

fn boundary(uid: u32) -> ReviewResult<String> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    let field = |name: &str| {
        status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .unwrap_or("")
            .trim()
    };
    if field("Uid:").split_whitespace().count() != 4
        || field("Gid:").split_whitespace().count() != 4
        || field("Uid:")
            .split_whitespace()
            .any(|id| id != uid.to_string())
        || field("Gid:")
            .split_whitespace()
            .any(|id| id != uid.to_string())
        || !field("Groups:").is_empty()
        || field("NoNewPrivs:") != "1"
        || ["CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:"]
            .iter()
            .any(|name| field(name) != "0000000000000000")
        || uid == 0
    {
        return Err(
            "generator requires actual non-root UID, no groups/capabilities and NoNewPrivileges"
                .into(),
        );
    }
    let cgroup = std::fs::read_to_string("/proc/self/cgroup")?;
    if !cgroup.contains("hepta-native-generator-") {
        return Err("generator must run in the fixed bounded service cgroup".into());
    }
    Ok(cgroup)
}
fn user_directory(path: &Path, uid: u32) -> ReviewResult<()> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::CurDir | Component::ParentDir))
    {
        return Err("canonical user key path required".into());
    }
    for ancestor in path.ancestors() {
        let m = std::fs::symlink_metadata(ancestor)?;
        if !m.is_dir() || (m.uid() != 0 && m.uid() != uid) || m.mode() & 0o022 != 0 {
            return Err("unsafe generator key ancestor".into());
        }
    }
    let m = std::fs::symlink_metadata(path)?;
    if m.uid() != uid || m.mode() & 0o077 != 0 {
        return Err("generator key directory must be private to its UID".into());
    }
    Ok(())
}
fn user_key(path: &Path, uid: u32) -> ReviewResult<SigningKey> {
    user_directory(path.parent().ok_or("key parent")?, uid)?;
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.uid() != uid
        || before.nlink() != 1
        || before.mode() & 0o077 != 0
        || before.len() != 32
    {
        return Err("generator key owner/mode/length mismatch".into());
    }
    let mut file = File::open(path)?;
    let after = file.metadata()?;
    if before.dev() != after.dev() || before.ino() != after.ino() {
        return Err("generator key changed while opening".into());
    }
    let mut seed = [0; 32];
    file.read_exact(&mut seed)?;
    Ok(SigningKey::from_bytes(&seed))
}
pub(super) fn initialize_key(path: &Path, uid: u32) -> ReviewResult<()> {
    boundary(uid)?;
    user_directory(path.parent().ok_or("key parent")?, uid)?;
    if !path.exists() {
        let mut seed = [0; 32];
        File::open("/dev/urandom")?.read_exact(&mut seed)?;
        let mut out = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)?;
        out.write_all(&seed)?;
        out.sync_all()?;
        File::open(path.parent().ok_or("key parent")?)?.sync_all()?;
    }
    let key = user_key(path, uid)?;
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.native-generator-public-key.v1","uid":uid,"verifying_key_hex":encode_hex(key.verifying_key().as_bytes()),"qualified":false})
    );
    Ok(())
}
fn lines<T: serde::de::DeserializeOwned>(
    bytes: &[u8],
    row_bound: usize,
) -> ReviewResult<Vec<(Vec<u8>, T)>> {
    if !bytes.ends_with(b"\n") || bytes.len() > 4 * 1024 * 1024 {
        return Err("complete bounded stream required".into());
    }
    let mut output = Vec::new();
    for line in bytes.split_inclusive(|byte| *byte == b'\n') {
        if line.len() > row_bound || output.len() >= 2048 {
            return Err("row/count bound".into());
        }
        output.push((line.to_vec(), serde_json::from_slice(line)?));
    }
    Ok(output)
}
fn score(
    contract: &GeneratorContract,
    manifest: &Path,
    model: &PinnedModel,
) -> ReviewResult<Vec<(Vec<u8>, NativeObservation)>> {
    let output = Command::new(&contract.scorer_path)
        .args([
            manifest.as_os_str(),
            std::ffi::OsStr::new(&model.manifest.to_string()),
        ])
        .stdin(Stdio::from(super::files::root_file(
            &contract.inputs_path,
            Access::Immutable,
        )?))
        .output()?;
    if !output.status.success() {
        return Err("pinned offline scorer failed".into());
    }
    lines(&output.stdout, 16 * 1024)
}
pub(super) fn run(request: &Path) -> ReviewResult<()> {
    let bytes = read_root(request, 32 * 1024, Access::Immutable)?;
    let contract: GeneratorContract = serde_json::from_slice(&bytes)?;
    let cgroup = boundary(contract.uid)?;
    let program = program_digest(&std::env::current_exe()?)?;
    if contract.schema != "hepta.native-generator-contract.v1"
        || program != contract.generator_program_digest.parse::<Digest32>()?
        || program_digest(&contract.scorer_path)? != contract.scorer_digest.parse::<Digest32>()?
    {
        return Err("generator/scorer program identity mismatch".into());
    }
    for path in &contract.inaccessible_paths {
        match File::open(path) {Err(error) if error.kind()==std::io::ErrorKind::PermissionDenied=>(),_=>return Err("generator can access private evaluator custody or its denial was not permission-enforced".into())}
    }
    let key = user_key(&contract.private_key_path, contract.uid)?;
    let principal = contract.principal.principal()?;
    if Digest32::of_bytes(key.verifying_key().as_bytes()) != principal.signing_key_digest {
        return Err("generator key does not match the admitted public principal".into());
    }
    let now = now_ms()?;
    principal.validate(now)?;
    let binding = EventBindings {
        objective: contract.objective_digest.parse()?,
        generator: principal.clone(),
        observer: principal,
        program_digest: program,
    };
    let candidate = PinnedModel::open(
        &contract.candidate_manifest_path,
        &contract.candidate_weights_path,
    )?;
    let baseline = PinnedModel::open(
        &contract.baseline_manifest_path,
        &contract.baseline_weights_path,
    )?;
    let inputs = lines::<NativeInput>(
        &read_root(&contract.inputs_path, 4 * 1024 * 1024, Access::Immutable)?,
        16 * 1024,
    )?;
    let mappings = lines::<SourceMapping>(
        &read_root(&contract.mapping_path, 4 * 1024 * 1024, Access::Immutable)?,
        1024,
    )?;
    let candidate_rows = score(&contract, &contract.candidate_manifest_path, &candidate)?;
    let baseline_rows = score(&contract, &contract.baseline_manifest_path, &baseline)?;
    if inputs.is_empty()
        || [mappings.len(), candidate_rows.len(), baseline_rows.len()]
            .iter()
            .any(|count| *count != inputs.len())
    {
        return Err("incomplete generator inputs/executions".into());
    }
    let issued = now_ms()?;
    let mut rows = Vec::new();
    for (index, ((input_bytes, input), (_, mapping))) in inputs.iter().zip(&mappings).enumerate() {
        if input.request_id != mapping.request_id
            || input.feature_vector_q24.len() != 512
            || input.expected_output_width != 10
        {
            return Err("generator source/input identity mismatch".into());
        }
        let feature: Vec<_> = input
            .feature_vector_q24
            .iter()
            .flat_map(|number| number.to_be_bytes())
            .collect();
        for (label, (raw, observation), model) in [
            ("candidate", &candidate_rows[index], &candidate),
            ("baseline", &baseline_rows[index], &baseline),
        ] {
            let selected = validate_observation(
                observation,
                model,
                &input.request_id,
                Digest32::of_bytes(input_bytes),
                Digest32::of_bytes(&feature),
                now_ms()?,
            )?;
            let fact = decision(
                &binding,
                contract.audit_digest.parse()?,
                index,
                ExecutedPolicy {
                    label,
                    observation,
                    selected,
                    model,
                    support: Digest32::of_bytes(raw),
                },
                mapping.source_record_sha256.parse()?,
            )?;
            let payload = decision_signing_payload_v2(&fact)?;
            let mut row = SignedDecisionRow {
                index,
                policy: label.to_owned(),
                observation_line: std::str::from_utf8(raw)?.to_owned(),
                payload_digest: Digest32::of_bytes(&payload).to_string(),
                signature_hex: encode_hex(&[0; 64]),
            };
            let evidence = generator_evidence(&contract, &row, issued)?;
            row.signature_hex = encode_hex(&key.sign(&evidence.signing_bytes()).to_bytes());
            rows.push(row);
        }
    }
    if program_digest(&contract.scorer_path)? != contract.scorer_digest.parse::<Digest32>()? {
        return Err("scorer changed during generation".into());
    }
    let batch = GeneratorBatch {
        schema: "hepta.native-generator-decisions.v1".to_owned(),
        contract_digest: Digest32::of_bytes(&bytes).to_string(),
        program_digest: program.to_string(),
        uid: contract.uid,
        no_new_privileges: true,
        supplementary_groups_empty: true,
        capabilities_zero: true,
        cgroup,
        private_custody_denied: contract.inaccessible_paths.len(),
        issued_at_ms: issued,
        rows,
    };
    println!("{}", serde_json::to_string(&batch)?);
    Ok(())
}
