use super::SkillMetadataFile;
use super::resolve_policy;
use codex_protocol::protocol::Product;
use codex_skills::SkillPolicy;
use pretty_assertions::assert_eq;

#[test]
fn metadata_policy_preserves_yaml_aliases_and_boolean_values() {
    let parsed: SkillMetadataFile = yaml_serde::from_str(
        "products: &products [codex, atlas]\npolicy:\n  allow_implicit_invocation: false\n  products: *products\n",
    )
    .expect("policy with an alias is valid");
    assert_eq!(
        resolve_policy(parsed.policy),
        Some(SkillPolicy {
            allow_implicit_invocation: Some(false),
            products: vec![Product::Codex, Product::Atlas],
        })
    );
}

#[test]
fn metadata_policy_rejects_duplicate_fields_and_legacy_booleans() {
    for text in [
        "policy:\n  allow_implicit_invocation: true\n  allow_implicit_invocation: false\n",
        "policy:\n  allow_implicit_invocation: yes\n",
        "policy: {}\npolicy: {}\n",
    ] {
        assert!(yaml_serde::from_str::<SkillMetadataFile>(text).is_err());
    }
}
