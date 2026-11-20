# Original E6 task retirement and NoUpdate read-limit evidence

This is a preserved failed end-to-end experiment, with successful component controls. The executable source was `e4aeaa2cdd1a4aa884d09cafaeef96968feb7a90`, tree `05c36cd26f6dfbd1a8fb0e0cfe275755fef80c86`. No native/model work was rerun to create this archive.

## Product change and exact outcomes

The actual submit/resume effect helper drains the original active generation only after its trusted business outcome has become Complete. It verifies the drained publication and checks that the task status remains unchanged. Retained/status paths remain read-only. The predecessor-witness gate remains unchanged.

| Scope | Exact result |
| --- | --- |
| Full source gates on b5da8e703986918f5bcd5c7c5c8287dc2838e8a4 | 275 source tests, 893 protected rows, 282 targeted boundary checks, and original 1,138-boundary CLI passed |
| First native attempt on b5da | Compilation exit 101 due to ambiguous assert_eq in new test modules; zero native cases; parent never started |
| e4ae change from b5da | Exactly two explicit pretty_assertions::assert_eq imports; all other 15,734 tracked files byte-identical |
| Two-library compile on e4ae | Actual compiler/list exit 0; recorder rejected a binary-name/binary-id spelling assumption. Its failed original is retained and an independent readback corrects metadata without rerunning compilation |
| Original native cases on e4ae | 11 passed, no failed/error/skipped cases |
| Retirement and fault controls on e4ae | 16 passed, no failed/error/skipped cases |
| Actual original NoUpdate parent on e4ae | Failed: historical read request 65 exceeded the unchanged maximum 64 |
| New C / Adopt / cold D / FinalUse / settlement | No successful qualification |

The full caller CLI was not rerun on e4ae. Its passing result belongs to b5da; the exact two-import source delta, current protected-row sweep, blob policy and actual native results are separate evidence.

The current parent no longer reports the earlier missing predecessor witness. Physical original A data contains a 93-byte journal and 224-byte witness, compared with the prior header-only 40/112-byte state. This demonstrates the actual drain effect in that parent. C has a zero-byte journal and 112-byte initial witness, so this is not a C success receipt.

The first failure is retained in the original daemon log and JUnit:

```text
daemon_stage=historical.trace.request request_id=65 maximum=64 purpose=runtime.learning.historical-task-read.v1
daemon_stage=historical_client.read_limit request_id=65 maximum=64
```

The first-error propagation path then reports the original publication owner unavailable; later delivery closure and CommitUncertain remain in the raw log. No scorer, 64-read budget, 500 ms frame, authority window, independent-B contract or original parent body was relaxed.

## Evidence and reassembly

The archive retains 201 original files / 55,918,596 bytes. Its exact compressed bytes are split into five parts of 480,000 / 480,000 / 480,000 / 480,000 / 256,776 bytes. Every published blob remains below the existing 512,000-byte limit; no allowed path or threshold is expanded.

Archive SHA-256: `84f474d4f9699d3e9bc538dab820beb5e21d61d9da700007fa5b59465665cabc`.

Run `python3 reassemble.py` in this directory. It checks every part, the full archive, and every included original against the retained manifest before writing the reassembled archive. It does not execute tests, reconstruct results, or extract files automatically.

Raw originals include source gate failures and successes, compile failures and metadata correction, exact protocols/runners, native and parent XML/logs, inventories, runtime/binary invariance checks, original terminal archives and physical journal/witness bytes. The original host files are retained unchanged. Compiled/cache files excluded from the portable archive are named in MANIFEST.json.

Only five selected non-key physical files are copied into the archive: A journal/witness and C journal/witness/target. The broader physical inventory contains metadata only. EXCLUDED_KEY_METADATA.json explicitly lists unconfirmed key/authority paths retained on the host; no key body was read for this publication or added to the archive. It does not claim those keys are production or test keys.

## Timing and limits

The 11-case command took 1.616680337 s and its owner 3.535677076 s. The 16-case command took 11.040714024 s and its owner 11.807528335 s. The original NoUpdate command took 70.808666 s; its enclosing owner took 121.382146 s. Compile/list, failed compile, full source gate, helper/product/library preparation and test execution are separately retained; enclosing intervals overlap and must not be added as independent costs.

Chain work had completed before the e4ae parent. Small status/RESULT/metadata RPCs occurred during the measured parent. Complete whole-system CPU, memory, energy, network and provider-charge totals are not claimed.

The prior first-cause evidence and oversized-blob rejection remain in parent history. This archive does not revise those originals. The Adopt CURRENT 240-second versus old writer 300-second authority conflict is still unresolved. No merge or production activation occurred.
