# Independent per-row bounds contract/preflight review

Base #3616 c8a2014750e2c3a59c0966873fbfe0d8084a598c. Read actual research_task_head_owner.rs and its tests plus Cargo manifests. No source changes or builds by reviewer.

Current owner has global header64KiB/inventory4MiB/request32MiB/row-count bounds, but deserializes full inventory/request with serde_json::from_slice before per-row validation. RowBinding and RequestRow are strict typed/deny_unknown_fields. score_json validates all admitted rows before forwarding; tests require forward_entries=0 on invalid later rows. The proposed256KiB raw-object bound is additional input admission, not a production authority feature.

A narrowly scoped allocation-light lexical preflight before the corresponding serde deserialization is reasonable and avoids a serde_json raw_value feature/dependency-lock/Bazel expansion. It must operate on original bytes rather than decoded strings, values serialized again, or line lengths. Exact row-object span should include both braces and internal UTF-8 bytes, escapes, spaces and linebreaks. Whitespace between array members is outside the object span unless explicitly specified otherwise; whole-input limits still cover it. Request rows include both binding and features, while inventory rows are the binding objects themselves.

Critical implementation/test requirements:
- Only direct members of the root rows array are candidates; nested decoy rows properties and braces/brackets inside strings must not change structural depth.
- Root keys may be JSON escaped (e.g. r\u006fws); serde accepts these as rows. A literal byte-string-only match would bypass the intended preflight. Decode or compare escaped field names safely, retaining grammar validation by serde.
- Quote and backslash parity, nested arrays/objects, multiple row objects and duplicate rows keys must be handled. Do not let a later duplicate root key hide an oversized earlier row; serde must still reject duplicate fields after preflight when below limits.
- Scanner should not replace the strict serde syntax/type/missing/null/unknown-field checks. Valid under-limit payload semantics and raw-byte pins remain identical. Oversized malformed input may receive Bounds before Encoding if this priority is intentionally documented; small malformed input should still be serde Encoding.
- Inclusive exactly256KiB vs one-byte-over regression, multibyte UTF-8, escaped keys, quoted delimiters, late oversized row before any forwarding, inventory and request coverage, and whole-input protections should be exercised through the real owner.

The owner's existing bytes/pins compare exact original inputs; do not canonicalize/hash rewritten JSON or trust request-supplied pins. Existing missing-modalities/null prediction behavior and research deny-all authority flags must remain. Tests through a harness should import the exact owner source and real hepta-neuron/infer-core/types implementations, not stub forward or parse validation; a passing harness is bounded owner integration evidence, not full agentd startup/Runtime/FinalUse acceptance.

The inspected related native-task-head replay and pool scripts also use256KiB request-row bounds, but those line-based formats include newlines and are not automatically identical to a batch-JSON object-span definition. Final documentation must bind this specific owner's new object-span limit precisely. Full scanner/source diff remains pending for independent review.
