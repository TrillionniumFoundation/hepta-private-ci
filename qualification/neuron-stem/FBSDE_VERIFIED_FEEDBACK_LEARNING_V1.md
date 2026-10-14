# Local verification feedback changes a shared Head's ranking

Parent: `6fc2cd3c46621e620acb18cd3b853966be2bccbe`, Draft PR #1550.
The parallel input-tied and novelty-calibration work is retained, not imported
again. The same entrypoint gains `verified_feedback_learning_v1`. Existing
solvers, controls, workflows, budgets and native owners remain unchanged.

## Change in learned mechanism

Temperature/uniform smoothing cannot change a member's preferred participant
pair. Here a shared residual adds `w*x+b` to the existing participant logits:
129 parameters for 128 frozen lexical features, reused across all three base
Heads and every event. This is not another Encoder. The old 6,219 Head weights
remain immutable; three independent candidate paths are evaluated: residual
(129 trainable), full three-Head fine-tuning (6,219), and a standalone linear
Head (129). All use exactly the same 54 labelled source operations, 160 AdamW
steps, lr=.01 and original fit CPU ceiling. Standalone linear output is replicated
only to use the same probability interface, not claimed as three independent Heads.

All original predictions on the feedback population are written and closed before
simulated verification labels are exposed to fitting. The population is a fixed
quota, including already-correct examples, not cherry-picked errors or simulated
production-selected logs. Each label is bound to the source and prior prediction.
This is simulator provenance/consistency, not an owner-signed production receipt,
OS data isolation, independent observer, future chronology or live deployment.

Feedback has five familiar plus four previously explored repair frames (54 unique
sentences); 18 different sentences in three other frames select temperatures and
constant smoothing. Six further frames generate 144 evaluation stories; known
frames generate 60 replay stories. No test score changes training, candidate
selection, temperature, cost or horizon. Known replay overlaps feedback frames and
is not independent retention qualification. The held-out stories reuse only 36
sentences and have no IID-case confidence claim. Semantics and final decoder are
still a closed grammar with an exact source verifier; no general language score.

## Strong controls and original-budget execution

The twelve arms retain the frozen baseline, same-calibration scalar temperature
and smoothing, residual with zero/one/two-step planning, full fine-tuning and
standalone linear controls with zero/two-step planning, verify-all and the cheap
exact reverse algorithm. Each uses the same input-tied probability workspace.
The two-step horizon is a TOTAL verification budget and single-step planning can
replan within that same budget. Correct/incorrect/abstain utility is +1/-1/0,
with .02 per requested verification. A check is revealed only after action choice.
The 100ms process-CPU proposal/planner ceilings and 20,000-node limit are unchanged.
No Riccati residual is repurposed as a semantic truth or risk certificate.

All candidate predictions and every state's action are sealed before final label
scoring. Immutable canonical-byte buffers retain failed attempts and partial
outputs without keeping large nested graphs alive. Model/state JSON permits an
independent scalar forward recomputation without importing Torch or the runtime
planner. The original world-based auditor checks source roles, conditional choices,
verification observations, posterior laws, decoded text, parameters and cost sums.
Hashes and arithmetic do not authenticate execution or make calibration valid.

## First complete local observation (lexical reference, NOT pretrained)

On 144 held-out stories: frozen/no-check 84 correct/135 answered; calibrated
frozen NDU 136/142 with 182 checks; shared residual no-check 102/117; residual
myopic 132/135 with 105 checks; residual two-step 140/143 with 121 checks;
full-finetuned NDU 128/144 with 91 checks; standalone linear NDU 138/142 with
182 checks; verify-all and exact reverse 144/144. Exact reverse needs no neural
proposal. Two-step improves this residual's finite task score, but buys 16 more
checks than myopic; its controller CPU is higher. Modelled check costs are NOT
hardware prices. Exact reverse still wins overall within this declared grammar.

Unanimous event-level mistakes on held-out sentences: frozen 432/648 exposures
(24 distinct strings), residual 108 (6 strings), full fine-tune 216 (12), linear
324 (18). These are correlated exposures, not 648 independent observations.
All non-verify-all policies retain 60/60 known replay without checks. This is a
promising local feedback mechanism, not confirmed risk/lifecycle superiority.

Preparation, shared encoding/proposals, fit, probability construction, selection,
recording and audit CPU are separately visible or included in the total measured
envelope. Shared comparisons do not allocate complete standalone costs. Original
base training is imported, not repeated or made free. No wall-latency, energy,
independent future qualification or production promotion follows.

Run using an original byte-bound lexical `input_tied_challenge_v1` artifact:

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile verified_feedback_learning_v1 --evidence-dir /fixed/source \
  --output /new/output
```

A separate read-only source-head/merge workflow constructs that source and runs
this profile. Any failed source run remains failure; it is not silently replaced.
Full-repository/native Rust and physical pretrained qualification remain separate.
