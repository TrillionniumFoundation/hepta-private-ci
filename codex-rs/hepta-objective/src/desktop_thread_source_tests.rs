//! Authority-free compiler contracts; these are not a Root or model receipt.
use super::*;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveSourceAuthenticationV1;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

#[test]
fn both_desktop_actions_require_the_new_profile_and_keep_one_effect_budget() {
    let principal = Digest32::of_bytes(b"explicit fixture principal");
    let operation = Digest32::of_bytes(b"explicit original operation binding fixture");
    let profile = desktop_thread_admission_profile_json_v1(
        "fixture.desktop.scope",
        principal,
        "fixture.desktop.issuer",
    )
    .unwrap();
    let profile = crate::decode_admission_profile_json_v1(profile.as_bytes()).unwrap();
    let legacy = crate::thread_notes_admission_profile_json_v1(
        "fixture.desktop.scope",
        principal,
        "fixture.desktop.issuer",
    )
    .unwrap();
    let legacy = crate::decode_admission_profile_json_v1(legacy.as_bytes()).unwrap();
    let mut context = ObjectiveAdmissionContextV1 {
        revision: Revision::new(1).unwrap(),
        now_unix_micros: 1_788_861_601_000_000,
        selected_profile_digest: profile.digest().unwrap(),
        source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: StableId::new("fixture.desktop.issuer").unwrap(),
            source_digest: operation,
        },
    };
    let mut intents = Vec::new();
    for (action, action_name) in [
        (DesktopThreadAction::NotesReplace, "notes.replace"),
        (
            DesktopThreadAction::CalculatorEvaluate,
            "calculator.evaluate",
        ),
    ] {
        let raw = desktop_thread_source_json_v1(
            action,
            DesktopThreadSourceContext {
                original_call_id: "original-call-digest",
                source_digest: operation,
                principal_scope_digest: principal,
                locale: "zh-CN",
                observed_at: "2026-09-08T10:00:00Z",
                deadline: "2026-09-08T10:00:05Z",
            },
        )
        .unwrap();
        let value: serde_json::Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(
            value["structuredIntent"]["legalActionClasses"],
            json!([action_name])
        );
        assert_eq!(
            value["structuredIntent"]["resources"]["externalEffectCount"],
            1
        );
        assert_eq!(value["structuredIntent"]["resources"]["networkBytes"], 0);
        let source = crate::decode_source_envelope_json_v1(raw.as_bytes()).unwrap();
        context.selected_profile_digest = profile.digest().unwrap();
        assert!(
            crate::admit_and_compile_objective_v1(&source, &profile, &context)
                .unwrap()
                .compile_result
                .is_ok()
        );
        context.selected_profile_digest = legacy.digest().unwrap();
        assert!(crate::admit_and_compile_objective_v1(&source, &legacy, &context).is_err());
        intents.push(crate::canonical_objective_intent_digest_v1(&source).unwrap());
    }
    assert_ne!(intents[0], intents[1]);
}

#[test]
fn desktop_source_refuses_missing_original_operation_binding() {
    assert!(
        desktop_thread_source_json_v1(
            DesktopThreadAction::CalculatorEvaluate,
            DesktopThreadSourceContext {
                original_call_id: "original-call-digest",
                source_digest: Digest32::ZERO,
                principal_scope_digest: Digest32::of_bytes(b"fixture principal"),
                locale: "en-US",
                observed_at: "2026-09-08T10:00:00Z",
                deadline: "2026-09-08T10:00:05Z",
            },
        )
        .is_err()
    );
}
