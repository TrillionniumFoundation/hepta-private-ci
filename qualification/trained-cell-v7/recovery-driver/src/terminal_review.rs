//! Bind positive admission to the exact evaluated terminal checkpoint family.
//! Generic transport and unadmitted diagnostic restoration may remain mid-plan.

use crate::handoff_version::Handoff;
use crate::*;

pub(crate) fn commitment(inputs: &report::Inputs, gate: &Value) -> Result<Value> {
    let bundle = Handoff::decode(&inputs.candidate, Digest32::of_bytes(&inputs.candidate))?;
    ensure(
        bundle.protocol_digest() == inputs.policy.protocol_digest,
        "terminal candidate protocol differs",
    )?;
    let mut cells = BTreeMap::new();
    for checkpoint in bundle.checkpoints() {
        let wrapper: Value = serde_json::from_slice(checkpoint.controller_metadata_json())?;
        let source: Value =
            serde_json::from_str(report::string(&wrapper, "source_controller_json")?)?;
        ensure(
            wrapper["absolute_step"] == 32
                && wrapper["registered_steps"] == 32
                && source["absolute_step"] == 32
                && source["registered_steps"] == 32
                && source["contract"]["registered_steps"] == 32
                && source["run_status"] == "completed"
                && source["failure_ledger"] == json!([])
                && wrapper["action_cursor"] == wrapper["plan_horizon"]
                && checkpoint.pending_actions().is_empty()
                && source["receipt_chain"]["count"] == 32
                && source["counters"]["committed_steps"] == 32,
            "positive admission requires the completed exact32 terminal candidate",
        )?;
        let chain = json!({"certificate_chain": source["certificate_chain"],
            "receipt_chain": source["receipt_chain"], "counters": source["counters"]});
        let chain_digest = Digest32::of_bytes(&serde_json::to_vec(&chain)?);
        ensure(
            report::hash(&wrapper, "receipt_chain_sha256")? == chain_digest,
            "terminal controller receipt commitment differs",
        )?;
        cells.insert(checkpoint.cell_id().as_str().to_string(), json!({
            "state_sha256": report::hash(&wrapper, "state_sha256")?.to_string(),
            "source_controller_sha256": report::hash(&wrapper, "source_controller_sha256")?.to_string(),
            "receipt_chain_sha256": chain_digest.to_string(),
            "resolved_plan_sha256": report::hash(&wrapper, "resolved_plan_sha256")?.to_string()}));
    }
    let expected: std::collections::BTreeSet<String> = report::TASKS
        .iter()
        .flat_map(|task| {
            ["linear", "gated"].into_iter().flat_map(move |mode| {
                report::SEEDS
                    .into_iter()
                    .map(move |seed| format!("{task}-{mode}-seed{seed}"))
            })
        })
        .collect();
    ensure(
        cells
            .keys()
            .cloned()
            .collect::<std::collections::BTreeSet<_>>()
            == expected,
        "terminal candidate family is incomplete",
    )?;
    Ok(
        json!({"schema":format!("hepta.reviewed-terminal-checkpoints.v{}",bundle.version()),
        "protocol_sha256":inputs.policy.protocol_digest.to_string(),
        "report_sha256":inputs.report_digest.to_string(),
        "source_candidate_bundle_sha256":report::hash(gate,"source_candidate_bundle_sha256")?.to_string(),
        "native_candidate_sha256":bundle.content_digest().to_string(),
        "registered_steps":32,"cells":cells}),
    )
}

pub(crate) fn verify(
    inputs: &report::Inputs,
    gate: &Value,
    conversion: &Path,
    replay: &Path,
    statistics: &Path,
) -> Result<()> {
    if !Handoff::recognizes(&inputs.candidate) {
        // Frozen V5 regression path has its own historical serving-only profile.
        return Ok(());
    }
    let expected = commitment(inputs, gate)?;
    let digest = Digest32::of_bytes(&serde_json::to_vec(&expected)?);
    let conversion_bytes = report::read(conversion)?;
    ensure(
        Digest32::of_bytes(&conversion_bytes) == report::hash(gate, "conversion_manifest_sha256")?,
        "terminal conversion read differs from its bound commitment",
    )?;
    let converted: Value = serde_json::from_slice(&conversion_bytes)?;
    ensure(
        converted["evaluated_terminal_checkpoints"] == expected
            && report::hash(gate, "evaluated_terminal_checkpoints_sha256")? == digest,
        "reviewed terminal checkpoint map differs from the actual candidate",
    )?;
    for (path, field) in [
        (replay, "independent_replay_sha256"),
        (statistics, "independent_statistics_sha256"),
    ] {
        let bytes = report::read(path)?;
        ensure(
            Digest32::of_bytes(&bytes) == report::hash(gate, field)?,
            "terminal audit read differs from its bound commitment",
        )?;
        let audit: Value = serde_json::from_slice(&bytes)?;
        ensure(
            report::hash(&audit, "evaluated_terminal_checkpoints_sha256")? == digest,
            "independent audit did not review this exact terminal checkpoint family",
        )?;
    }
    Ok(())
}
