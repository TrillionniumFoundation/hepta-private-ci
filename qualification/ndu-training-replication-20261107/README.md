# Independent training replication for the #5198 factorial protocol

Status: **STRUCTURAL_EXTENSION_ONLY / SCIENTIFIC_HOLD**.

Executed local verification: **50 tests passed, zero skips** (15 new replication
checks plus 35 existing factorial regressions). The synthetic complete-matrix
example has 4 declared fits, 2 episode seeds, 10,240 terminal rows and all 20
contrasts. See [VERIFICATION.json](VERIFICATION.json) and the complete
[execution-evidence.zip](execution-evidence.zip). These are software fixtures;
zero real training fits or confirmation tasks ran in this package.

This extension is stacked on #5198 at
`006e744fbb10a6ee393166eed2e5d1e91f2fab1f`. It leaves the v1 protocol,
single-fit auditor and historical evidence intact. No real training replication
or confirmation episode is created by this extension.

## What changes

`scripts/ndu_portfolio/factorial_replication.py` adds a prospective fit registry,
fit-specific model/policy identities and training-execution bindings. It reuses
the existing complete A/B/C/D and initial/fixed/VOI/MPC matrix, in both frozen
and joint regimes, and its source-group, objective, capacity, cost and timing
checks.

The independent axes are declared training fits and registered source clusters.
Episode seeds are averaged inside each fit/source cell. Repeating an episode,
adding a seed or renaming an execution does not create a verified independent
training run. Distinct execution IDs and hashes prevent detectable reuse, but
are not proof of process independence or native authenticity.

Each fit obtains its own validation-only strongest comparator. One global lock
binds all fit selections, fitted identities, training attempts and completed
training/search costs before any confirmation run starts. Evaluation expenditure
can be completed later; completed training/search expenditure cannot be rewritten.
The lock is detached from mutable input dictionaries.

Returned reports are detached deep snapshots as well. Changing the caller's
cost or selection dictionaries after an audit cannot rewrite its report while
leaving the old evidence digest in place. Derived totals and bootstrap results
must remain finite; overflow produces a bound HOLD/error receipt instead of
leaving an older success report at the output path.

All 20 original contrasts remain visible: the four factorial effects in each
regime, the two strongest-comparator effects in each regime, and four
joint-versus-frozen and four retention comparisons. Comparator identities are
reported per fit, including when different fits select different baselines.

## Statistical contract

For each contrast, let `Y[r,c]` be the paired effect averaged over the registered
tasks and episode seeds in source cluster `c`, for training fit `r`. The point
estimate gives fits and source clusters equal weight. The product bootstrap
resamples the two axes separately and keeps the paired arm effects together.

This is a balanced crossed-data calculation, conditional on the fixed training
data and observed validation selections. It is not an inference over newly drawn
training datasets. It does not rerun validation selection inside the bootstrap.
The percentile intervals use Bonferroni nominal tails for the declared 20
contrasts. They do not have an exact finite-sample familywise coverage guarantee;
few fits, poor variance estimates or a misspecified sampling structure can leave
them unreliable. Two declared fits is an input minimum, not an adequacy claim.
All scientific/adoption gates remain HOLD.

The prospective planning calculation requires an effect **above the decision
margin**, a target power and a pinned variance-evidence identity. Under the
declared independent random-effects approximation,

```text
Var(mean) = fit_variance / R
          + source_variance / C
          + interaction_variance / (R * C).
```

The supplied components must conservatively cover the contrasts to which the
plan is applied. The normal approximation uses the 20-comparison nominal
critical value and reports per-contrast planning power. It is neither achieved
power nor simultaneous power for all 20 conclusions. More source clusters cannot
remove the between-fit variance floor; more episode seeds are not additional
training fits. Real pilot variance, effect, margins and source identities remain
required before a real campaign can use this plan.

Primary methodological references:

- Art B. Owen (2007), [The pigeonhole bootstrap](https://arxiv.org/abs/0712.1111).
- Art B. Owen and Dean Eckles (2012),
  [Bootstrapping data arrays of arbitrary order](https://arxiv.org/abs/1106.2125v3).
- Rishabh Agarwal et al. (2021),
  [Deep Reinforcement Learning at the Edge of the Statistical Precipice](https://papers.nips.cc/paper/2021/hash/f514cec81cb148559cf475e7426eed5e-Abstract.html).

These precedents motivate the dependence treatment; they do not establish
coverage, power or efficacy for this unexecuted Hepta study.

## Costs, missing fits and failure handling

Every registered fit must be present, with the complete terminal matrix. A failed
fit cannot be dropped to improve the estimate. Failed training attempts that
precede a completed fit remain in its inventory and research charges.
An all-failed or incomplete fit makes the complete-matrix inference unavailable.
Keep the original campaign bundle and the error receipt; a failure is not a new
smaller preregistration.

The report retains per-fit, per-profile research charges and the complete
nine-category deployment ledger. Unknown charges remain null; overruns and
timing contradictions remain findings. Total research cost includes all supplied
fits, not only the selected model. Physical authenticity, disjoint-meter
reconciliation and truly independent source provenance remain external
requirements.

## Execute

A bundle is a JSON object with `plan` and `fits`. Each fit contains its v1
`protocol`, an `execution` record and `rows` carrying the matching `fit_id`.
The plan declares `fit_id`/training-seed pairs, a common design digest and the
power inputs. The adversarial test fixture is explicitly synthetic and provides
a complete runnable schema example.

First provide validation rows only and save the global lock outside the held-out
executor:

```bash
PYTHONPATH=scripts python -m ndu_portfolio.factorial_replication \
  --bundle validation-bundle.json --select \
  --locked-at 2026-11-07T12:00:00Z --output comparator-lock.json
```

After confirmation, supply the full registered matrix and the saved lock:

```bash
PYTHONPATH=scripts python -m ndu_portfolio.factorial_replication \
  --bundle full-bundle.json --selection comparator-lock.json --output audit.json
```

The timestamp above is illustrative, not a real preregistration.
Run the independent regression suite with:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python -m unittest -v \
  ndu_portfolio.test_factorial_replication
```

The existing blocking NDU job discovers the new tests automatically. Synthetic
schema execution establishes only the software behavior described here.

The source-bound reproduction command also preserves the complete synthetic
bundle, lock and numerical output in a ZIP:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  qualification/ndu-training-replication-20261107/reproduce.py \
  --output /tmp/ndu-replication-contracts
```
