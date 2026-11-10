# HPCA-MICRO-V1 original-evidence claim guard (2026-11-10)

**Scope:** read-only historical-result adjudication. **Authority:** `DENY_ALL`.
**Scientific and production decision:** `HOLD_NO_GO` for this material.
This package does **not** reproduce training, rerun the already closed smoke,
integrate any owner, infer neuroscience, train or deploy a model, or verify
that an external data owner produced the report.

## Original source identity (independent input, never silently relabel it)

- Research PR: [#5739](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5739).
- Original complete execution commit: `f07f41f9a396f7096211b9cc984543b773ce719b`.
  Do not substitute the later documentation HEAD.
- [Original GitHub Actions](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42823724940),
  job `129855449784`, completed success on **2026-11-10**.
- Artifact: `hpca-micro-result`, ID `13768490076`, declared ZIP
  `sha256:69618c9ef6dd3e171c3bc8da8a16b104eb55213ae962b0ba21157e9e39410cb6`,
  retention to 2026-11-24; verify against original ZIP **independently** before
  treating the extracted report as GitHub-produced.
- Original **four-code-file** source-manifest SHA-256:
  `3305e052434eee355d6230785e19e3bd41b7e7ee59691f78a89211e7c79fb63d`.
- Original calibration seeds `9001..9006`; held-out exploratory seeds
  `11001..11016`. The 16 seeds were used in the original synthetic
  exercise; they are **not independently sourced real tasks**.
- Existing [original human-readable audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/15daf24ef21e9d038919fef53b82e3a6fb70358d/qualification/hpca-neuroscience-20261110/EVIDENCE.md)
  is a summary, not the original report bytes. The unit tests here construct
  a **synthetic input fixture** transcribed from its descriptive numbers,
  not independently authenticated historic evidence.

## Check original report without rerunning model training

After retrieving the existing report from GitHub Actions and separately
verifying the original artifact ZIP digest:

```bash
cd qualification/hpca-claim-gate-20261110
python3 -m unittest -v test_claim_gate.py
python3 claim_gate.py \
  --input /path/to/original/hpca-result.json \
  --output /path/to/ABSENT/hpca-claim-review.json
```

The CLI reads the original JSON (up to 256 KiB), refuses wrong source
manifest/seed rosters, duplicate JSON fields, NaN/Infinity, missing arms,
incoherent family totals, unequal strong-baseline update costs, unpaired
feedback denominators, zero-delay trace-parity violations, and
resource-unmatched neural replay updates. It never touches the original;
output is create-only and stores the SHA-256 of the **exact input bytes**
(not a proof of original ownership).

The decision is **always HOLD**, even if every reference metric is improved.
Its structural check is not a certificate of the origin or truth of a metric.
No `GO`, `Adopt`, `Selection`, `FinalUse`, training or model-writer operation
is exposed. A Boolean claimed independence flag would not prove an
independent evaluator; this historical report has none.

## Historical interpretation: scientifically necessary negative results

- H1 heterogeneity improves aggregate synthetic MSE but **regresses PERC and
  ACT**. Per-family non-regression is mandatory before considering a change to
  a production cadence. Matching 256 optimizer *updates* alone does not
  match all forwards, backwards, latency, label cost, scheduling or memory.
- H2 correctly routed credit and a same-information contextual policy
  gradient are **exactly equivalent** in this experiment. No novel
  algorithm can be claimed from beating shuffled routing; full broadcast
  spends more weight writes.
- H3 an eight-step event trace beats an intentionally incorrect latest-trace
  reference on sparse feedback, but the dense delayed slice also has an
  advantage over that corrupted control. This is **not** isolation of a
  sparse-specific effect, neurochemical diffusion, or improved real
  downstream ACT/CTRL outcome. Direct feedback/supervised and matched
  time-aware baselines remain necessary.
- H4 stratified and error-priority replay improve old-task retention
  **while reducing new-task accuracy** relative to uniform; error priority
  incurs scans. Exact-key retrieval beats the hashed neural candidate on
  both reported accuracy measures but has a richer representation; it is a
  mandatory strong reference, not a fully matched memory-cost winner.

Independent follow-on implementations already exist elsewhere:
[#5756](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5756)
(198-slot FP64 corrected synthetic development run, **not real-task evidence**),
[#5770](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5770)
(recovery review), [#5797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5797)
(pre-selection replay inventory), and
[#5811](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5811)
(prospective shadow evidence preflight). This guard does **not** reimplement
those or alter `hepta-neuron`, native Agentd, MEM/PERC/ACT Cell owners.

## Remaining exact acceptance obligations

An independent, prospective run must freeze a genuinely new, authorized
task/holdout dataset; actual model/encoder/tokenizer/config/source tree;
baseline capacities, tuner opportunities and all resource costs; evaluator
identity and results; independent seed clusters and corrected inference;
and per-lineage no-regression/old-task/OOD/revocation criteria. Then use the
original Agentd/Root owners for true A training, independent future B,
authorized Adopt **or** NoUpdate, distinct C consumption and genuine
daemon+Root cold-recovery. Missing or UNKNOWN receipts cannot be promoted.

**All independent real-task confirmations remain unestablished by this
package.** This guard is a narrow safeguard against upgrading the completed
HPCA-MICRO-V1 smoke's descriptive results into claims it cannot support.
