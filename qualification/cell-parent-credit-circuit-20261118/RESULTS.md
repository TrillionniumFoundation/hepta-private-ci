# E4: actual parent/credit communication on exposed B2

## Result and scope

Neither fixed mixed order exceeds the same two-call strong single-model controls. PP, CC, PC and CP each retain **5/6** successful tasks. The previously observed independent-arm oracle union of 6/6 is not realized by actual interaction. Removing the answer message reduces PC selected success to 4/6; removing measured feedback leaves it at 5/6. All three A-only retrieval controls score 0/6.

This is a predeclared follow-up to the prior E2 errors on **already exposed B2 development tasks**, not new confirmation. All nine arms and both calls were retained. No additional B2 arms or post-result training were run. The original E2 NoUpdate decision is unchanged.

## Fixed candidate and real process

- Execution source: `18de34630fe4b81efaf875c073272b062aeea211`, tree `d6085bbf232c2dbf13d9951d99085add7f9e4b69`, published in Draft PR #6714 before the run.
- Source freeze: `de5e208e429c3944390d5efbd6ab695cbaeca7669203340c4a3107e4f1e6940d`, 555 bound execution-source files.
- P is the previously trained E1 all-actions parent, model `430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786`.
- C is its A-only verified-credit continuation, model `785bc1cea2996e33cfe02c9c51a5a3802c931b010060369fc659b47fde4440a1`.
- Actual loaded normalized FP32 adapter-parameter hashes are P `e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f` and C `549ac578447c41d1ddc975f14468c54eeae12ba431f47bcd1a3da46fbc17ce8f`. These hash normalized tensor names/shapes/values; they are different objects from the SHA256 of `adapter_model.safetensors`. Exact file hashes and bytes are indexed separately in ADAPTERS.json.
- Shared frozen base has 1,543,714,304 parameters; each adapter has 544,768. Recorded active parameters per main call are 1,544,259,072 and resident shared-pool parameters are 1,544,803,840.
- Durable job `1a1ef774693-ffbe-4f9` actually completed with exit 0, durable complete logs, no timeout or automatic retry. Owned child exit SHA256 is `1b86d69f0125290898b77f13773f2d98d39bf54d6d7a1611a77816819945c981`; COMPLETE is `88171852d4da90af8a1c4d063c671c25407840e40f669b130e440f4ae52a9668`.

Original model manifests, training sources and admission schemas were preserved. Every active adapter was checked against actual loaded parameters. Both cold-versus-pool A calibration pairs matched answer, output token IDs, model, generation and rendered-prompt identities. P and C share a lineage and differ in training history; they are not independent teachers and their lifetime training costs are not claimed equal.

## All nine arms

Each row uses exactly 12 fresh model calls and 12 verifier calls, two of each per task. Calls continue after first success. Selected means the frozen rule “earliest business success, otherwise last”; last measures the final output even when it regresses.

| Arm | First | Last | Selected | Recovered | Regressed | Input / output tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| PP | 4/6 | 2/6 | 5/6 | 1 | 3 | 5264 / 531 |
| CC | 4/6 | 3/6 | 5/6 | 1 | 2 | 5259 / 502 |
| PC | 4/6 | 3/6 | 5/6 | 1 | 2 | 5264 / 504 |
| CP | 4/6 | 3/6 | 5/6 | 1 | 2 | 5259 / 520 |
| PC_no_answer | 4/6 | 4/6 | 4/6 | 0 | 0 | 5039 / 403 |
| PC_no_feedback | 4/6 | 3/6 | 5/6 | 1 | 2 | 4911 / 508 |
| PP_retrieval | 0/6 | 0/6 | 0/6 | 0 | 0 | 9420 / 765 |
| CC_retrieval | 0/6 | 0/6 | 0/6 | 0 | 0 | 9350 / 690 |
| PC_retrieval | 0/6 | 0/6 | 0/6 | 0 | 0 | 9420 / 758 |

The cap is 4096 input tokens, 384 generated tokens and two model/verifier opportunities per task. Answer/feedback relay is capped at 2048 bytes; the same selected A retrieval reference is capped at 4096 bytes. Actual token counts differ, so this is matching of opportunities and caps, with measured consumption, not equality of actual compute.

## What the raw pairs show

For `is_same_domain`, PP, CC, PC and CP all repair the same initial incomplete test by adding a negative-domain assertion. The single-model controls therefore explain this recovery. PC without an answer message fails this repair.

For `escape_leading_slashes`, C alone starts with a valid `subject(...)` assertion. In PC, C instead repeats P's invalid use of the original function name; both attempts are rejected by the unchanged literal-input task contract. CP preserves the successful C output, but it cannot repair C's `first_true` failure.

For `first_true`, P's initial `subject([True, False, True]) == 1` passes the two declared controls because Python equates `True` and `1`. PC retains that first success but its second call adds a wrong expected value and fails. CP copies C's initial incorrect list expectation and then includes disallowed nonliteral arguments. This is narrow control-based success, not evidence of broad semantic mastery.

The fixed lexical retriever selects the same unrelated A-counter reference for all six B2 questions. 36/36 retained retrieval outputs contain its counter key. The retrieval arms were included before any current result and remain fully reported. This is a limited existing-A baseline; it does not represent the strongest possible external retrieval system.

## Complete measured cost

There are **108 main + 4 A-calibration model calls = 112**, and **108 main + 4 calibration + 6 A-reference verifier calls = 118**. Main calls consume 59,186 input and 5,181 output tokens; calibration adds 1,128 input and 164 output tokens. Total generation is **60,314 input / 5,345 output tokens**. No output hits its generation cap.

Main verification records 87 actual business executions and 21 format rejections; calibration adds four business executions and reference preparation adds six. All rejected attempts retain their paid model calls and raw outputs.

The owned wall window is **541.191474 seconds**. Waited child CPU is **514.769474 user + 21.592976 system seconds**; owner CPU is separately recorded. Main generation totals 380.165023 seconds, calibration generation 11.843868 seconds, and the three verifier scopes total 18.921268 seconds. Those timings nest inside the owner window and must not be summed into another total.

Setup includes two cold base loads and one shared-pool base load; adapters load twice cold and twice into the pool. Cold setup wall is 51.253507 seconds and shared-pool initialization is 30.875898 seconds; these scopes are also nested. Energy, currency and complete system cost are unknown. The GPU's nominal power limit is not measured energy.

## Audit and retained failures

The read-only audit recomputed all 108 original request/output/STEP/verifier bindings, output-token lengths, active parameter hashes, original/negative-control observations, relay ablations, fixed call order, per-arm costs and selected/last transitions. It separately checks the four calibrations and six reference checks. No model generation or verifier execution occurs during the audit.

Main and reference verification bind source `64fcc25e4ccf82f31c2549f5d4c1a5c4af1831c5bed4219c0aac2283b213a020`. A calibration intentionally uses the predeclared retained provider core `ee37e28567944ab542a21926f66957cf663c0ec7e7ceab62a4c30da5fce4282b`. Two read-only audit attempts initially assumed the wrong mapping of these source paths; both failures and source versions are retained, followed by the source-bound successful audit. No original receipt or score was changed.

A first deployment was rejected by the clean-worktree gate because a tool-created sidecar existed in the preparation tree. It made **zero model calls**. The sidecar and failure were preserved, and the published execution source was materialized into a separate clean worktree. Preflight fixture/materialization and formatter failures also remain in the archive.

Readout SHA256: `d60e05f9522e13763868a2fbeb8a21a6c8063e3dcc2cfde8e5b807805df787b0`.
Successful audit source SHA256: `0362835567b5ee110d2d16bea4b154a1e48cd23b2f8211d802adf65f67d433dd`.
Per-task raw-pair readout: TASKS.json; full receipt index: EVIDENCE_INDEX.json.

## Qualification limits

The six tasks come from three public projects and have possible pretraining overlap. They are not authenticated-user sources. Each checks one extracted function under a restricted test contract and two wrong-output controls; it is not whole-repository integration. The software pool is a research executor, not native HIA or an adopted owner Circuit. This result grants no adoption, FinalUse or settlement eligibility.

The archive retains all original run receipts, wire messages, setup outcomes, complete source freeze, both actual adapter files and supporting source/manifest bytes. Large base-model weights and the external Python distribution remain referenced by their original immutable manifests; the archive is not a standalone replacement for that runtime.
