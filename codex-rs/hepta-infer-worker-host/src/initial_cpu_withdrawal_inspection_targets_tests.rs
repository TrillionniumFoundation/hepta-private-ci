//! Registry projection tests supply no current-owner authority.
use super::*;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

fn registry() -> HostResult<ArtifactRegistry> {
    let mut registry = ArtifactRegistry::new();
    for (name, parent, generation) in [
        ("source", None, 1),
        ("child", Some("source"), 2),
        ("grandchild", Some("child"), 3),
        ("unrelated", None, 1),
    ] {
        registry.append(ArtifactEvent::Register {
            event_id: id(&format!("register-{name}"))?,
            manifest: ArtifactManifest {
                artifact_id: id(name)?,
                kind: ArtifactKind::Model,
                generation: Generation::new(generation)?,
                predecessor_id: parent.map(id).transpose()?,
                content_digest: Digest32::of_bytes(name.as_bytes()),
                objective_digest: Digest32::of_bytes(b"original-objective"),
                support_digest: Digest32::of_bytes(name.as_bytes()),
                producer_id: id("original-producer")?,
                compatibility_digest: Digest32::of_bytes(b"original-compatible"),
                encoded_size_bytes: 8,
            },
        })?;
    }
    Ok(registry)
}
fn changes(names: &[&str]) -> HostResult<Vec<ArtifactEvent>> {
    names
        .iter()
        .map(|name| {
            Ok(ArtifactEvent::Revoke(StateChange {
                event_id: id(&format!("withdraw-{name}"))?,
                artifact_id: id(name)?,
                evaluator_id: id("original-authority")?,
                reason_digest: Digest32::of_bytes(b"actual-lineage-reason"),
            }))
        })
        .collect()
}
#[test]
fn inherited_dataset_members_keep_their_actual_descendant_roles() -> HostResult<()> {
    let registry = registry()?;
    let names = ["source", "child", "grandchild"];
    let direct = names
        .iter()
        .map(|name| id(name))
        .collect::<HostResult<BTreeSet<_>>>()?;
    let targets = names.map(str::to_owned);
    assert_eq!(
        complete(&registry, &direct, &targets, &changes(&names)?)?,
        BTreeMap::from([
            (id("source")?, "source"),
            (id("child")?, "descendant"),
            (id("grandchild")?, "descendant"),
        ])
    );
    Ok(())
}
#[test]
fn partial_foreign_or_duplicate_denials_and_suffixes_never_complete() -> HostResult<()> {
    let registry = registry()?;
    let names = ["source", "child", "grandchild"];
    let direct = names
        .iter()
        .map(|name| id(name))
        .collect::<HostResult<BTreeSet<_>>>()?;
    let targets = names.map(str::to_owned);
    let suffix = changes(&names)?;
    assert!(complete(&registry, &direct, &targets[..2], &suffix).is_err());
    assert!(complete(&registry, &direct, &targets, &suffix[..2]).is_err());
    let mut duplicate = targets.to_vec();
    duplicate.push("source".to_owned());
    assert!(complete(&registry, &direct, &duplicate, &suffix).is_err());
    let mut foreign = targets.to_vec();
    foreign[2] = "unrelated".to_owned();
    assert!(complete(&registry, &direct, &foreign, &suffix).is_err());
    let mut duplicate_suffix = suffix.clone();
    duplicate_suffix.push(suffix[0].clone());
    assert!(complete(&registry, &direct, &targets, &duplicate_suffix).is_err());
    let mut foreign_suffix = suffix;
    foreign_suffix[2] = changes(&["unrelated"])?.remove(0);
    assert!(complete(&registry, &direct, &targets, &foreign_suffix).is_err());
    let missing = BTreeSet::from([id("source")?]);
    assert!(complete(&registry, &missing, &targets[..1], &changes(&["source"])?).is_err());
    Ok(())
}
