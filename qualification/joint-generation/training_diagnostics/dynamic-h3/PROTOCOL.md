# H3: fixed TRAIN-only headroom and complete-service receipt diagnostic

This is a separately registered development diagnostic, not qualification or
a rerun of codec D1. D1's frozen hard-stop slot-0 failure remains final.
H3 is **not executed** by creating this document. Commit and review the protocol,
runtime source and `frozen-h3.json` before the single permitted execution.
No r1/CORE reopening, r2 test, new formal data, model training, critic fitting,
validation metric extraction, threshold/lambda/rho selection or AV is allowed.

## Explicit authorization after the retained H2 startup failure

H2 remains consumed and sealed. Its sole worker invocation failed with
`independent.accounting.AccountingError: invalid arm` at dependency initialization:
`WorkLedger("H2-TRAIN-R&D-not-qualification", ...)` contains an invalid ampersand.
The source commit was `f3c9d89bf10be3e0d7664d3ba5c3eb17cc782665`, execution commit
`a5bec822cf5c235c52c7a6ab20bf74297a9795e8`, and original freeze SHA256
`cf555cd1571d2019b6c9c2e1ca737ff9392682a0e2b19aae580425d699413e52`.
Only dependency imports ran: zero TRAIN construction, restored/loaded models,
native forward or service calls; all 36 measurements remained unexecuted.
This is an implementation failure, not a scientific effect estimate or result.

H2's original stage/output START, PARTIAL, diagnostic, protocol/freeze, report and
outer receipt paths/hashes are bound in `prior_H2_failure` in `protocol.json`.
The H2 stage START SHA256 is
`4bd25ebd1569630a273acc059baea093e737a9926a00d1ddd348359be4cc04dc`.
No H2 lock or artifact is reset, overwritten, resumed or replaced.
Its full worker/descendant CPU was 0.491702000 s plus 0.027556463 s launcher-own
CPU before final receipt: **0.519258463 s retained prior research cost**.
Zero declared units and zero measurements did not mean zero research expense.

The parent explicitly authorized one new H3 after this zero-measurement failure.
The sole scientific execution repair removes the ampersand, preserving accounting
rules; H2's legal label is `H2-TRAIN-RD-not-qualification`, H3's identity label is
`H3-TRAIN-RD-not-qualification`. Reuse the shared physical files
`training_diagnostics/dynamic-h2/run_once.py` and `analyze.py`; the thin fixed
`--experiment h3` profile selects only H3 stage/output/freeze/schema/arm identity.
There is no second training/analysis engine or changed model/cost equation.
Freeze committed repair/source/protocol identity and pass the real shared
import/WorkLedger `--startup-smoke` without data, model, native or service work.
Then the registered command is:

`python training_diagnostics/dynamic-h2/run_once.py --experiment h3 --freeze training_diagnostics/dynamic-h3/frozen-h3.json`

The newly authorized H3 budget is the same **30 CPU seconds, 4B units, 32 MiB**.
Do not use the earlier unapproved reduced-budget recovery draft. Report H2's
0.519258463 s separately and cumulatively alongside actual H3 and preflight R&D;
do not credit or conceal that cost. The authorization permits this one H3,
not selective repeats of measured samples or further automatic recoveries.

## Question and restricted comparison

Fill H1's missing same-NC direct-full service cost and selected static NDU TRAIN
decoded utility, keeping routing opportunity, content opportunity and complete
cost distinct. The comparison is to T11's already selected **NDU/full**, a
necessary effective-static comparison. It is not a proof against every static
policy/menu, nor evidence that an implementable dynamic policy wins. H1's saved
g, prices and conclusions remain immutable; H3's new simultaneous-wave prices
receive separate names. Do not transport either price to the cached codec.

All models already saw TRAIN and were selected earlier using validation.
This diagnostic cannot establish independent content generalization.

## Fixed source and artifact identity

The canonical machine-readable parameters and every exact SHA256 are in
[`protocol.json`](protocol.json). They bind:

- T11 archive `runs/codex-cloud-efficient-r2-t11/retained-full-run.tar.gz`, SHA256
  `369afeca8c5e79e7e1c835f224c4683ad0d298e832e4250c578f529b61044702`;
  member `selection.json`, SHA256
  `43667a768d2b951b2bf6965c32683a5e9114fb6832a33af924ae161581b5c157`;
  the original-file inventory is bound separately.
- Six selected model members: `ndu_control-{11,23,47}-0.01.npz` (NC, 488 updates
  each) and `ndu-{11,23,47}-0.01.npz` (N, 513/514/514 updates), their NPZ SHA256
  and content digests; three original NC controller NPZ members and SHA256.
  No candidate selection or model substitution occurs. NC and N decoder/bias
  bytes were previously checked equal within each seed; content weights differ.
- Existing T11 `build/libjoint.so`, SHA256
  `ca84652442d6258ab67f2d553fb55742e0cc4c08222cb5e0fad02504c7ad32a0`.
  Reuse is explicitly separate R&D, without compilation or credit to any build.
- Q1 `predictions.npz`, SHA256
  `dcfe04a99c3825cf4df2afc95b2c0c1a894a9723fa602abf8cf2ac7095145fdf`,
  and its frozen protocol and completed diagnostic hashes.
- Original TRAIN profile, manifest and data-source hashes. Dataset input digest:
  `3863542c447c6b5f898f9ac14d7f9e76afb5f602ddb9798f65f20cba39cbff68`.

Root's `frozen-h3.json` must bind the committed protocol SHA256, source commit,
complete runtime-source inventory and script SHA256. Check actual committed
bytes at preflight and after execution; the protocol does not invent runtime
hashes before the script is finalized. Use only the saved Codex Cloud environment.

## TRAIN input and decoded-content checks

Existing Q1 arrays contain utilities, actions and identities, but not pixels or
labels. Reconstruct **TRAIN exactly once**, using the original profile and frozen
data equations. Do not construct validation or test even for identity checks.
Require all 3072 input hashes in their original order, all 192 physical-source
identities and the complete TRAIN manifest to match. Every source has sixteen
instruction/sensor rows. Keep all sources, rows, labels and original order.
Persist the full pixel/instruction tensor, labels and row/source identities once
in a bounded artifact; subsequent probes reuse these same bytes, not another
constructor or a newly sampled source. Q1's existing arrays remain referenced
by hash, rather than copied or modified.

For every seed, compute the same NC full and low decoded raw expected utility
and g=full−low, checking all three against Q1 with **absolute tolerance 1e-12,
relative tolerance zero**. Any mismatch fails; do not relax tolerances. Compute
new selected-NDU full decoded raw utility for every TRAIN row using the same
fixed external decoded-output utility and true TRAIN labels. No label is passed
to serving. Content observers are outside service timers but inside total R&D
CPU and declared work. Retain arrays named `s{seed}_NC_full`, `_NC_low`,
`_NC_delta`, and `_N_full`. Preserve all per-row/source effects, including tails.

## Thirty-six complete service calls, no short timing substitute

Use model seeds in order **11, 23, 47**, repeat indices **0, 1, 2** and paths:

| Path | Actual work |
| --- | --- |
| NC-full | Same selected NC weights, direct full; no unused low/critic |
| NC-go | Same NC weights/original fitted MSE controller; real low+critic, force continue, real full |
| NC-stop | Same NC weights/original fitted MSE controller; real low+critic, force stop |
| N-full | Selected static NDU weights, direct full; no unused low/critic |

Each call uses **all 3072 TRAIN rows**, in original order, fixed batches of 64,
and the old `rowwise-png-v1` output path. This is 3 seeds × 3 repeats × 4 paths
= **36 complete calls and 110592 actual output rows**. Each call freshly pays
complete generator/controller preparation and actual sampling, caption, learned
RGB decoding, PNG/hash/base64/JSON and output-ledger work. Do not use a codec
table, warmup, shortened call, new model fit or unused static critic. Retain
measured preparation independently from service, including local imports/setup.

For each seed/repeat left-rotate the base list
`[NC-full, NC-go, NC-stop, N-full]` by `(repeat + seed_index) modulo 4`.
Sampling seed is `model_seed + 1009*repeat`; all four paths within that pair
use exactly the same sampling seed. Retain exact execution order and all three
observations, including negative increments and outliers. No fastest sample,
trimmed repeat, alternative order or repeated timing until favorable is allowed.
Timing is descriptive; no service CI or significance claim is computed.

For each completed call, retain only its **first actual PNG/JSON** in
`sampled_output`, together with all 3072 rows' work/CPU/output-byte vectors,
batch/preparation vectors and original receipts, and the sample seed.
Batch-shared CPU/preparation allocations
keep their original scope; they are not independent per-row timing samples.
The other sampled outputs are actually produced and costed, but **not all
110592 PNG/JSON payloads or complete RNG trajectories are retained**. Do not
claim full output-byte retention or cross-codec equivalence: H3 has no such
goal, and does not inherit D1's full PNG comparison obligations.

## Fixed cost equations and conditional assumptions

Keep R=**73435.296875 ns**, price=**0.02**, H=**100000** requests per selected
seed, and three selected seeds. Historical complete whole-arm build CPU is
**8.537556029 s for NC** and **8.307966292 s for N**; each seed receives one
third. Convert build seconds to nanoseconds before dividing by R. These build
receipts are not remeasured, refunded, or increased. Gross critic/helper cost
already lies inside NC build and must not be added a second time.

For each seed and repeat let service CPU values be nanoseconds and n=3072.
Preserve the three signed `(NC-go − NC-stop)/n` values. Define:

`m = median_repeats((go_service_ns - stop_service_ns)/n)`

`c_H3 = price * max(0,m) / R`

`Cstop = price * median_repeats(stop_service_ns/n + stop_prepare_ns/H) / R`

`B_NC = price * 8.537556029 * 1e9 / (3*H*R)`

`B_N = price * 8.307966292 * 1e9 / (3*H*R)`

`J_oracle_proxy = mean(NC_low + max(g-c_H3,0)) - Cstop - B_NC`

`J_N_direct = mean(N_full) - price*median_repeats(N_service_ns/n + N_prepare_ns/H)/R - B_N`

Independently of timing assumptions, also report the fixed descriptive quantity
`free_label_oracle_raw = mean(max(NC_full, NC_low))` and its difference from
`mean(N_full)`. This is only an empirical raw-utility ceiling on this TRAIN
batch for these two fixed NC potential content actions, given free outcome
labels. It cannot alone bound full-lifecycle net utility or rule out a different
model, architecture, content action set or unseen sample.

Also retain signed-price sensitivity before zero-clamping, same-NC direct-full
cost, NC-go versus NC-full mandatory-overhead contrasts, and the TRAIN content
gap `D=mean(N_full-NC_full)`. Keep all three raw paired costs and prepared/H
terms; do not silently equate a difference of medians, a median of differences,
or a median stopped cost plus a median marginal difference. Expose any residual
between that additive proxy and observed complete always-continue cost.

The label-known oracle assumes a constant additive marginal cost and a mixture
of observed median costs; actual chosen rows can change encoding cost/timing.
It is **not a strict complete-CPU upper bound**, nor a deployable policy. No
result may be called dynamic superiority over the full best-static menu.

## Hard bounds, one-shot failure and retention

The safety bounds are **30 process-plus-child CPU seconds for all H3 R&D,
4 billion declared operator units, and 32 MiB retained artifacts**. They are
diagnostic bounds, not changed qualification budgets. Include startup/imports,
archive verification/loading, reconstruction, observers, all content/service
work and persistence. Retain launcher-own CPU separately, without counting
waited-child CPU twice, and include its overhead in total R&D cap review.
Every executed mathematical kernel is admitted/charged; RNG, hashing,
allocation, PNG/JSON and I/O remain actual CPU even outside declared arithmetic.
Store the specified first-output evidence and complete returned cost vectors
within the bound. Administrative compression is paid R&D, not cached runtime
execution; it does not imply retention of every generated output payload.

The fixed experiment-wide exclusive latch is
`training_diagnostics/dynamic-h3/START.json`; retain an identical copy at fixed
output `runs/codex-cloud-dynamic-train-headroom-h3/START.json`.
Acquire before any TRAIN reconstruction. Existing/partial START consumes H3;
changing or deleting the output directory cannot authorize another execution.
Any exception, mismatch, cap breach, storage refusal or interruption is final:
stop further model/data work, preserve the original error/nonzero status,
partial costs and available artifacts, and **do not rerun**. No automatic retry
or new output alias is allowed. Final persistence must preserve failure rather
than conceal a cap breach. Check retained source/artifact identities unchanged.

If a measure fails before returning its partial private ledger, report known
settled declared units as a **lower bound**, its unsettled preflight quote as an
**upper bound on the additional units**, and `accounting_incomplete=true`.
Retain the quote's scope and the original failure; reserved upper-bound work
must not be labeled executed/settled. An unavailable partial measure does not
justify claiming a complete ledger, zero remaining work or a successful bound
check. If a valid finite unsettled bound is unavailable, state that limitation
explicitly. Failure still consumes H3 and stops without a retry.

Keep the reconstructed input artifact, row IDs/hashes, decoded utility arrays,
all returned raw call/cost records, one `sampled_output` per completed call,
execution order/sample seeds, runtime environment, exact source/protocol/freeze
identities and full process/child receipts. Report what failed or remained unrun
and the stated evidence/accounting limits. H1, D1, all r2/CORE failures and their
test states remain unchanged; no merge, deployment or permissions change.

