//! Prepare source-pinned private gold and an actual fenced holdout owner.
//!
//! This service does not freeze a candidate evaluation plan, consume gold,
//! issue qualification evidence or select artifacts. Those operations require
//! the production runner's authenticated preregistration and real reference.
use crate::FencedFinalHoldoutOwnerV1;
use crate::FinalHoldoutCasAnchorV1;
use crate::HoldoutFenceIssuerV1;
use crate::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    path: PathBuf,
    digest: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    program_digest: String,
    archive: Source,
    earlier_claims: Source,
    holdout_claims: Source,
    corpus: Source,
    private_directory: PathBuf,
    witness_path: PathBuf,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Witness {
    schema: String,
    config_digest: String,
    private_gold_digest: String,
    masked_features_digest: String,
    binding: String,
    fence_generation: u64,
    record_count: u64,
    state_digest: String,
    eligible_claims: usize,
    eligible_components: usize,
    labeled_pairs: usize,
    excluded_shared_claims: usize,
    unjudged_pairs_not_scored: usize,
}
fn digest(text: &str) -> HostResult<Digest32> {
    Ok(text.parse()?)
}
fn boundary() -> HostResult<()> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    for name in ["Uid:", "Gid:"] {
        let values = status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .ok_or("identity")?;
        if values.split_whitespace().count() != 4 || values.split_whitespace().any(|s| s != "0") {
            return Err("holdout custody requires the actual Root owner".into());
        }
    }
    for name in ["CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:"] {
        if status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .map(str::trim)
            != Some("0000000000000000")
        {
            return Err("holdout custody requires zero capabilities".into());
        }
    }
    if status
        .lines()
        .find_map(|line| line.strip_prefix("NoNewPrivs:"))
        .map(str::trim)
        != Some("1")
        || !std::fs::read_to_string("/proc/self/cgroup")?.contains("hepta-fixed-holdout-custody-")
    {
        return Err("holdout custody requires its bounded NoNewPrivileges service".into());
    }
    Ok(())
}
fn private_directory(path: &Path) -> HostResult<File> {
    if !path.is_absolute()
        || path
            .components()
            .any(|c| matches!(c, Component::CurDir | Component::ParentDir))
    {
        return Err("canonical private custody directory required".into());
    }
    for ancestor in path.ancestors() {
        let m = std::fs::symlink_metadata(ancestor)?;
        if !m.is_dir() || m.uid() != 0 || m.mode() & 0o022 != 0 {
            return Err("unprotected custody directory".into());
        }
    }
    if path.metadata()?.mode() & 0o077 != 0 {
        return Err("gold and holdout witnesses must be Root private".into());
    }
    Ok(File::open(path)?)
}
fn create_private(path: &Path, bytes: &[u8]) -> HostResult<File> {
    let parent = private_directory(path.parent().ok_or("custody parent")?)?;
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    parent.sync_all()?;
    Ok(file)
}
fn source(source: &Source, maximum: u64) -> HostResult<Vec<u8>> {
    let bytes = read_root_review_input(&source.path, maximum)?;
    if Digest32::of_bytes(&bytes) != digest(&source.digest)? {
        return Err("pinned source bytes changed".into());
    }
    Ok(bytes)
}
fn rows(bytes: &[u8]) -> HostResult<Vec<(Value, Digest32)>> {
    std::str::from_utf8(bytes)?
        .lines()
        .map(|line| {
            Ok((
                serde_json::from_str(line)?,
                Digest32::of_bytes(line.as_bytes()),
            ))
        })
        .collect()
}
fn claim_id(row: &Value) -> HostResult<u64> {
    row["id"].as_u64().ok_or_else(|| "claim id".into())
}
fn documents(row: &Value) -> HostResult<BTreeSet<u64>> {
    let mut docs = BTreeSet::new();
    for id in row["cited_doc_ids"]
        .as_array()
        .ok_or("cited source documents")?
    {
        docs.insert(id.as_u64().ok_or("cited source document id")?);
    }
    for id in row["evidence"].as_object().ok_or("source evidence")?.keys() {
        docs.insert(id.parse()?);
    }
    Ok(docs)
}
/// Exclude whole held-out citation components touching earlier source rows.
fn eligible_components(
    earlier: &[(Value, Digest32)],
    heldout: &[(Value, Digest32)],
) -> HostResult<Vec<Vec<usize>>> {
    let seen_claims = earlier
        .iter()
        .map(|(r, _)| claim_id(r))
        .collect::<HostResult<BTreeSet<_>>>()?;
    let mut seen_docs = BTreeSet::new();
    for (row, _) in earlier {
        seen_docs.extend(documents(row)?);
    }
    let docs = heldout
        .iter()
        .map(|(r, _)| documents(r))
        .collect::<HostResult<Vec<_>>>()?;
    let mut by_doc: BTreeMap<u64, Vec<usize>> = BTreeMap::new();
    let mut ids = BTreeSet::new();
    for (index, (row, _)) in heldout.iter().enumerate() {
        if !ids.insert(claim_id(row)?) {
            return Err("duplicate held-out claim".into());
        }
        for doc in &docs[index] {
            by_doc.entry(*doc).or_default().push(index);
        }
    }
    let mut visited = BTreeSet::new();
    let mut eligible = Vec::new();
    for start in 0..heldout.len() {
        if visited.contains(&start) {
            continue;
        }
        let mut pending = vec![start];
        let mut component = Vec::new();
        let mut shared = false;
        while let Some(index) = pending.pop() {
            if !visited.insert(index) {
                continue;
            }
            component.push(index);
            shared |= seen_claims.contains(&claim_id(&heldout[index].0)?)
                || !docs[index].is_disjoint(&seen_docs);
            for doc in &docs[index] {
                pending.extend(by_doc[doc].iter().copied().filter(|j| !visited.contains(j)));
            }
        }
        if !shared {
            component.sort_unstable();
            eligible.push(component);
        }
    }
    Ok(eligible)
}
fn config(path: &Path) -> HostResult<(Config, Digest32)> {
    boundary()?;
    let bytes = read_root_review_input(path, 16 * 1024)?;
    let config: Config = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.fixed-source-holdout.config.v1"
        || Digest32::of_bytes(&read_root_review_input(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
        )?) != digest(&config.program_digest)?
    {
        return Err("holdout program/config pin".into());
    }
    private_directory(&config.private_directory)?;
    private_directory(config.witness_path.parent().ok_or("witness parent")?)?;
    if config.witness_path.parent() == Some(config.private_directory.as_path()) {
        return Err("holdout witness requires an independently retained directory".into());
    }
    Ok((config, Digest32::of_bytes(&bytes)))
}
pub fn prepare_fixed_source_holdout(path: &Path) -> HostResult<()> {
    let (config, config_digest) = config(path)?;
    source(&config.archive, 32 * 1024 * 1024)?;
    let earlier = rows(&source(&config.earlier_claims, 4 * 1024 * 1024)?)?;
    let heldout = rows(&source(&config.holdout_claims, 4 * 1024 * 1024)?)?;
    let corpus = rows(&source(&config.corpus, 32 * 1024 * 1024)?)?;
    let corpus: BTreeMap<_, _> = corpus
        .iter()
        .map(|(row, sha)| Ok((row["doc_id"].as_u64().ok_or("corpus id")?, (row, sha))))
        .collect::<HostResult<_>>()?;
    let components = eligible_components(&earlier, &heldout)?;
    let eligible_claims: usize = components.iter().map(Vec::len).sum();
    let mut private_tasks = Vec::new();
    let mut features = Vec::new();
    let mut unjudged = 0;
    for component in &components {
        for index in component {
            let (claim, claim_digest) = &heldout[*index];
            let evidence = claim["evidence"].as_object().ok_or("gold evidence")?;
            unjudged += documents(claim)?
                .iter()
                .filter(|d| !evidence.contains_key(&d.to_string()))
                .count();
            for (doc_id, labels) in evidence {
                let doc_id: u64 = doc_id.parse()?;
                let (doc, doc_digest) = corpus.get(&doc_id).ok_or("missing corpus source")?;
                let mut gold = BTreeSet::new();
                for label in labels.as_array().ok_or("gold annotations")? {
                    let label = label["label"].as_str().ok_or("gold annotation label")?;
                    if !matches!(label, "SUPPORT" | "CONTRADICT") {
                        return Err("unknown source label".into());
                    }
                    gold.insert(label);
                }
                if gold.len() != 1 {
                    return Err("ambiguous source gold".into());
                }
                let feature = serde_json::json!({
                    "claim_id":claim_id(claim)?,"doc_id":doc_id,"claim_text":claim["claim"],
                    "title":doc["title"],"abstract_sentences":doc["abstract"],
                    "claim_source_record_digest":claim_digest.to_string(),"corpus_source_record_digest":doc_digest.to_string(),
                    "source_component_claim_ids":component.iter().map(|i| claim_id(&heldout[*i].0)).collect::<HostResult<Vec<_>>>()?,
                });
                private_tasks.push(serde_json::json!({"features":feature,"gold":gold.into_iter().next().ok_or("gold")?,"original_annotation":labels}));
                features.push(feature);
            }
        }
    }
    if private_tasks.is_empty() {
        return Err("no genuine disjoint labeled holdout remains".into());
    }
    let private_gold = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.source-pinned-private-gold.v1","source_archive_digest":config.archive.digest,
        "earlier_claims_digest":config.earlier_claims.digest,"holdout_claims_digest":config.holdout_claims.digest,
        "corpus_digest":config.corpus.digest,"tasks":private_tasks,
        "scope":"public SciFact held-out claim and cited abstract classification; no cross-subject or longitudinal claim",
    }))?;
    let masked = serde_json::to_vec(&features)?;
    let gold_digest = Digest32::of_bytes(&private_gold);
    let binding = Digest32::of_bytes(&serde_json::to_vec(
        &serde_json::json!({"domain":"hepta.fixed-source-holdout.binding.v1","config":config_digest.to_string(),"gold":gold_digest.to_string()}),
    )?);
    create_private(&config.private_directory.join("gold.json"), &private_gold)?;
    create_private(
        &config.private_directory.join("masked-features.json"),
        &masked,
    )?;
    let journal = create_private(&config.private_directory.join("holdout-cas.bin"), &[])?;
    let store = LockedFileFinalHoldoutCasStoreV1::create(journal, binding)?;
    let fence = HoldoutFenceIssuerV1::resume(
        StableId::new("fixed-root-gold-custody")?,
        config_digest,
        None,
    )?
    .issue(binding)?;
    let owner = FencedFinalHoldoutOwnerV1::initialize(store, binding, fence)?;
    let anchor = owner.anchor();
    let witness = Witness {
        schema: "hepta.fixed-source-holdout.witness.v1".into(),
        config_digest: config_digest.to_string(),
        private_gold_digest: gold_digest.to_string(),
        masked_features_digest: Digest32::of_bytes(&masked).to_string(),
        binding: binding.to_string(),
        fence_generation: anchor.fence_generation,
        record_count: anchor.record_count,
        state_digest: anchor.state_digest.to_string(),
        eligible_claims,
        eligible_components: components.len(),
        labeled_pairs: private_tasks.len(),
        excluded_shared_claims: heldout.len() - eligible_claims,
        unjudged_pairs_not_scored: unjudged,
    };
    create_private(&config.witness_path, &serde_json::to_vec(&witness)?)?;
    publication(&witness)
}
pub fn inspect_fixed_source_holdout(path: &Path) -> HostResult<()> {
    let (config, config_digest) = config(path)?;
    let witness: Witness =
        serde_json::from_slice(&read_root_review_input(&config.witness_path, 16 * 1024)?)?;
    if witness.schema != "hepta.fixed-source-holdout.witness.v1"
        || digest(&witness.config_digest)? != config_digest
    {
        return Err("independent holdout witness/config changed".into());
    }
    for (name, expected) in [
        ("gold.json", &witness.private_gold_digest),
        ("masked-features.json", &witness.masked_features_digest),
    ] {
        if Digest32::of_bytes(&read_root_review_input(
            &config.private_directory.join(name),
            32 * 1024 * 1024,
        )?) != digest(expected)?
        {
            return Err("private held-out data changed".into());
        }
    }
    let path = config.private_directory.join("holdout-cas.bin");
    let before = read_root_review_input(&path, 32 * 1024 * 1024)?;
    let file = OpenOptions::new().read(true).write(true).open(&path)?;
    if file.metadata()?.uid() != 0 || file.metadata()?.mode() & 0o077 != 0 {
        return Err("private CAS ownership".into());
    }
    let expected = FinalHoldoutCasAnchorV1 {
        fence_generation: witness.fence_generation,
        record_count: witness.record_count,
        state_digest: digest(&witness.state_digest)?,
    };
    let store =
        LockedFileFinalHoldoutCasStoreV1::recover(file, digest(&witness.binding)?, Some(expected))?;
    if store.anchor() != Some(expected)
        || before != read_root_review_input(&path, 32 * 1024 * 1024)?
    {
        return Err("holdout state differs from its acknowledged witness".into());
    }
    publication(&witness)
}
fn publication(witness: &Witness) -> HostResult<()> {
    println!(
        "{}",
        serde_json::json!({
            "schema":"hepta.fixed-source-holdout.prepared.v1","private_gold_digest":witness.private_gold_digest,
            "masked_features_digest":witness.masked_features_digest,"config_digest":witness.config_digest,
            "binding":witness.binding,"fence_generation":witness.fence_generation,"record_count":witness.record_count,"state_digest":witness.state_digest,
            "eligible_claims":witness.eligible_claims,"eligible_components":witness.eligible_components,"labeled_pairs":witness.labeled_pairs,
            "excluded_shared_claims":witness.excluded_shared_claims,"unjudged_pairs_not_scored":witness.unjudged_pairs_not_scored,
            "holdout_consumed":witness.record_count > 0,"evaluation_plan_registered":false,"qualified":false,"authority_grants_any":false,
        })
    );
    Ok(())
}

#[cfg(test)]
#[path = "fixed_holdout_custody_tests.rs"]
mod tests;
