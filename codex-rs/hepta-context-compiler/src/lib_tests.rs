use super::*;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn item(name: &str, role: ContextRole, tokens: u64) -> ContextItem {
    ContextItem {
        item_id: id(name),
        role,
        content_digest: Digest32::of_bytes(name.as_bytes()),
        source_digest: Digest32::of_bytes(b"source"),
        token_count: tokens,
        contains_secret: false,
    }
}

fn request(items: Vec<ContextItem>) -> CompilationRequest {
    CompilationRequest {
        compilation_id: id("compile:1"),
        run_snapshot_digest: Digest32::of_bytes(b"snapshot"),
        objective_digest: Digest32::of_bytes(b"objective"),
        token_budget: 10,
        items,
    }
}

#[test]
fn evidence_never_becomes_instruction() {
    let Ok(receipt) = compile(request(vec![
        item("evidence:1", ContextRole::UntrustedEvidence, 2),
        item("instruction:1", ContextRole::TrustedInstruction, 2),
    ])) else {
        panic!("compilation must succeed");
    };
    assert_eq!(receipt.trusted_instruction_ids, vec![id("instruction:1")]);
    assert_eq!(receipt.untrusted_evidence_ids, vec![id("evidence:1")]);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn secret_bearing_item_is_rejected() {
    let mut value = item("secret:1", ContextRole::UntrustedEvidence, 1);
    value.contains_secret = true;
    assert_eq!(
        compile(request(vec![value])),
        Err(Error::SecretRejected("secret:1".to_string()))
    );
}

#[test]
fn optional_evidence_omission_is_explicit() {
    let Ok(receipt) = compile(request(vec![
        item("evidence:a", ContextRole::UntrustedEvidence, 8),
        item("evidence:b", ContextRole::UntrustedEvidence, 8),
    ])) else {
        panic!("compilation must succeed");
    };
    assert_eq!(receipt.used_tokens, 8);
    assert_eq!(receipt.omitted_ids, vec![id("evidence:b")]);
}

#[test]
fn legacy_compile_cannot_omit_trusted_instructions() {
    assert_eq!(
        compile(request(vec![
            item("instruction:a", ContextRole::TrustedInstruction, 8),
            item("instruction:b", ContextRole::TrustedInstruction, 8),
        ])),
        Err(Error::InsufficientContext {
            required_tokens: 16,
            token_budget: 10
        }),
    );
}

#[test]
fn oversized_required_cost_reports_the_exact_insufficient_floor() {
    assert_eq!(
        compile(request(vec![
            item("instruction:a", ContextRole::TrustedInstruction, u64::MAX),
            item("instruction:b", ContextRole::TrustedInstruction, u64::MAX),
        ])),
        Err(Error::InsufficientContext {
            required_tokens: 2 * u128::from(u64::MAX),
            token_budget: 10,
        }),
    );
}

#[test]
fn duplicate_item_is_rejected() {
    let value = item("item:1", ContextRole::UntrustedEvidence, 1);
    assert_eq!(
        compile(request(vec![value.clone(), value])),
        Err(Error::DuplicateItem("item:1".to_string()))
    );
}
