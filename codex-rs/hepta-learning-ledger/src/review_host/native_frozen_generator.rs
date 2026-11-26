//! The original isolated Generator signs one Root-approved frozen iteration.
//! Root's window owner validates the original round, native receipt and stores
//! before creating these immutable sources; this endpoint grants no effects.

use super::boundary;
use super::user_key;
use crate::LearningEvidenceRoleV1;
use crate::SignedLearningEvidenceV1;
use crate::activate_learning_trust;
use crate::review_host::ReviewEvidenceWireV1;
use crate::review_host::ReviewTrustWireV1;
use crate::review_host::files::Access;
use crate::review_host::files::ReviewResult;
use crate::review_host::files::read_root;
use crate::review_host::generator_wire::bounded_generator_controller;
use crate::review_host::generator_wire::now_ms;
use crate::review_host::generator_wire::program_digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

const FROZEN_PREFIX: &[u8] = b"hepta.agentd.self-iteration-candidate.v2\0";
const MAX_FROZEN_BYTES: u64 = 512 * 1024;

/// Only the admitted Root window owner constructs this request. It contains
/// public trust and immutable factual bytes, never an Agent-supplied signer.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeFrozenGeneratorRequestV1 {
    pub schema: String,
    pub uid: u32,
    pub generator_program_digest: String,
    pub trust: ReviewTrustWireV1,
    pub principal_id: String,
    pub frozen_payload_path: PathBuf,
    pub frozen_payload_digest: String,
    pub window_authorization_path: PathBuf,
    pub window_authorization_digest: String,
    pub private_key_path: PathBuf,
    pub inaccessible_paths: Vec<PathBuf>,
    pub expires_at_ms: u64,
}

pub(in crate::review_host) fn frozen_payload(bytes: &[u8], expected: Digest32) -> ReviewResult<()> {
    if bytes.len() as u64 > MAX_FROZEN_BYTES
        || bytes.len() <= FROZEN_PREFIX.len()
        || !bytes.starts_with(FROZEN_PREFIX)
        || expected.is_zero()
        || Digest32::of_bytes(bytes) != expected
    {
        return Err("fixed Generator requires the complete Root-approved V2 frozen source".into());
    }
    Ok(())
}

pub(crate) fn run(request: &Path) -> ReviewResult<()> {
    let bytes = read_root(request, 64 * 1024, Access::Immutable)?;
    let request: NativeFrozenGeneratorRequestV1 = serde_json::from_slice(&bytes)?;
    boundary(request.uid)?;
    let program = program_digest(&std::env::current_exe()?)?;
    let now = now_ms()?;
    if request.schema != "hepta.native-frozen-generator-request.v1"
        || program != request.generator_program_digest.parse::<Digest32>()?
        || request.expires_at_ms <= now
        || request.expires_at_ms > now.saturating_add(3_600_000)
        || !(2..=32).contains(&request.inaccessible_paths.len())
    {
        return Err("fixed Generator program, purpose, denial roster or window expired".into());
    }
    let window = read_root(
        &request.window_authorization_path,
        64 * 1024,
        Access::Immutable,
    )?;
    let window_digest: Digest32 = request.window_authorization_digest.parse()?;
    if window_digest.is_zero() || Digest32::of_bytes(&window) != window_digest {
        return Err("original Root window authorization changed".into());
    }
    for path in &request.inaccessible_paths {
        match File::open(path) {
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {}
            _ => return Err("Generator private custody denial is not permission-enforced".into()),
        }
    }
    let payload = read_root(
        &request.frozen_payload_path,
        MAX_FROZEN_BYTES,
        Access::Immutable,
    )?;
    let payload_digest: Digest32 = request.frozen_payload_digest.parse()?;
    frozen_payload(&payload, payload_digest)?;
    let (root, distribution) = request.trust.native()?;
    let signer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|signer| {
            signer.principal.principal_id.as_str() == request.principal_id
                && signer.principal.principal_id.as_str() == "native-unprivileged-generator"
                && signer.roles == [LearningEvidenceRoleV1::Generator]
        })
        .ok_or("original admitted Generator principal is absent")?;
    let controller = bounded_generator_controller(
        program,
        request.uid,
        program_digest(Path::new("/usr/bin/setpriv"))?,
        program_digest(Path::new("/usr/bin/systemd-run"))?,
    )?;
    if signer.controller_id != controller {
        return Err("original admitted Generator controller changed".into());
    }
    let principal = signer.principal.clone();
    let trust = activate_learning_trust(&root, distribution, None, now)?;
    let key = user_key(&request.private_key_path, request.uid)?;
    if Digest32::of_bytes(key.verifying_key().as_bytes()) != principal.signing_key_digest {
        return Err("original admitted Generator key changed".into());
    }
    let issued_at = now_ms()?;
    trust.revalidate_at(issued_at)?;
    principal.validate(issued_at)?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!("native.frozen.{payload_digest}"))?,
        principal_id: principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: principal.authority_epoch,
        issued_at,
        expires_at: request
            .expires_at_ms
            .min(principal.expires_at)
            .min(trust.expires_at()),
        payload_digest,
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &evidence,
        &payload,
        issued_at,
    )?;
    println!(
        "{}",
        serde_json::to_string(&ReviewEvidenceWireV1::from_native(&evidence))?
    );
    Ok(())
}

#[cfg(test)]
#[path = "native_frozen_generator_tests.rs"]
mod tests;
