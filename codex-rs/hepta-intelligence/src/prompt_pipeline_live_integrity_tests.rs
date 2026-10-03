//! Consumer batch fixture: real admission, selection, compilation and preparation.
use super::*;
use crate::prompt_delivery::tests::admitted_registry_at_index;
use crate::prompt_delivery::tests::canonical_selection_with_maximum;

#[cfg(target_os = "linux")]
fn read_accounting() -> (u64, u64) {
    let text = std::fs::read_to_string("/proc/self/io")
        .unwrap_or_else(|error| panic!("read own I/O accounting: {error}"));
    let count = text
        .lines()
        .find_map(|line| line.strip_prefix("rchar: "))
        .unwrap_or_else(|| panic!("rchar counter"))
        .parse()
        .unwrap_or_else(|error| panic!("rchar: {error}"));
    (count, text.len() as u64)
}

#[test]
fn sixteen_selected_payloads_revalidate_once_per_boundary_and_reject_later_corruption() {
    // Isolate actual process I/O accounting even when cargo runs other tests
    // concurrently. The child executes exactly this one registered fixture.
    #[cfg(target_os = "linux")]
    if std::env::var_os("HEPTA_PROMPT_BATCH_FIXTURE_CHILD").is_none() {
        let output = std::process::Command::new(std::env::current_exe().unwrap_or_else(|error| panic!("test executable: {error}")))
            .args(["prompt_pipeline::live_integrity_tests::sixteen_selected_payloads_revalidate_once_per_boundary_and_reject_later_corruption", "--exact", "--nocapture", "--test-threads=1"])
            .env("HEPTA_PROMPT_BATCH_FIXTURE_CHILD", "1").output()
            .unwrap_or_else(|error| panic!("isolated fixture: {error}"));
        eprint!(
            "{}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.status.success(), "isolated fixture failed");
        return;
    }
    let temp = tempfile::tempdir().unwrap_or_else(|error| panic!("fixture: {error}"));
    let root = temp.path().join("registry");
    let mut last = None;
    for index in 0..16 {
        drop(last.take());
        last = Some(admitted_registry_at_index(
            &root,
            &vec![b'A' + index; 64 * 1024],
            /*token_cost*/ 4,
            index,
        ));
    }
    let (registry, tuple, _authority, _key, _) = last.unwrap_or_else(|| panic!("fixture"));
    let selected = canonical_selection_with_maximum(
        &registry,
        &tuple,
        /*now*/ 100,
        /*maximum_candidates*/ 16,
        (0..16)
            .map(|index| {
                StableId::new(if index == 0 {
                    "factor:verify".to_owned()
                } else {
                    format!("factor:verify:{index}")
                })
                .unwrap_or_else(|error| panic!("ID: {error}"))
            })
            .collect(),
    );
    assert_eq!(selected.portfolio.selected.len(), 16);
    let manifest_path = root.join("registry.json");
    let payload_path = root.join("registry.payloads");
    let manifest =
        std::fs::read(&manifest_path).unwrap_or_else(|error| panic!("manifest: {error}"));
    let payload = std::fs::read(&payload_path).unwrap_or_else(|error| panic!("payload: {error}"));
    let request = PromptContextCompileRequestV1 {
        exercise: selected.exercise_request.clone(),
        compilation_id: StableId::new("compile:batch")
            .unwrap_or_else(|error| panic!("ID: {error}")),
        model_profile: ContextModelProfileV2 {
            model_digest: tuple.model_digest,
            provider_id_digest: Digest32::of_bytes(b"provider"),
            provider_model_digest: tuple.model_digest,
            tokenizer_digest: tuple.tokenizer_digest,
            serializer_digest: Digest32::of_bytes(b"serializer"),
            template_digest: tuple.template_digest,
            tool_schema_digest: tuple.tool_schema_digest,
            maximum_context_tokens: 4096,
        },
        token_budget: 128,
        truncation_policy_digest: Digest32::of_bytes(b"truncation"),
        base_candidates: vec![],
        mandatory_groups: vec![],
    };
    eprintln!("PREG_BATCH_BEGIN compile");
    #[cfg(target_os = "linux")]
    let before = read_accounting();
    let started = std::time::Instant::now();
    let prepared = compile_exercised_prompt_context_v1(&registry, &selected.portfolio, request)
        .unwrap_or_else(|error| panic!("compile: {error}"));
    eprintln!(
        "PREG_BATCH_END compile total_us={}",
        started.elapsed().as_micros()
    );
    #[cfg(target_os = "linux")]
    {
        let observed = read_accounting().0 - before.0 - before.1;
        eprintln!("PREG_BATCH_READ compile bytes={observed}");
        assert_eq!(observed, (manifest.len() + payload.len()) as u64);
    }
    assert_eq!(prepared.compiled.receipt().selected_item_ids().len(), 16);
    let serialized_payload = prepared
        .compiled
        .receipt()
        .selected_item_ids()
        .iter()
        .flat_map(|id| {
            prepared
                .materialization
                .payloads
                .iter()
                .find(|item| &item.binding.realization_id == id)
                .unwrap_or_else(|| panic!("selected item"))
                .payload
                .iter()
                .copied()
        })
        .collect::<Vec<_>>();
    let request = PromptDeliveryPrepareRequestV1 {
        exercise: selected.exercise_request,
        serialization_id: StableId::new("serialize:batch")
            .unwrap_or_else(|error| panic!("ID: {error}")),
        attachment_id: StableId::new("attach:batch").unwrap_or_else(|error| panic!("ID: {error}")),
        serialized_payload,
    };
    eprintln!("PREG_BATCH_BEGIN prepare");
    #[cfg(target_os = "linux")]
    let before = read_accounting();
    let started = std::time::Instant::now();
    let delivered =
        prepare_prompt_delivery_v1(&registry, &selected.portfolio, &prepared, request.clone())
            .unwrap_or_else(|error| panic!("prepare: {error}"));
    eprintln!(
        "PREG_BATCH_END prepare total_us={}",
        started.elapsed().as_micros()
    );
    #[cfg(target_os = "linux")]
    {
        let observed = read_accounting().0 - before.0 - before.1;
        eprintln!("PREG_BATCH_READ prepare bytes={observed}");
        assert_eq!(observed, (manifest.len() + payload.len()) as u64);
    }
    assert_eq!(delivered.materialization, prepared.materialization);
    assert_eq!(
        std::fs::read(&manifest_path).unwrap_or_else(|error| panic!("manifest: {error}")),
        manifest
    );
    assert_eq!(
        std::fs::read(&payload_path).unwrap_or_else(|error| panic!("payload: {error}")),
        payload
    );
    let mut corrupt = payload.clone();
    corrupt[64] ^= 1;
    std::fs::write(&payload_path, &corrupt).unwrap_or_else(|error| panic!("fault: {error}"));
    assert!(matches!(
        prepare_prompt_delivery_v1(&registry, &selected.portfolio, &prepared, request.clone()),
        Err(PromptPipelineErrorV1::Registry(_))
    ));
    assert!(registry.requires_reopen());
    std::fs::write(&payload_path, &payload)
        .unwrap_or_else(|error| panic!("restore fixture: {error}"));
    assert!(matches!(
        prepare_prompt_delivery_v1(&registry, &selected.portfolio, &prepared, request),
        Err(PromptPipelineErrorV1::Registry(_))
    ));
    eprintln!(
        "PREG_BATCH_INPUT selected=16 manifest_bytes={} payload_bytes={}",
        manifest.len(),
        payload.len()
    );
}
