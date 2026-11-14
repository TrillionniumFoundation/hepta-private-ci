# P0: source-bound terminal-evidence supervision for Hepta Group reasoning

Date: 2026-10-15. **RESEARCH ONLY / DRAFT / SHADOW / DENY_ALL**.
Frozen parent: `research/group-evidence-utility-gates-20261015@e9a5c160dac58e1ec8d18ce106f1fc0c0567eeb2`.

## Failure mode addressed

The prior `fit_model` recurrent Group training charges final-answer cross-entropy
at **every** intermediate step. For a dependency, constraint or temporal source,
the sampled recurrent depth may end before the TRAIN teacher's last required
evidence operation. Therefore the model is rewarded for guessing an answer
before its supervised evidence chain is complete. Intermediate attention
coverage alone does not remove this objective inconsistency.

This change is an optional training intervention, **not a claim that learned
recurrence executes logical operations**.

## Exact intervention

1. `group_terminal_evidence.py` converts the original complete TRAIN-only
   per-operation token masks into an immutable Boolean `[case, depth]` tensor.
   A case is eligible only at and after its last nonempty operation slot.
   Coalesced operations are retained. Cases with no evidence are rejected.
2. `fit_model(..., terminal_guard=True)` replaces final-answer CE at each
   recurrent step with guarded log-softmax/gather CE; incomplete examples have
   exactly zero **terminal-label gradient**. Independent per-operation attention
   supervision continues; no extra model parameters or decoder are introduced.
   An empty eligible subset is a legal zero-label-loss step.
3. The original `fit_model` default is unchanged. Control arms and their
   initial tensors, minibatch membership, sampled depths and training schedule
   remain the documented comparison point. The guarded intervention is applied
   only to the attention-trained Core when the campaign opts in.
4. `group_attention_campaign.py --terminal-guard` binds the new policy in the
   immutable protocol and reports actual admitted/suppressed step-example counts,
   mask digest, mask bytes, parameter counts, training work, RNG schedule digest,
   and frozen model identity. It does **not** run the teacher at inference.
5. `group_terminal_receipt_review.py`, invoked by the existing independent
   standard-library campaign reviewer, reconstructs the exact Boolean tensor
   from the source-bound TRAIN operation slots. It independently replays the
   fixed Python `random.Random(seed)` sample/depth sequence and rejects
   mismatched count, SHA-256, byte length, cohort order, batch size and sampler.
   This is **source-consistency replay**, not independent proof of physical
   learning, original model execution or externally observed utility.

The training profile avoids unreduced NLL: the frozen strict ATen work formula
only admits mean-reduced NLL. The guarded CE uses log-softmax, gather, multiply,
sum and divide, all covered by the existing eager CPU arithmetic profile.

## Run and compare

```bash
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest \
  test_group_terminal_evidence test_group_terminal_receipt_review \
  test_group_training_attention -v

# Requires an independently acquired, approved real Granite97 snapshot.
python3 qualification/stem-cell-v1/group_attention_campaign.py \
  --snapshot /approved/granite97 --output /sealed/prefix-guard-41 \
  --seed 41 --training-profile sgd_v1 --terminal-guard

python3 -S qualification/stem-cell-v1/group_attention_campaign_review.py \
  /sealed/prefix-guard-41 \
  --output /sealed/prefix-guard-41/independent-review.json

# Frozen legacy training policy (without --terminal-guard):
python3 qualification/stem-cell-v1/group_attention_campaign.py \
  --snapshot /approved/granite97 --output /sealed/legacy-41 \
  --seed 41 --training-profile sgd_v1
```

Run multiple seeds and both registered optimizer profiles before comparing
correct complete answers, source-group rescues/harm, missing-evidence refusals,
long chains, composition, original no-change, CPU/wall/RSS, and all training,
teacher and shared Encoder costs. A same-seed but separate-host or different
full-work budget is **not** a matched-compute causal result.

## Observed local facts, not inferred successes

- Exact local original-byte Git blobs for the new helper and its 7-test module:
  `70ef77e9dfa166f50c81d16c63abe5c8e50dc9d2`,
  `f81ccec1a63461891780e5a9b029e62d87cafc35`.
- Exact local original-byte Git blobs for the stdlib reviewer and its 3-test module:
  `37aac6fcc438233559445c9bfa0ccfb635ed147f`,
  `2e2901e3d30539068d76251d0804b81699e243cf`.
- Python Torch 2.10.0+cpu: **10/10 local mechanism/replay tests passed**
  in normal Python and **10/10 passed** under `python -O`; new files also
  passed local `py_compile`. The guard gradient, completed-case CE parity,
  forged source, mismatched counter and frozen sampler denials ran.
- A local TorchDispatchMode traced the guarded CE forward/backward. The trace
  contained log-softmax/gather/scatter-add and **no unreduced NLL**.
- Existing full repository / actual pretrained campaign / newly authored
  `test_group_training_attention.py` integration tests are **not claimed
  passing** in the isolated authoring environment. No new actual natural-task
  F1/EM, 4096 Cell resource gain, NDU positive utility or production promotion
  has been observed. Earlier negative real Granite results remain binding.

## Remaining scientific blockers

- Even when final-label gradients are masked, the Core sees the full frozen
  input token matrix. A supervised attention slot is not proof that intermediate
  dependency or constraint operations were executed.
- TRAIN verifier callbacks may disclose candidate correctness as status. The
  intervention does not remove this training-only oracle-feedback channel.
  An independent no-verifier and feedback-masked factorial study is required.
- No source-group-independent future natural-task improvement, old-task
  retention, strict lifecycle-cost frontier, global neural FBSDE solution,
  multimodal generation or inference-time autonomous Cell split is established.
- Production Neuron V1/Q24, NDU owner, CNS/Control, Worker/FinalUse,
  authorization, CAS/WAL, revocation and effects remain unchanged.
  `production_promotion_permitted=false`; **DENY_ALL**.
