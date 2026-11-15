# Independent P1 provenance review, version 3

## Decision and scope

**Artifact integrity and linkage pass. Scientific admission remains HOLD.** The
independent checker completed eight groups of checks in 0.281543 seconds. It did
not rerun the slow high-precision numerical oracles. The [receipt](p1-provenance-v3.json)
and [exact review script](review_p1_provenance_v3.py) retain the identities and
individual findings. This supplements the earlier independent review; it does
not replace its original files or grant full training-domain accuracy.

The checked archive is `hcsn-p1-evidence-20261110-v2.zip`, SHA256
`a1a32db092bce32db2d5e75804cbca316d4bab02080cc57ace5f6490390c0b79`.
Its manifest SHA256 is
`0b67283f7b9c2e1328d7da8041199713909e5d8c256bb4c9bccfaeacd37cc04c`.
All 189 ZIP members passed CRC, uniqueness and path-safety checks; all 188
manifest-listed files matched their bytes, SHA256 and expanded copies.

## Model, data and visited-state chain

The two original optimizer log entries identify 32 events from `A01-0` and then
32 from `A01-256`. Their finite losses and distinct tensor-state digests are
retained. Comparing initial and trained checkpoints independently found nine
changed content/observation/readout tensors, with physical tensors unchanged.
The trained checkpoint's **serialized file** SHA256 is
`cef66283de5f7175eca02ce2de8f441a0d72a60163019594418f91cee61b1584`;
its **canonical tensor-state** SHA256 is
`4bc4a16fcf546178fbe106b0224bd1ffa5c596abdf343719d7001ded1256d3d9`.
These intentionally hash different representations and are not interchangeable.

All 256 retained A01 visits use that final tensor state and `update_index=2`.
Their indices, priors, normalized posterior vectors, actual elapsed times,
footer prefix digest, source-before/source-after records and plan's 18 source
files agree. The three retained A episodes match the official preparation
manifest and integer timestamp differences divided by 10,000,000. No D or E
episode is part of this P1 artifact.

The original 256-cell process ended with exit 137 and did not finish; the
underlying cause is unknown. The separate numerical continuation binds the
original checkpoint, trace, plan and interruption record, and uses an unchanged
copy of the declared sources. It continues numerical checks from saved weights
and laws. It is not an optimizer or exact training-cursor resume.

## Finite schedules and retained failures

Each summary row agrees with its raw report and artifact digest. The saved
starting law and exact future duration slice agree for all six fixtures:

| Starting law and duration slice | Intervals | Maximum scaled error |
| --- | ---: | ---: |
| A01-0 position 31 | 32 | 0.00312231581906 |
| A01-0 position 127 | 32 | 0.00255649806510 |
| A01-0 position 223 | 32 | 0.00216529922997 |
| A04-3072 position 47 | 8 | 0.000598912942266 |
| A04-3072 position 47 | 32 | 0.00272456493514 |
| A01-0 position 31 | 128 | 0.00702721149240 |

The long continuation uses A01 duration entries 32 through 159, with horizon
4.2436075 and reference expected count 1.43305504974. The burst fixture includes
a 1e-7 second gap. These reference calls consume the starting probability,
physical/grid configuration and future durations. They do not condition on
future observations or pass future labels into the oracle. The original
training objective uses labels only from the two A prefixes.

The long128 runner records eight common source files before and after and
separately hashes the finite helper at its start; the helper's exact bytes also
exist in the frozen snapshot. It does not supply a separate end-of-run hash for
that helper. This narrower capture scope must not be described as an atomic
snapshot of every imported file.

The independently checked 128-cell failure is the maximum across **all three**
positions 31, 127 and 223: scaled count error 0.0164043650480 (1.6404365%) and
scaled value error 0.0140244661405 at position 223. Both candidates were
initialized and trained separately and have different learned starting laws.
Their individual pass/fail outcomes are not a common-posterior grid-convergence
experiment or proof that grid size alone caused the difference. The source-bound
135-case repeated-gap reproduction remains 0/135 passing; success on selected
finite schedules does not override that stress failure.

## Learnable physics and limits of credit

Three saved model/optimizer states and all 48 recorded visits agree with their
file and tensor digests. All four raw physical parameters change after each
actual Adam update. The drift remains negative at all three checkpoints, from
-0.12 to -0.1192178832 to -0.1184357469. Complete discrete-forward AD versus
finite difference was evaluated at post-update states 1 and 2; the largest
absolute error is 7.63323571018e-11. Gradient agreement does not remove the
coarse-grid numerical value failure (maximum scaled error about 3.27336%).

Every scaled error here is `abs(candidate-reference)/max(1,abs(reference))`.
For probabilities or values below one it is an absolute-error measure, not
relative rare-tail precision. Quadrature order doubling is measured refinement
sensitivity, not a certified total-error bound. Continuum basis derivatives
hold the starting mixture fixed; they do not independently establish the full
filtered network's derivative against an exact continuum observation model.

The width-4 candidate has two 32-event optimizer updates and selected numerical
continuations. This does not establish sufficient training, generalization,
width-16 transfer, the full constructor domain, positive-drift training, or
real-task scientific benefit. The cost ledger explicitly has
`total_cost_complete=false`; interrupted work is retained separately and energy
and currency remain unknown.

## Review history and replay

Version 1 stopped after five valid checks because the review script assumed
every checkpoint was a plain state dictionary. The learnable-physics files
correctly contain nested `model` and `optimizer` objects. That was a reviewer
parser defect, not an artifact defect. Version 2 passed seven groups. Version 3
adds initial/trained tensor comparison, the original optimizer-log linkage and
the maximum over all three 128-cell failures. Previous receipts remain intact.

The exact script records its original absolute scratch paths. To replay its
unchanged bytes, place the named ZIP and its expanded directory at those paths
and run it with the recorded Torch environment. Relocating its path constants
creates a new reviewer-source identity and should produce a separately named
receipt rather than replacing this one.
