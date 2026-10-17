# Actual 1.7B Reader cancellation: source-bound negative evidence

This is an **actual inference-prefix** review, not a successful completion of
the preregistered whole-census capability comparison and not a new test on the
current audit commit. The model was cancelled while generating.

- Original generating commit: `5c9acdb340975adc2d16927fdb744023bd973bd8`
- Workflow: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39007522955
- 1.7B cancelled artifact ID: `12095845236`
- Original artifact ZIP SHA256:
  `f08896887e79b64c4cbba605ac65cbbc775aaf24afb9f03eb461e1ad4c9bb618`
- 135M complete artifact ID: `12093476084`, archive digest
  `07bb823e3b54b175689c0c1440930164260a76bfd43a7451ef23eb6f07714197`
- Original 1.7B raw journal SHA256:
  `e6fec2f158124e2c364b1cf2614bdaf0fc8f8ebc0df49c3e3f68a55f15e9c130`
- Frozen common reviewed plan SHA256:
  `940c2783f5d5bab438828461bdc12d09ea6c2c76307fbc59c84276cdf9c98b92`
- Reader repository: `HuggingFaceTB/SmolLM2-1.7B-Instruct`, fixed revision
  `31b70e2e869a7173562077fd711b654946d38674`
- Original frozen external gold label SHA256:
  `5973e13de088b5973d045db543444ab1050dfe3ede2b843c84642781dfd6232e`

## What really happened

| Scope | Value |
| --- | ---: |
| Original planned question/condition calls | 98 |
| Durably journaled original **prefix** | 16 |
| Successful 1.7B inferences in prefix | 16 |
| Unexecuted planned 1.7B conditions | 82 |
| Matching frozen 135M source-byte comparisons | 16 |
| Mean diagnostic token-F1 delta on observed prefix (1.7B minus 135M) | +0.05782967 |
| Full 98-call diagnostic delta lower bound | -0.82729312 |
| Full 98-call diagnostic delta upper bound | +0.84617627 |
| Total observed 1.7B inference seconds | 5,191.65 |
| Median observed seconds per completed call | 325.70 |
| Literal `[E...]` citation markers in 16 1.7B answers | 0 |

The bounds above are **missing-outcome bounds**, not 95% statistical intervals.
The 16 originally executed calls are a **non-random leading prefix** of two
question blocks, not 16 independent questions or 16 source families.

The complete 135M source and cancelled 1.7B raw evidence have matching original
source lists for these 16 pairs; the full common frozen eight-question plan
hash is unchanged across the two models. The cancelled run was not assigned a
score by the original generation workflow: the separate read-only reviewer
computes diagnostic token-F1 using the original pinned labels **after**
verifying the raw journal. It does not rewrite a single model answer.

The run consumed approximately 86.5 minutes of actual model inference for
16 calls. A purely conditional extrapolation of the remaining 82 calls at
the observed mean is roughly 7.39 **additional** CPU-hours, not a measurement
of their future execution or a runtime guarantee. Repeating a monolithic
90-minute CPU job cannot close the 98-call matrix.

## Disposition

- **Reader-capacity advantage unproven.** A positive result on the selected
  prefix cannot be promoted to the entire 98-call population.
- **MemoryCell parameter gain unproven.** A stronger external Reader does not
  measure adaptive memory quality.
- **Oracle sufficiency unproven.** Original review was missing for three
  development questions; the other reviews are not independent human proofs.
- **Citation semantic precision undefined**, because the observed answers
  emitted zero citation labels.
- **Production accepted: false**; prospective source-family independence,
  actually future tasks, training freeze, revocation recovery and full lifecycle
  costs remain unestablished.

The audit is implemented in `stage1_partial_reader_audit.py` and retains all
original misses in the planned denominator. A subsequent actual model experiment
should use frozen per-question/condition shards with explicit CPU budgets and
independently checked full-census collection, or measure a smaller
predeclared four-condition diagnostic first. Do not call a partial replay
new generation or fill remaining calls with synthetic answers.
