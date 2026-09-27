#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

BRANCH = "codex/context-compiler-full-closure-review-20260927"


def replace_or_present(text: str, old: str, new: str, marker: str, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and marker in text:
        return text
    raise SystemExit(f"{label} drifted: source occurrences={count}")


provider = Path("codex-rs/hepta-context-compiler/src/provider_closure.rs")
text = provider.read_text(encoding="utf-8")
import_line = "    use proptest::prelude::*;\n"
start_marker = "    proptest! {\n"
end_marker = "\n\n    #[test]\n    fn generated_unicode_control_corpus_keeps_exact_escaped_identity()"
replacement = r'''    #[test]
    fn generated_segment_maps_are_total_deterministic_and_single_context() {
        for prefix_len in [0_usize, 1, 2, 17, 255, 2047] {
            for suffix_len in [0_usize, 1, 3, 31, 511, 2047] {
                for seed in [0_u64, 1, 7, 0x55aa, u32::MAX as u64, u64::MAX] {
                    let payload = format!("CTX::{seed:016x}::END").into_bytes();
                    let mut request = vec![b'p'; prefix_len];
                    request.extend_from_slice(&payload);
                    request.extend(std::iter::repeat_n(b's', suffix_len));
                    let first = build_segment_map(
                        &request,
                        &payload,
                        digest("generated-payload"),
                    )
                    .expect("generated map");
                    let second = build_segment_map(
                        &request,
                        &payload,
                        digest("generated-payload"),
                    )
                    .expect("deterministic map");
                    assert_eq!(first, second);
                    assert_eq!(
                        first
                            .iter()
                            .filter(|segment| {
                                segment.kind()
                                    == FinalRequestSegmentKindV2::CanonicalContextBundle
                            })
                            .count(),
                        1
                    );
                    assert_eq!(
                        first.last().expect("last segment").end_offset(),
                        request.len() as u64
                    );
                    assert_eq!(
                        compute_segment_map_digest(&first),
                        compute_segment_map_digest(&second)
                    );
                }
            }
        }
    }

    #[test]
    fn generated_gap_and_overlap_mutations_fail_closed() {
        for prefix_len in [2_usize, 3, 17, 255, 511] {
            for suffix_len in [1_usize, 2, 19, 255, 511] {
                for seed in [0_u32, 1, 7, 0x55aa, u16::MAX as u32, u32::MAX] {
                    let payload = format!("UNIQUE-CONTEXT-{seed:08x}").into_bytes();
                    let mut request = vec![b'a'; prefix_len];
                    request.extend_from_slice(&payload);
                    request.extend(std::iter::repeat_n(b'z', suffix_len));
                    let valid = build_segment_map(
                        &request,
                        &payload,
                        digest("mutation-payload"),
                    )
                    .expect("valid map");
                    let mut gap = valid.clone();
                    gap[0].end_offset -= 1;
                    assert_eq!(
                        validate_segment_coverage(&gap, request.len() as u64),
                        Err(ProviderClosureErrorV2::SegmentCoverageInvalid)
                    );
                    let mut overlap = valid;
                    overlap[1].start_offset -= 1;
                    assert_eq!(
                        validate_segment_coverage(&overlap, request.len() as u64),
                        Err(ProviderClosureErrorV2::SegmentCoverageInvalid)
                    );
                }
            }
        }
    }'''
if import_line in text:
    text = text.replace(import_line, "", 1)
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit("property block markers drifted")
    text = text[:start] + replacement + text[end:]
elif "fn generated_segment_maps_are_total_deterministic_and_single_context()" not in text:
    raise SystemExit("property corpus missing")
provider.write_text(text, encoding="utf-8")


exact = Path("codex-rs/hepta-agentd/src/exact_context_delivery.rs")
text = exact.read_text(encoding="utf-8")
text = replace_or_present(
    text,
    "        let provider_terminal = provider_terminal(terminal.terminal)?;\n",
    "        let provider_terminal = provider_terminal(terminal.terminal.clone())?;\n",
    "provider_terminal(terminal.terminal.clone())?",
    "terminal ownership",
)
old = '''        if !object.contains_key("input") && !object.contains_key("instructions") {
            return Err("provider request has no typed model-input field".to_owned());
        }
        let occurrences = count_context_occurrences(&value, context)?;
        if occurrences != 1 {
            return Err(format!(
                "canonical context must occur in exactly one JSON string, observed {occurrences}"
            ));
        }
        Ok(())
'''
new = '''        let instructions = object
            .get("instructions")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| {
                "provider request instructions must be the typed context field".to_owned()
            })?;
        let instruction_occurrences = instructions.match_indices(context).count();
        if instruction_occurrences != 1 {
            return Err(format!(
                "canonical context must occur exactly once in instructions, observed {instruction_occurrences}"
            ));
        }
        let outside_occurrences = object
            .iter()
            .filter(|(name, _)| name.as_str() != "instructions")
            .try_fold(0_usize, |total, (_, value)| {
                total
                    .checked_add(count_context_occurrences(value, context)?)
                    .ok_or_else(|| "context occurrence count overflow".to_owned())
            })?;
        if outside_occurrences != 0 {
            return Err(format!(
                "canonical context escaped the typed instructions field, observed {outside_occurrences} outside occurrences"
            ));
        }
        Ok(())
'''
text = replace_or_present(
    text,
    old,
    new,
    "canonical context escaped the typed instructions field",
    "typed framing",
)
old = '''    async fn count(&self, request: &[u8]) -> Result<u64, ExactContextDeliveryError> {
        let mut child = Command::new(&self.binary)
'''
new = '''    fn validate_runtime_files(&self) -> Result<(), ExactContextDeliveryError> {
        if hash_bounded_file(&self.binary)? != self.identity.tokenizer_binary_digest()
            || hash_bounded_file(&self.vocabulary)? != self.identity.vocabulary_digest()
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        Ok(())
    }

    async fn count(&self, request: &[u8]) -> Result<u64, ExactContextDeliveryError> {
        self.validate_runtime_files()?;
        let mut child = Command::new(&self.binary)
'''
text = replace_or_present(
    text,
    old,
    new,
    "fn validate_runtime_files(&self)",
    "tokenizer pre-check",
)
old = '''        if !status.success()
            || u64::try_from(output.len()).unwrap_or(u64::MAX) > MAX_TOKENIZER_STDOUT_BYTES
        {
            return Err(ExactContextDeliveryError::TokenizerRejected);
        }
        parse_token_count(&output)
'''
new = '''        if !status.success()
            || u64::try_from(output.len()).unwrap_or(u64::MAX) > MAX_TOKENIZER_STDOUT_BYTES
        {
            return Err(ExactContextDeliveryError::TokenizerRejected);
        }
        self.validate_runtime_files()?;
        parse_token_count(&output)
'''
text = replace_or_present(
    text,
    old,
    new,
    "self.validate_runtime_files()?;\n        parse_token_count(&output)",
    "tokenizer post-check",
)
old = '''        assert!(policy.verify_final_request(&wrong_model, context).is_err());
    }
'''
new = '''        assert!(policy.verify_final_request(&wrong_model, context).is_err());

        let misplaced = serde_json::json!({
            "model": "model",
            "instructions": "ordinary instructions",
            "input": [],
            "metadata": String::from_utf8(context.to_vec()).expect("utf8")
        });
        let misplaced = serde_json::to_vec(&misplaced).expect("request");
        assert!(policy.verify_final_request(&misplaced, context).is_err());

        let non_string = serde_json::json!({
            "model": "model",
            "instructions": [String::from_utf8(context.to_vec()).expect("utf8")],
            "input": []
        });
        let non_string = serde_json::to_vec(&non_string).expect("request");
        assert!(policy.verify_final_request(&non_string, context).is_err());
    }
'''
text = replace_or_present(
    text,
    old,
    new,
    "let misplaced = serde_json::json!",
    "framing tests",
)
old = '''        assert_eq!(
            tokenizer.count(request).await.expect("tokenizer count"),
            u64::try_from(request.len()).expect("length")
        );
    }
}
'''
new = '''        assert_eq!(
            tokenizer.count(request).await.expect("tokenizer count"),
            u64::try_from(request.len()).expect("length")
        );
        std::fs::write(&tokenizer.vocabulary, b"mutated-vocabulary")
            .expect("mutate vocabulary");
        assert_eq!(
            tokenizer.count(request).await,
            Err(ExactContextDeliveryError::TokenizerIdentity)
        );
    }
}
'''
text = replace_or_present(
    text,
    old,
    new,
    "mutated-vocabulary",
    "tokenizer mutation test",
)
exact.write_text(text, encoding="utf-8")


prompt = Path("codex-rs/ext/hepta-prompt/src/lib.rs")
text = prompt.read_text(encoding="utf-8")
old = '''    #[must_use]
    fn has_final_terminal_observer(&self) -> bool {
        self.final_terminal.is_some()
    }
'''
new = '''    #[must_use]
    fn has_final_terminal_observer(&self) -> bool {
        self.final_terminal.is_some()
    }

    #[must_use]
    fn exact_observers_are_paired(&self) -> bool {
        self.final_request.is_some() == self.final_terminal.is_some()
    }
'''
text = replace_or_present(
    text,
    old,
    new,
    "fn exact_observers_are_paired(&self)",
    "observer pair helper",
)
old = '''            if input.request_kind != ModelProviderRequestKind::Turn || !input.generate {
                return Ok(ModelProviderPolicyDecision::Allow {
                    lease: Box::new(PromptRuntimeNoopLease),
                });
            }
            let resolved = self
'''
new = '''            if input.request_kind != ModelProviderRequestKind::Turn || !input.generate {
                return Ok(ModelProviderPolicyDecision::Allow {
                    lease: Box::new(PromptRuntimeNoopLease),
                });
            }
            if !self.host.exact_observers_are_paired() {
                return Err(ModelProviderPolicyError::new(
                    "prompt_runtime_exact_observer_pair_incomplete",
                    "exact request and terminal observers must be installed as one capability",
                ));
            }
            let resolved = self
'''
text = replace_or_present(
    text,
    old,
    new,
    "prompt_runtime_exact_observer_pair_incomplete",
    "observer pre-dispatch check",
)
prompt.write_text(text, encoding="utf-8")

prompt_tests = Path("codex-rs/ext/hepta-prompt/src/lib_tests.rs")
text = prompt_tests.read_text(encoding="utf-8")
if "fn split_exact_observers_are_rejected_before_dispatch()" not in text:
    text += r'''

#[test]
fn split_exact_observers_are_rejected_before_dispatch() {
    let dispatches = Arc::new(StdMutex::new(Vec::new()));
    let records = Arc::new(StdMutex::new(Vec::new()));
    let request_only = host(Arc::clone(&dispatches), Arc::clone(&records))
        .with_final_request_observer(|_request| Box::pin(async { Ok(()) }));
    assert!(!request_only.exact_observers_are_paired());
    let paired = request_only.with_final_terminal_observer(|_terminal| {
        Box::pin(async { Ok(()) })
    });
    assert!(paired.exact_observers_are_paired());
}
'''
prompt_tests.write_text(text, encoding="utf-8")


manifest_path = Path("docs/modules/context.compiler/MODULE_MANIFEST.json")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["integrationBranch"] = BRANCH
for item in (
    "The canonical context bundle occurs exactly once in the provider instructions field and nowhere else in the final request.",
    "Exact request and terminal observers are configured as one capability; split configuration is rejected before provider dispatch.",
):
    if item not in manifest["invariants"]:
        manifest["invariants"].append(item)
test_case = "typed-instructions confinement, tokenizer file mutation, and split observer configuration fail closed"
if test_case not in manifest["testMatrix"]:
    manifest["testMatrix"].append(test_case)
manifest_path.write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

qualification = Path(".github/workflows/context-compiler-qualification.yml")
text = qualification.read_text(encoding="utf-8")
for stale in (
    "codex/context-compiler-provider-closure-final-20260927",
    "context-compiler-v3-full-closure",
):
    text = text.replace(stale, BRANCH)
if BRANCH not in text:
    raise SystemExit("qualification workflow branch drifted")
qualification.write_text(text, encoding="utf-8")
