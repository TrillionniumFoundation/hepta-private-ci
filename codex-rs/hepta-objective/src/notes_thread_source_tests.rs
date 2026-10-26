//! Finite compiler tests only; no production model or Root authority.
use super::*;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveSourceAuthenticationV1;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

#[test]
fn model_tool_source_uses_its_own_profile_and_cannot_masquerade_as_literal() {
    let principal = Digest32::of_bytes(b"explicit fixture principal");
    let operation =
        Digest32::of_bytes(b"explicit fixture operation including original callback run ID");
    let source = thread_notes_source_json_v1(LiteralNotesSourceContext {
        client_intent_id: "original-call-digest",
        source_digest: operation,
        principal_scope_digest: principal,
        locale: "zh-CN",
        observed_at: "2026-09-08T10:00:00Z",
        deadline: "2026-09-08T10:00:05Z",
    })
    .unwrap();
    let source = crate::decode_source_envelope_json_v1(source.as_bytes()).unwrap();
    let profile = thread_notes_admission_profile_json_v1(
        "fixture.notes.scope",
        principal,
        "fixture.notes.issuer",
    )
    .unwrap();
    let profile = crate::decode_admission_profile_json_v1(profile.as_bytes()).unwrap();
    let mut context = ObjectiveAdmissionContextV1 {
        revision: Revision::new(1).unwrap(),
        now_unix_micros: 1_788_861_601_000_000,
        selected_profile_digest: profile.digest().unwrap(),
        source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: StableId::new("fixture.notes.issuer").unwrap(),
            source_digest: operation,
        },
    };
    let admitted = crate::admit_and_compile_objective_v1(&source, &profile, &context).unwrap();
    assert!(admitted.compile_result.is_ok());
    assert_eq!(source.structured_intent.provenance.source_digest, operation);
    let literal = crate::literal_notes_admission_profile_json_v1(
        "fixture.notes.scope",
        principal,
        "fixture.notes.issuer",
    )
    .unwrap();
    let literal = crate::decode_admission_profile_json_v1(literal.as_bytes()).unwrap();
    context.selected_profile_digest = literal.digest().unwrap();
    assert!(crate::admit_and_compile_objective_v1(&source, &literal, &context).is_err());
}
