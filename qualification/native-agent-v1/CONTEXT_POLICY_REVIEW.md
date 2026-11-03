# Native context policy v3 review

This is the P0 review of newly injected host fragments and requested model output, not a tokenizer qualification receipt.

## Frozen bounds

| Material | Bound and enforcement | Evidence scope |
| --- | --- | --- |
| Native `instructions` | At most 8,192 bytes after JSON serialization, checked before model admission | Includes JSON escaping and quotes |
| `system` / `developer` items | At most 8,192 serialized bytes for the entire item; the role check precedes the generic `message` type | Cannot inherit the 64 KiB original-message allowance |
| Tool definitions, calls, and presented results | 8,192 serialized-byte cap; function-call types take priority over any extra provider role | Full output evidence remains under its original runtime owner; presentation does not replace it |
| Requested generated output | Integer from 1 through 8,192 in `max_output_tokens` | Provider token semantics and provider compliance are external contracts; this is not a local count |
| Original user and provider message text | Existing request-derived cap, at most 65,536 serialized bytes per retained item | Bytes are not token counts; long Chinese UI and append-only original history remain intact |

The complete policy binding records the version, all byte caps, actual requested output tokens, the maximum requested tokens, storage budget, and `tokenizer_validation: not_performed`. The request excerpt policy retains its prior version because its transformation is unchanged.

The 8 KiB host/tool allowance can exceed 1,000 tokens. Those classes therefore remain explicitly identified for the AGENTS P0 manual review. This change closes the enlargement of host instructions and system/developer items; it does not assert that arbitrary original user/provider text satisfies the separate 10K-token-per-item rule. AGENTS does not explicitly exempt original text from that rule. A strict proof for every request item requires a tokenizer bound to the actual model, or a separately reviewed, frozen request-only lossless segmentation policy. No byte-to-token conversion is invented here.

The production canonical renderer in `hepta-agentd/src/native_context_binding.rs` already checks each original selected material at 8 KiB and then checks the entire serialized `NativeInputMessageV1` at 8 KiB, with a 48 KiB aggregate ceiling. This includes the untrusted evidence encoded with a user role: its trust warning, source/content digests, and escaped content are all inside that final per-item check. Trusted material uses the developer role. The original compiler selection and source/content digests are checked before rendering. Thus the existing production initial-context path does not gain the larger original-user allowance merely by using a user role; no renderer limit is widened by this patch.

## Original-operation compatibility

The policy version changes from `hepta-native-context-policy-v2` to `hepta-native-context-policy-v3`. Product recovery compares the entire original configuration digest before provider observation or settlement. Qualification sessions compare their full frozen manifest policy. Older or mismatched pending state is retained unchanged and cannot be reopened for fresh execution under v3. Read-only original status/evidence inspection is separate; no original request body, operation identifier, provider response identifier, tool intent, or idempotency key is migrated. This patch does not implement an old-policy execution engine.

## Verification

Native regressions reject an oversized instruction, a typed system/developer message, and output requests above 8,192 before admission or HTTP. They preserve a long Chinese user/assistant pair byte-for-byte, including the unchanged owner history. A provider function call carrying an extra user/assistant role still cannot exceed the tool cap: the response stays under its original pending model operation across same-response GET, and no tool is queued or executed. Existing streamed long-Chinese settlement and same-response GET recovery tests remain relevant. The runner recovery regression verifies both an absent old policy and the exact v2 binding remain incompatible with v3 while the original request, operation, manifest, and saved snapshots stay unchanged. Existing production recovery tests check unchanged writer/checkpoint state and no new GET/POST on a mismatched full configuration.

Local source review is not a Rust compilation result. Report the host's actual scoped test receipts separately.
