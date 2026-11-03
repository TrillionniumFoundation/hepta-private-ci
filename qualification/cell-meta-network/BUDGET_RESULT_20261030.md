# Observed total-budget continuation: split and prune remain unqualified

The fixed protocol ran on `main` in Runtime job `1a18b89dd54-96a-45ae`, with
output `/tmp/hepta-cell-budget-20261030-01`. All eight candidate executions
completed, all measured CPU allowances passed, and the recorded ordering check
confirms that the published held-expression rows were parsed after training.
No parameter or admission threshold was changed after these outcomes.

| Candidate | Held correct | Never-updated entities, held expressions | Charged CPU, two seeds | Actual total / trainable parameters |
|---|---:|---:|---:|---:|
| Dynamic split | 355/384 (92.45%) | 230/240 | 22.218990 s | 10,764 / 6,144 |
| Fixed experts | 368/384 (95.83%) | 236/240 | 22.198996 s | 10,764 / 6,144 |
| Rank increase | 377/384 (98.18%) | 238/240 | 22.158891 s | 10,764 / 6,144 |
| Pruning | 120/384 (31.25%) | 69/240 | 22.154637 s | 6,156 / 1,536 |

Dynamic split is 22/384 answers behind the rank-increase candidate and loses
eight more held expressions for never-updated entities. Pruning reduces stored
capacity but substantially damages retained behavior. These results do not
admit automatic split or prune. Rank increase is the best of these tested
candidates in this finite configuration; two seeds and reused expressions do
not establish universal superiority or significance.

## Why positive local credit is insufficient

Dynamic split reaches training-prefix task utility 1.0 at all three phases in
both seeds. Its twelve adapter-update conditional contributions are all positive
(approximately 0.08984–0.45313); its routing counterfactuals are also positive.
Nevertheless, its held-expression quality is below the single rank-increased
model. A local feedback signal can recognize useful work without proving that
the proposed structure improves generalization of the whole system.

Pruning immediately lowers phase-one utility from 0.7890625 to 0.236328125 in
seed 731 and 0.328125 in seed 732. Subsequent learning raises both to 0.794921875,
but that does not repair held-expression retention. In seed 731, the phase-two
update itself has negative task-value credit, −0.033203125. This is a concrete
reason to preserve candidate rejection rather than automatically activate a
local optimization step.

The credit measures remove one update while keeping the other final components
fixed. They are conditional ablation measurements, not additive Shapley values,
randomized causal estimates, or proof of a globally optimal routing policy.

## Measured costs and boundaries

The single shared process used 88.731515 CPU seconds and 89.099801 wall seconds
before final report serialization. Shared setup was 3.306532 CPU seconds and
coordinator overhead 0.017066 seconds. Both are already allocated into the arm
totals; adding them again would double count. Peak process RSS was 306,712 KiB,
which is a whole-process peak, not a per-cell memory footprint or resident-byte
integral.

Stored checkpoints over two seeds and three phases were 378,518 B for dynamic,
378,656 B for fixed experts, 258,165 B for rank increase, and 156,021 B for
pruning. Sample presentations were respectively 362,816, 473,088, 766,496, and
817,696. The protocol gives equal total CPU ceilings and an equal parameter
upper bound; it does not claim equal consumed CPU, equal actual pruning
parameters, or equal sample exposure.

The existing frozen encoder vectors and trained parent checkpoints were reused.
Historical parent training/encoder creation, interpreter startup before the
module clock, final report serialization, and external transport are outside
this observed process window. `full_cost_exact=false` remains correct. The
result is an exploratory continuation of a finite eight-address task, not a
new blind benchmark, native production rollout, recursive cell-growth result,
or general-intelligence demonstration.
