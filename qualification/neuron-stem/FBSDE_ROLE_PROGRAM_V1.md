# Verified role programs: change the candidate explanations, not only the depth gate

Parent `c53587f9a5fe3b7a1577bf9bf5a64e81b47e12dd`, Draft #1550.
The existing entry gains `verified_role_program_v1`. Every old study, exact
algorithm, CPU limit and production owner remains unchanged. No weights are fit.

## Diagnosis and mathematical object

In the three previously shared participant-exclusion errors, all six orders of
exactly two verifications still give an incorrect terminal MAP answer under the
old belief. This is a post-score diagnosis, not an oracle available to a policy.
It does not exclude earlier stopping or different explanations. Changing only
which two instructions are checked cannot repair these exact-two continuations.

The new candidate set comprises three programs per EXACT name-normalized frame:
omit its first, second or third mention-role, and exchange the other two actors.
Actor tokens are alpha-renamed by first occurrence; a sole unmentioned actor fills
the remaining coordinate. All other words, negations, punctuation and event order
remain intact. Equal embeddings do not merge inputs. A distinct frame has a distinct
latent program. The family explicitly assumes a single unconditional two-person
exchange among three actors with frame-invariant role semantics. It is NOT a
learned general parser, causal sufficiency proof, or coverage of arbitrary language.

For frame g, let R_g be the omitted role and e_i(R_g) its actor-pair emission at
event i. The prior is product_g w_g(R_g). Source feedback updates this JOINT law:

    posterior(R | revealed history) proportional to
        product_g w_g(R_g) * product_(i,o) 1[e_i(R_group(i)) == o].

An observation may therefore update other name permutations of the same frame.
Repeated consistent observations do not multiply new independent likelihoods;
contradictions reject. The complete sequential permutation is still applied to
each candidate world. No event/state is skipped merely because a rule is shared.
Three distinct actors make the role-to-pair emission invertible, so one genuine
verification identifies that frame's program within this declared family.

Two priors are compared: an arithmetic pool of the frozen Head probabilities
mapped into program coordinates, and a uniform program prior. Pooling predictions
is NOT independent evidence or a calibrated epistemic distribution. The uniform
prior does not need the neural Head. Both retain the same three possible programs.
A resampled-per-event ablation has the SAME initial event marginals as the pooled
program model, but discards the shared rule. A cheap uniform-probe control checks
the first unresolved frame until support agrees or two checks are exhausted; it
abstains if still ambiguous. It needs neither a neural gate nor optimal planning.

The original bounded Bellman/finite-BSDE planner is reused for one/two-step choices.
All selected truths enter through reveal(event) AFTER action choice. The original
100ms process CPU, 20,000-node and two-verification limits remain. At most 8,192
worlds are admitted before materialization. Setup and immutable record writing
are measured separately, not free or a part of a native source-authority contract.
The uniform-probe support statement is conditional on family coverage, NOT a
semantic correctness certificate. Frame-invariant semantics can fail outside this
experiment; one checked instance cannot authenticate invariance in real language.

## Frozen data and actual results

The old complete outcome artifact supplies frozen three base Heads, the residual,
calibration and known tasks. These bytes are audited before use. Eight new frames
were specified before the first evaluation, without filtering errors/disagreement.
They produce 192 stories with one to three frames per story and 48 raw instruction
strings. The 192 signed-gain stories are a DIAGNOSTIC REPLAY; 60 familiar stories
are separate retention REPLAYS. None are independent human or future observations.

The first complete run used eleven controls. Inspection identified the missing
uniform-one-step ablation; it was added as a twelfth control without changing
frames, beliefs, budgets, labels, probabilities or any of the first 4,884 outputs.
This addition is transparent post-inspection analysis, not a fresh confirmation.
The final run has 444 stories x 12 arms = 5,328 outputs and 1,998 shared lexical
proposals. Scoring occurs after the output buffers close; chronology is logical,
not OS-isolated or independently authenticated.

| New-frame method | Correct / answered of 192 | Checks | Controller CPU seconds |
| --- | ---: | ---: | ---: |
| Original one-step | 162 / 192 | 92 | .065348524 |
| Original two-step | 162 / 192 | 92 | .116701704 |
| Head-prior role programs, two-step | 167 / 192 | 70 | .045043471 |
| Uniform role programs, one-step | 144 / 144 | 92 | .043165436 |
| Uniform role programs, two-step | 185 / 185 | 174 | .072588473 |
| Cheap first-frame uniform probe | 181 / 181 | 196 | .021173757 |
| Exact reverse | 192 / 192 | 0 | .008323053 |

Two-step uniform uses two actual checks on 41 requests; it obtains 41 additional
correct answers relative to the SAME-prior one-step policy. Compared with the
cheap probe it answers four additional cases with 22 fewer checks, but consumes
more controller CPU. Exact reverse remains better and cheaper. The Head-prior
still makes 25 errors: expanded hypotheses do not repair a misleading prior when
it declines verification. Zero observed errors in an arm is not a risk bound.
On the old diagnostic replay, program one/two get 192/192 with 48 checks, including
all three old errors; the original one/two remain 189/192 with 94 checks. All
methods retain 60/60 familiar answers, except uniform variants may pay checks.

Costs retain .02 per verification and .002 per requested two-step root, including
roots that stop early. These are utility proxies, not CPU prices. Source auditing,
shared proposals, hypothesis building and record/audit overhead remain in the
outer envelope; per-arm independent deployment attribution is incomplete. No
stable latency or full-lifecycle superiority, new pretrained forward, independent
risk qualification, general FBSDE/Riccati improvement or production admission.

Reproduce with the original study entry and complete prior outcome evidence:

    python fbsde_study.py --profile verified_role_program_v1 \
      --evidence-dir /fixed/outcome-study --output /new/role-study

The independent auditor uses forward world permutations and separate source
rendering, not the runtime backward-holder implementation. It checks the original
source, semantic logits, program priors, selected revelations, scoped identities,
all answers and measured totals. A unit-audit mismatch at exactly zero utility
was fixed BEFORE the first scoring run by reproducing specified normalized
log-mass arithmetic, not by loosening ties or altering a policy. The initial test
failure is retained. All final-head/merge qualification remains separate.
