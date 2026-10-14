# Calibration coverage without claiming semantic repair

Parent #1550: `77741c44ecb031f92dc4893292795045f0b334bf`. That parent
already landed the preserved input-tied challenge; do not import it twice.
This additive study uses the SAME existing entrypoint and existing finite
input-tied BSDE planner. Old workflows, priors, CPU/node/check limits, reviewers
and production owners are unchanged.

## Frozen model and information boundary

Load the byte- and tensor-bound three tiny Heads from an existing
`input_tied_challenge_v1` artifact. Verify the original training identity; no
pretrained forward or further base-Head updates occur. Six additional scalar
weights learn alpha(x), and each participant-pair law is replaced by

    q'(pair|x,m) = (1-alpha(x))*q(pair|x,m) + alpha(x)/3.

Alpha sees training-only unigram/bigram support, mean-distribution entropy,
confidence and ensemble disagreement. It sees neither the correct participant
pair nor a source-interpreter result at inference. Repeated inputs share the
same latent interpretation through InputTiedBelief. Alpha is a fitted smoothing
mass, NOT a calibrated probability that an answer is wrong. For alpha<1 this
operation preserves each member's pair ranking: it cannot learn new semantics.

## Explicit calibration, controls and task scope

A separate 54-unique-sentence simulator set (five familiar and four new frames)
fits six weights with 160 Adam steps, lr=.05. All individual-source strings have
equal weight; those strings/families are not authenticated independent samples.
Exactly the same data selects the one-temperature and constant-alpha controls.
No new test result selects the gate, temperature, constant, cost or horizon.

Test: four DIFFERENT actor-normalized sentence frames, 96 generated stories.
Known-frame replay: 60 stories. The known frames also occur in calibration, so
this is NOT an independent retention qualification. Inputs contain watchers,
exclusion or exchange wording. Their semantics and the exact source verifier are
explicit closed-grammar task knowledge, not unrestricted language understanding.
The 96 test stories reuse only 24 event strings; no IID case confidence interval
or general distribution-shift guarantee is claimed. The original six-family
challenge is not reused as the new test. All choices were fixed before its first
output. Generic uncertainty-under-shift motivation: Ovadia et al. (2019),
arXiv:1906.02530; temperature control: Guo et al. (2017), arXiv:1706.04599.

All ten controls remain, including no checks, one-step/two-step verification,
constant smoothing, uniform-prior planning, verify-all and cheap exact reverse.
Verification is source-side revelation after choice, not free evidence to the
planner. The parser already reads the story; modelled check cost .02 is not a
physical parsing price. Both planner and proposal CPU limits remain 100ms.

## First observed result; no selection from the final test

Frozen base NDU: 65/96 correct, zero checks. Temperature 1.0, constant alpha=.25,
novelty myopic and novelty NDU: 91/96 correct, 126 checks each. Uniform planning
answers 87 correctly and abstains on nine; exact reverse is 96/96 without neural
work. Thus calibration coverage triggers useful checking but there is NO unique
six-parameter or two-step benefit. On known-frame replay, conditional smoothing
and temperature retain 60/60 without checks; constant smoothing makes 79 checks.
The simpler temperature control already matches that behaviour.

All 1560 outputs are sealed before final scoring. The independent arithmetic
reader imports no model, planner or belief class; it recomputes source/conditional
laws, controls, decisions, decoded text and costs using the earlier independent
world reference. These hashes and checks are consistency, not execution authority.
Imported base training costs and common inference are not fully attributed per
arm. Component CPU and study envelopes do not grant lifecycle superiority.

Run `fbsde_study.py --profile novelty_calibration_v1 --evidence-dir /frozen/base
--output /new/result`. The source must be the original lexical Head study, never
an opaque pretrained substitution. CI first generates that source through the
unchanged baseline, then runs this separate profile and retains failures. Keep
Draft; no risk, independent retention, future outcome or production admission.
