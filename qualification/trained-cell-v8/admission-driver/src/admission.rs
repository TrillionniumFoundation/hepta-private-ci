//! Only validated evidence reaches the unchanged, externally signed owner path.
use crate::Result;
use crate::ensure;
use crate::profile::Profile;
use crate::report::Loaded;
use crate::report::hash;
use crate::report::read;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use std::path::Path;

pub fn reject(loaded: &Loaded) -> Result<Value> {
    ensure(
        !loaded.inputs.all_numeric_gates_pass,
        "a passing candidate cannot be reported as a scientific rejection",
    )?;
    Ok(
        json!({"schema":"hepta.host-profile-rejection.v1","status":"rejected_before_owner",
        "reason":"frozen numerical, census or completion gate failed",
        "disposition":loaded.disposition(),"owner_opened":false,"owner_writes":0,
        "signing_proposal_created":false,"candidate_published":false,"production_authority":false}),
    )
}

pub fn positive(
    mode: &str,
    profile: &Profile,
    loaded: &Loaded,
    paths: [&Path; 4],
    output: &Path,
    signature: Option<&Path>,
) -> Result<Value> {
    ensure(
        profile.digest() == loaded.profile_digest && loaded.inputs.all_numeric_gates_pass,
        "uninstalled profile or failed scientific gates cannot prepare a signature",
    )?;
    for (path, field) in paths[..2]
        .iter()
        .zip(["independent_replay_sha256", "independent_statistics_sha256"])
    {
        let bytes = read(path)?;
        ensure(
            Digest32::of_bytes(&bytes) == hash(&loaded.gate, field)?,
            "profile audit read differs from its bound commitment",
        )?;
        let audit: Value = serde_json::from_slice(&bytes)?;
        profile.verify_bindings(&audit)?;
    }
    // Existing implementation rechecks both audit hashes, exact terminal32
    // maps, parity and the external signature before opening the candidate owner.
    // Its prepare step imports only the immutable predecessor in a new research owner.
    hepta_handoff_recovery_v7::positive::run(
        mode,
        &loaded.protocol,
        &loaded.inputs,
        &loaded.gate,
        paths,
        output,
        signature,
    )
}
