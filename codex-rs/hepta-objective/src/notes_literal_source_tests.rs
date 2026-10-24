//! Pure compiler regressions. Authentication below is an explicit test fixture;
//! these tests establish no production authority, model result or document effect.

use super::*;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveSourceAuthenticationV1;
use crate::admit_and_compile_objective_v1;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn source(client: &str, operation: Digest32) -> Result<String, String> {
    literal_notes_source_json_v1(LiteralNotesSourceContext {
        client_intent_id: client,
        source_digest: operation,
        principal_scope_digest: Digest32::of_bytes(b"test Notes principal"),
        locale: "zh-CN",
        observed_at: "2026-09-08T10:00:00Z",
        deadline: "2026-09-08T10:00:05Z",
    })
}

#[test]
fn literal_notes_source_binds_original_operation_and_uses_real_admission() {
    let operation = Digest32::of_bytes(b"explicit original-operation test digest");
    let encoded = source("note-1", operation).unwrap();
    let decoded = decode_source_envelope_json_v1(encoded.as_bytes()).unwrap();
    let profile = literal_notes_admission_profile_json_v1(
        "test.notes.principal",
        Digest32::of_bytes(b"test Notes principal"),
        "test.notes.issuer",
    )
    .unwrap();
    let profile = decode_admission_profile_json_v1(profile.as_bytes()).unwrap();
    let mut context = ObjectiveAdmissionContextV1 {
        revision: Revision::new(1).unwrap(),
        now_unix_micros: 1_788_861_601_000_000,
        selected_profile_digest: profile.digest().unwrap(),
        source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: StableId::new("test.notes.issuer").unwrap(),
            source_digest: operation,
        },
    };
    let admitted = admit_and_compile_objective_v1(&decoded, &profile, &context).unwrap();
    assert!(admitted.compile_result.is_ok());
    assert_eq!(decoded.structured_intent.provenance.source_digest, operation);

    // Reusing authentication for a different original operation cannot admit
    // the source whose payload/predecessor digest was changed.
    let changed = source("note-1", Digest32::of_bytes(b"different operation")).unwrap();
    let changed = decode_source_envelope_json_v1(changed.as_bytes()).unwrap();
    assert_ne!(
        canonical_objective_intent_digest_v1(&decoded).unwrap(),
        canonical_objective_intent_digest_v1(&changed).unwrap()
    );
    assert!(admit_and_compile_objective_v1(&changed, &profile, &context).is_err());

    context.now_unix_micros += 6_000_000;
    assert!(admit_and_compile_objective_v1(&decoded, &profile, &context).is_err());
}

#[test]
fn literal_notes_source_refuses_invalid_navigation_and_unbound_inputs() {
    let operation = Digest32::of_bytes(b"test operation");
    for client in ["", "../../other", "x\ny", "not allowed"] {
        assert!(source(client, operation).is_err());
    }
    assert!(source(&"x".repeat(97), operation).is_err());
    assert!(source("note-1", Digest32::ZERO).is_err());
    assert!(literal_notes_admission_profile_json_v1(
        "test.notes.principal",
        Digest32::ZERO,
        "test.notes.issuer"
    )
    .is_err());
}
