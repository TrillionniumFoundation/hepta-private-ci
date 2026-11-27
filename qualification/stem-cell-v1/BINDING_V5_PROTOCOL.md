# V5: full binding fit before feedback or compute control

This experiment follows V4's failure to learn the complete controlled training
set. It changes training while preserving the frozen Granite Encoder, cached
token representation and 38,466-parameter TokenReader. It does not claim a new
reasoning architecture, NDU benefit, multimodal transfer or a production result.
Hosted CI is outside this run. All neural phases run sequentially on CPU FP32.

## Frozen material and roles

The Encoder is `ibm-granite/granite-embedding-97m-multilingual-r2`, revision
`835ad14087e140460703cf0fae09f97d469d65c2` (97,441,152 frozen parameters).
V4 runtime files and the old cache remain byte-identical. V5 records both the
training parameter digest and the differently defined typed execution digest;
these names must never be compared as interchangeable hashes.

Only the official MultiRC training JSONL is read. The prior V4 design determines
64 Reader training paragraphs (3,909 candidates) and 16 internal-tune paragraphs
(827 candidates). Their bytes, source groups and row order are checked. This
internal tune is reported separately; it is not fresh evidence or a hard opening
gate. No official validation JSONL is read or rescored.

`binding_protocol.py` independently checks the controlled grammar and truth:

| Role | Groups / candidates | Admissible use |
| --- | --- | --- |
| reader_train | 32 / 128 | Full-fit gate, replay, training diagnostics |
| internal_tune | 16 / 64 | Previously exposed controlled regression |
| verifier_fit | 32 / 128 | Reserved and unused: no fitting, encoding or scoring |
| fresh_combinations | 32 / 128 | New fact combinations using old vocabulary |
| fresh_vocabulary | 32 / 128 | New people and objects |

Each group contains both candidates in two equal-word-count evidence worlds.
Swapping ownership changes truth. Duplicate rejection uses semantic facts rather
than sentence order; the two fresh roles are disjoint from prior controlled
material and each other. Worlds and annotations select training losses and
minibatches; inference receives only six public feature/mask tensors.

## Training, frozen before execution

All Reader seeds are 41, 47 and 53. The architecture and initial parameter count
remain fixed. Adam uses learning rate .001 and `foreach=False`; all phases use
depth three and last-hop supervision. There is no evidence-attention loss.

Warmup batches contain four complete groups (16 candidates). A seeded stream
shuffles all groups without replacement each epoch. The loss is final-hop CE
plus .5 times a softplus margin on the two worlds of the same question/candidate.
Run at most 8,000 updates per seed, diagnose the full 128 training candidates
every 250 updates, and select the earliest diagnostic with 100% candidate and
paired-world accuracy and CE <= .10. A 1,800-second call budget also applies.
All three seeds are attempted; every one must pass to open continuation.

Each seed's continuation starts from its same frozen warmup:

| Arm | Natural updates | Binding updates | Binding pair weight |
| --- | ---: | ---: | ---: |
| natural_only | 500 | 0 | 0 |
| replay | 500 | 500 | 0 |
| contrastive | 500 | 500 | .5 |

Natural cases, targets, source identities and sampled row order match across all
arms. Binding samples match between replay and contrastive. These arms have
different actual compute. Diagnostics occur every 100 updates, without early
stopping or selecting checkpoints. Natural anchors are the first eight complete
training question groups. Internal natural-tune outcomes are descriptive.

Contrastive retention must reach >=95% candidate and paired-world accuracy,
with at most five percentage points lost from warmup, in every seed. Failure
closes feedback and fresh evaluation; another arm cannot silently replace it.

## Trained revision and causal controls

If the Core passes, reuse each seed's original V4 independent, frozen,
natural-only verifier. Check its old artifact selection, weight bytes, both
named digests and source disjointness. Its historical training is identified as
reused, not charged as newly performed work. It has not learned controlled truth
and its predictions are not semantic certificates.

Real-feedback and zero-feedback models start from the same contrastive Core.
Both consume the same 256 natural and 256 binding updates. Unroll three Reader
steps with two detached verifier observations: class probabilities, agreement
with the current proposal, and evidence-present status. Train on actual
on-policy correct and incorrect proposals; do not force errors. Require nonzero
gradients in real feedback columns and zero gradients for the zero arm.

Post-training ordinary-forward diagnostics are explicitly named
`core-without-feedback`; they do not measure closed-loop revision. Actual fresh
revision controls execute `real`, `zero`, within-batch public-ID `shuffle`,
`reset`, `late_fusion`, and `verifier_only`, all with three Reader and two
verifier steps. Additional `cheap_fixed1` and `cheap_verifier` measure their
smaller actual call budgets. Record initial-to-final corrections and damage.

Only after all opening gates pass and all 18 model manifests are frozen may the
two fresh domains be encoded and evaluated once. The manifest binds training
receipts and opening evidence. Fresh Core controls include depth one, state
reset and evidence deletion. Repeated seeds reuse the same groups: they do not
create new independent examples. Independent units number 32 groups per domain.

## Costs, audit and invocation

`binding_process.py` records each child's startup-to-exit CPU, wall time, peak
RSS, exit status and log SHA, including unsuccessful attempts. Inner phase,
update, diagnostic and physical-batch costs are nested breakdowns, never added
again to the whole process. Shuffle preparation is inside its measured scope.
Cache generation from V4 is historical; restore costs are current. Incremental
fresh encoding is reported separately. Complete formula FLOPs are unavailable.

Run `binding_campaign.py prepare`, then `warmup`, `continue`, `feedback`, and
`evaluate`, with `--source`, `--snapshot`, `--prepared`, `--previous-main`,
`--previous-native`, and a new `--output` directory. Wrap each invocation with
`binding_process.py --receipt PATH --log PATH -- PYTHON binding_campaign.py ...`.
The orchestrator refuses closed gates, changed runtime/input bytes, modified
selected artifacts and repeat fresh evaluation. Preserve failed receipts and
logs; do not retry or relax gates under the same frozen experiment identity.

`binding_review.py` is a separate stdlib auditor: it recomputes truth, raw
`p > .5` decisions, CE, paired scores, sampling plans and admitted costs. Its
index must enumerate every claimed audited artifact. It checks weight-file
bytes and provenance; it explicitly does not independently decode tensor
digests or attest the hardware clock. Report that scope alongside results.
