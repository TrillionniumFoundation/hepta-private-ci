# E4: fixed parent / verified-credit interaction on exposed B2

## Scope fixed before the new calls

This follows the existing E4 Circuit experiment. B2 was already evaluated in E2.
It is an exposed development mechanism panel here, not a new confirmation set.
No training, additional source/user identities, native owner adoption, learned
routing, or settlement eligibility are claimed.

The independently reconstructed E2 B2 results gave selected success 5/6 for both
the parent and verified-credit update. Their failures differ: the parent used
the original function name instead of subject on escape_leading_slashes, while
the update produced a list-valued expectation for first_true. Their observed
oracle union is 6/6. This motivates the study; it is not evidence that real
communication can attain that union. Parent first_true passed the existing two
controls with Python's True == 1 semantics. The tasks and limited controls are
unchanged.

Prior independent audit SHA256:
afdf9eb3bd3816a815b6f63d732ce8fbc6578565f5340019b0a70a981cb9521e.

## Cells and source custody

- P: the E1 all_actions parent,
  430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786.
  Actual normalized FP32 adapter parameter hash:
  e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f.
- C: the E2 verified_credit update,
  785bc1cea2996e33cfe02c9c51a5a3802c931b010060369fc659b47fde4440a1.
  Actual normalized FP32 adapter parameter hash:
  549ac578447c41d1ddc975f14468c54eeae12ba431f47bcd1a3da46fbc17ce8f.

C denotes the verified-credit student in this study, not the older controlled
correction secondary adapter. These are related policies from one base model,
not independently licensed teachers. The parent and new update have different
training histories; inference-budget controls do not imply equal lifetime cost.

The pool retains the original parent matched schema and current-credit schema.
It verifies the unchanged E1 training source, original E2 candidate files and A
data, both completed training receipts, adapter file inventories, and the actual
FP32 tensors after load and each activation. It does not rewrite manifests or
pretend that this new orchestration source trained either model. The E2
current_credit.py loader is imported only after its manifest identity and file
hash match the frozen original.

The existing cold/pool calibration uses the first fixed A record. Both policies
produce one cold and one pool answer. All four answers and their verifier
receipts are retained. Actual cold parameter hashes, exact generated token IDs,
answers, rendered prompts and model identities must agree with the pool before
any B2 dispatch. A mismatch is retained as a failure with no automatic retry.

## Fixed arms and execution order

All six B2 records, in their published order, run these nine arms in this order:

| Arm | First call | Second call | Intervention |
| --- | --- | --- | --- |
| PP | P | P | Native current-answer and tool feedback |
| CC | C | C | Native current-answer and tool feedback |
| PC | P | C | Native current-answer and tool feedback |
| CP | C | P | Native current-answer and tool feedback |
| PC_no_answer | P | C | Remove first answer from second-call context |
| PC_no_feedback | P | C | Remove first verifier feedback from second-call context |
| PP_retrieval | P | P | Same fixed A-only retrieval rule |
| CC_retrieval | C | C | Same fixed A-only retrieval rule |
| PC_retrieval | P | C | Same fixed A-only retrieval rule |

Every arm makes both calls even when the first succeeds. There is no
task-specific route, result-based arm selection, new training or replay of a
prior model output as the current answer. Tool calls execute the newly generated
patch against the unchanged repo_patch v1 function contract and controls.

The retrieval rule is the pre-existing integer Jaccard overlap on task input
terms, tied by frozen A-record digest. Each task receives the same A reference
in PP_retrieval, CC_retrieval and PC_retrieval. It sees six previously authorized
A references and no B2 gold answers or prior B2 output. This limited reference
baseline is not a claim to the strongest possible external retrieval system.

## Budget and outcomes

- 108 main model calls and 108 main verifier calls: 9 arms x 6 tasks x 2.
- 4 additional A calibration model calls and 4 calibration verifier calls.
- 6 additional original A-reference verifier calls required by the unchanged
  retrieval preparation. Total: 112 model calls and 118 verifier calls.
- Every model call retains the existing 4096 input-token admission and
  384 output-token cap. Relay budget remains 2048 bytes; a retrieval reference
  remains bounded by 4096 bytes without truncation.
- The pool loads one base and two adapters; cold calibration loads two additional
  bases and two adapters. Load costs are shared scopes, not added per call.
- Primary comparisons report first success, last success, selected success,
  recovery and regression for all nine arms. Selected success uses the retained
  verifier result from either attempt, matching both strong single-policy
  baselines.
- Report actual input/output tokens, verifier executions versus format
  rejections, process wait/CPU/wall receipts and model load/activation counts.
  Energy and currency remain unknown unless measured. Equal caps and calls do
  not imply identical realized compute or physical cost.

B2 identity remains the original published commitment and reveal:
records SHA256 26b2e625c649a73a991c681bb1949cdaf91b995d8e4bc3402b924495797d42cb;
panel source commit 1134793c60c1b9908eaf6e388f753860ee8917c4.
The original E2 NoUpdate results and the B2 disclosure chronology are unchanged.
