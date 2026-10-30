# Semantic transport repairs the support filter's keep-axis regression

The prior command-support filter passed quality measures but failed its frozen
gate because conditioning slightly reweighted unspecified attributes. This new
opt-in operator instead **edits only requested set attributes of each generated
semantic candidate and transfers its probability mass to the edited candidate's
existing learned decoder slot**. It does not discard and renormalize mass.

Both observed text and image semantic maps must be complete bijections. Missing
or duplicate destinations reject; no nearest-class, renderer or best-target fill
is allowed. Pixels remain the learned decoder's output. All-keep is exact no-op.
The original model's wrong keep attributes remain wrong: they are not repaired
using a source-label oracle. Default serving behavior is not changed implicitly.

## Actual result on the same fixed bases and rows

Both seeds passed the **unchanged** five-condition partial-command gate. The
previous failed support arm is included unchanged as a comparator. Two fixed
supervised RGB bases each evaluated all516 validation rows; primary comparisons
use the same312 requests with one/two explicitly set attributes.

| Partial commands | Seed11 baseline → transport | Seed23 baseline → transport |
|---|---:|---:|
| Joint success | 0.747125 → 0.804635 | 0.738491 → 0.793513 |
| External expected reward | 0.752009 → 0.810499 | 0.743223 → 0.798982 |
| Actual pixel MSE | 0.010041 → 0.006851 | 0.011146 → 0.008077 |
| Unspecified text preservation | 0.918323 → 0.918323 | 0.909270 → 0.909270 |
| Unspecified image preservation | 0.914223 → 0.914223 | 0.912715 → 0.912715 |

All5472 per-request checks of the entire free-attribute joint distribution passed
at absolute1e-12. Neither model nor decoder was updated. All0/1/2/3-word strata,
baseline/previous-filter/new-transport values and costs are retained in the summary.

**Most of this is structural, not learned capability.** Copying unspecified
attributes makes their joint law invariant. Overwriting explicit attributes
increases correct semantic mass and can merge previously inconsistent outcomes.
These mathematical properties cannot independently establish improved learning.
Actual learned-pixel MSE remains an empirical quantity and improved here, but this
is only a closed12-class RGB validation task, not natural-image evidence. Earlier
digit experiments and the support-filter failure are not retrospectively rescued.

## Implementation and verification

`transport.py` defines a distinct explicit schema/mode, strict model binding,
semantic bijection, probability pushforward and roundtrip. `control.py` is the
unchanged prerequisite from the previous qualified profile. The new nine tests
cover the complete36-command lattice, actual decoded-map permutations, zero-prior
destinations, missing semantic rejection, no-op identity and cross-profile refusal.
Run `python -B -m unittest -v test_transport`.

This is a new serving-law operator, not a training gradient or Adam modification.
It preserves the independent text/image product-law form. Reusing a finite semantic
dictionary is an explicit model/task assumption, not general language understanding.
No inputs, model checkpoints, per-request predictions, machine paths or credentials
are included in this public package.

## Cost and continuation

Complete waited child, including nine tests/imports/restores/decoder observation,
1032 forward rows,1032 old-filter calls,1032 transports, invariants/metrics and exit:
**0.668309 CPU seconds**,0.690252 wall seconds,37084KiB RSS. Bounds10CPU/30wall/256MiB,
CPU0/one thread and a new synthetic-only shared lock. Two reused base-preparation
prefixes were0.219982/0.227947 CPU seconds; their other upstream costs are not free.
Preparation/review and supervisor final tail remain unknown, not zero. There is
no equal-total-budget or training-benefit claim.

A separate next hypothesis is to train against the FINAL transported law: pull
back the unchanged A/N reward table through the semantic map and differentiate
the final semantic anchor. That requires its own exact-gradient tests and fixed
paired training comparison; no such training result is claimed by this study.
