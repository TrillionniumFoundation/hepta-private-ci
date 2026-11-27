# F/L/R generations and A/B/C/D evidence

This extends the EVOLVE-1 and S5 execution-identity work at
`4d5ffd79302da50ca2de87ec203905f7b4683de6` (#5411). It is a research
supervisor and executable CPU reference, with no native adoption authority.
Historical EVOLVE-1 and Cell-127 negative results remain unchanged.

## Claims and controls

| Arm | Mutable components                            | Frozen components                                                    |
| --- | --------------------------------------------- | -------------------------------------------------------------------- |
| F   | Execution context permitted by the experiment | Model and learner                                                    |
| L   | Model parameters                              | Learner and candidate-selection rule                                 |
| R   | Model and a versioned learner candidate       | Evaluation, source partitions, budgets, stopping and selection rules |

Every arm starts with the same model and learner. The common plan freezes
information opportunities, all generation source lists, candidate and learner
trial limits, cumulative B-query limits, and total resource ceilings. Different
arms may consume different amounts within the same ceiling; unused F resources
are not fabricated costs. R's internal discovery is charged to R.

The reference learns a distribution over eight replay-ratio/learning-rate
policies using eight actual 16-step fits on A-only data. Ordinary candidates
receive 64 SGD steps of batch size 32. L retains its initial uniform proposal
distribution. R's update algorithm is fixed; only the actual distribution and
its inherited parent artifact change. This is a bounded learner-adaptation
experiment, not evidence of an open-ended self-rewriting algorithm.

L minus F measures the descriptive benefit of this reference's parameter
updates. R minus L measures a different descriptive contrast. R minus L alone
cannot identify a better improver: use the existing EVOLVE-1 same-solver
I0/I1 component-transfer experiment with independently formed improvers,
fresh sources and complete costs before making that claim.

## Data and causal order

- **A:** registered training experience. Every model and learner trial binds the
  scheduled A sources and actual predecessor model/learner.
- **B:** candidate selection. Every successful candidate has exactly one
  registered B query. A retry is a separately registered attempt. The cumulative
  query budget includes unsuccessful and unresolved attempts.
- **C:** subsequent reference use. Selection is retained before cold-loading
  the selected model and learner from content-addressed files and scoring the
  scheduled future sample. The real daemon ordinary entry is a separate gate.
- **D:** final audit. The complete search is sealed before opening D. The D
  reader first replays the original B/selection/C prefix and requires all
  generations of all three arms to be complete. Empty, substituted-plan and
  incomplete self-signed seals do not permit a data read.

Every evaluation original binds the full plan digest. B also binds its original
attempt and operation. Selection binds both the full candidate list and the
learner-search list, so removing a failed search cannot preserve its selection
receipt. Changed source bytes, budgets or code pins invalidate old originals.

Within a campaign, run, attempt, learner-trial and operation identities cannot
be reused to grow the evidence count. C/D sample bytes cannot be repeated.
Source groups and content digests cannot cross roles. Source-balanced means
give one weight to each declared original group; more seeds or template
variants do not establish more independent groups. These declarations do not
authenticate real provenance, so verified independent real sources remain zero.

Missing B, selection, C, a predecessor, or an unresolved search leaves the
affected chain `UNAVAILABLE`. An authenticated complete negative decision can
be `NO_UPDATE`; an unverified retained-model declaration cannot. All planned
rounds stay in the denominator. D results cannot be fed back into this campaign:
the horizon and seal are fixed, and the runner performs no training after D.

## Durability, budgets and missing meters

Trial and candidate registrations are saved before dispatch; B access is
reserved before B is read. Every round settles its disjoint wall/CPU envelope
on success and failure. Interruptions retain an incomplete journal. New runs
refuse an existing output directory; automatic resume is not implemented.

The inherited twelve-stage cost ledger retains failed work, internal learner
search, training, evaluation, readback and bookkeeping. Shared preparation and
publication receive a full standalone charge in every benefitting arm; summing
those standalone totals would double-count shared work. Admission is checked
between finite CPU operations. It is not an OS-enforced hard quota.

Energy and provider charges are unmeasured. Imports and final publication need
external metering; their cost cell remains unknown. No complete amortized net
benefit, zero missing cost or economic superiority is inferred. GPU/token
campaigns require a separately reviewed resource profile.

The reference retains actual D bytes before execution to pin their identity,
then reads them through the seal gate only at the end. The producer and evaluator
still share one process and filesystem. The gate proves the tested protocol
order, not independent external custody or protection against arbitrary local
code. Local content verification is not native owner authentication.

## Reproduction and interpretation

```bash
python -m unittest -v scripts.ndu_real_runtime.test_causal_ace \
  scripts.ndu_real_runtime.test_evolve1 scripts.ndu_real_runtime.test_evolve1_pilot \
  scripts.ndu_real_runtime.test_flr_contract scripts.ndu_real_runtime.test_flr_reference
python -m scripts.ndu_real_runtime.flr_reference \
  --output /absolute/path/to/new-run \
  --source-commit "$(git rev-parse HEAD)" --source-tree "$(git rev-parse HEAD^{tree})" \
  --generations 3 --seed 41 --attempts 3
```

The generated plan, originals, model and learner artifacts, input bytes, ledger,
seal and report are retained together. `DESCRIPTIVE_PROTOCOL_COMPLETE` means
this bounded recorded reference sequence was resolved. All scientific efficacy,
RSI, independent-custody and production-adoption flags remain false.

## Native dependency observed separately

At #6118 `62ef235c8c871f256891fe6a053c9f5ee7919c8b`, the real original
experience intake exists, but `main.rs` still calls `startup.receive()`.
The intake binds the NDU snapshot profile; #6006's full-RunStart Q24 Dataset
projection is incompatible. Existing records must not be relabeled to join them.
Original training/observer/selector capabilities, independent B and D custody,
ordinary C consumption, and complete daemon plus Root cold recovery must be
supplied and qualified on one common candidate before production claims.
