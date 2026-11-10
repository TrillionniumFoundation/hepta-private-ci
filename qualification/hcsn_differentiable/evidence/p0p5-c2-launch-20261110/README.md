# C2 preparation, authorized launch and first actual optimizer steps

This immutable snapshot closes the preparation-to-execution chain for the six
original HCSN candidates. The first read-only observation is dated
**2026-11-10 21:17:50 UTC**. All six continuations had started, restored their
last complete epoch, captured a real gradient-enabled training microbatch and
completed its corresponding optimizer step. No continuation had completed a
new epoch at that observation. These are launch facts, not terminal training,
numerical qualification or evidence of scientific benefit.

The [status](STATUS.json), [first-step index](FIRST-STEP-INDEX.json),
[original observer summary](first-step/SUMMARY.json) and
[original observer archive](first-step/hcsn-c2-start-observation-20261110-v1.zip)
retain that scope. Future results belong in a separate appendix.

## Exact source and decision chain

| Stage | Retained evidence | What it establishes |
| --- | --- | --- |
| Candidate v1 | [Original package](preparation/v1/hcsn-c2-execution-candidate-20261110-v1.zip) | Two cloud software attempts: 16 tests, then 40 tests. Earlier attempts and costs remain. |
| Candidate v2 | [Original package](preparation/v2/hcsn-c2-execution-candidate-20261110-v2.zip) | A counterexample showed that return code zero without a valid terminal result could be accepted. The correction received 48 synthetic tests. |
| Candidate v3 | [Independent review archive](preparation/v3-review-original.zip), [review](preparation/v3-review/REVIEW.md) | A second counterexample showed that row counts alone did not prove batch-position, time-gap or model-digest coverage. The corrected gates received 53 cloud tests and independent metadata checks. |
| Native v3 | [Native receipt](native-preflight/RESULT.json), [handoff](native-preflight/HANDOFF.json) | 53 synthetic tests and all six real parent bind-only validations passed in the original runtime. Real models and optimizers were constructed and loaded; no production data forward, backward or optimizer step occurred. |
| Reporting-only v4 | [Exact capsule](launch/source-v4.zip), [manifest](launch/PROGRAM-MANIFEST.json), [delta](preparation/v4/REPORTING-DELTA.json) | Reporting now distinguishes resumed attempts, new optimizer steps and missing terminal evidence. Five targeted cloud tests and independent AST review passed. A second full native preflight was not run. |
| Root decision | [Original decision](decision/DECISION.json), [independent review](decision-review/RESULT.json), [input locators](decision/INPUT-LOCATORS.json) | A concrete bounded diagnostic continuation was authorized before execution. The preparation contract itself remains unchanged. |
| Actual native launch | [Intent](launch/LAUNCH-INTENT.json), [acknowledgement](launch/LAUNCH-RESPONSE.json), [six commands](launch/FIRST-COMMANDS.jsonl) | The stable launch key was used once. All six child PIDs were dispatched between 21:13:44.057721 and 21:13:44.061997 UTC. |
| First actual steps | [Original handoff](first-step/HANDOFF.json), [producer records](first-step/hcsn-c2-start-observation-20261110-v1.zip) | Six complete-state witnesses preceded any new optimizer step; six real gradient microbatches were captured and their optimizer steps completed. |

The v4 capsule SHA-256 is
`95d53c9a8fd7b6d0d60388b29d58519160c1d04357069bd805e5f4bfa2c91079`.
The decision SHA-256 is
`bee192193f0f12599f783f348b6dea8c10b2a18df359487c3cc0c0c44d071370`.
The launch key is `hcsn-c2-native-execution-c385-v1`. The original v8 model,
frontend, head, data, physical parameters, two learning rates and three seeds
remain those of the original campaign. The new continuation wrapper is
explicitly v4; “unchanged source” in the decision refers to the original model
and experiment source, not to an assertion that no wrapper was added.

## Restored work and prospectively bounded costs

| Candidate | Restored complete epoch | Already executed partial updates discarded |
| --- | ---: | ---: |
| seed 101, learning rate .001 | 46 | 7 |
| seed 101, learning rate .003 | 47 | 5 |
| seed 211, learning rate .001 | 46 | 10 |
| seed 211, learning rate .003 | 47 | 1 |
| seed 307, learning rate .001 | 46 | 8 |
| seed 307, learning rate .003 | 46 | 10 |

All discarded work remains charged. Each fit has a cumulative active wall
allowance of 43,200 seconds, including its complete original outer process,
imports, recording, evaluation and finalization. At dispatch, the remaining
allowances were approximately 28,822–28,824 seconds. The protocol retains
the original plateau rule and allows at most 200 complete epochs. Six workers
use one thread each, an 8 GiB address-space limit and a 6 GiB RSS stop per fit.

The 600-second finalization reserve is inside this same cap. It asks training
to stop early; it does not guarantee that final recording, evaluation and I/O
finish. A supplemental capture slot has one shared 120-second soft timer for
all three episodes. It is not a 120-second allowance for each episode.
Timeouts, recording holds and missing terminal evidence cannot grant adequacy.
Actual polling and exit overhead must be retained, not hidden by the budget.

[COSTS.json](COSTS.json) indexes the five cloud attempts, independent reviews,
the native preflight, its separate archive process, and the read-only observer.
The native GNU measurements are 58.69 seconds for preflight, .35 seconds for
its archive and .26 seconds for the first-step observer. These rounded full
process measurements contain their respective inner timers. They must not be
added to those nested timers. Current C2 full process totals, energy and billing
remain unknown at this snapshot. Interactive preparation costs are incomplete.

The original [300/900/1800-second resource comparison](../p0p5-resource-replay-20261110/resource-analysis-v1/output-v1/REPORT.md)
remains unchanged. C2 is a separately labeled longer-resource/calendar phase.
It does not retroactively make the original fits adequately trained.

## Actual training visits and supplemental replays

The first six actual gradient microbatch capture receipts report **1,536 time
rows and 12,182 valid sample states**, with padding excluded by the producer
coverage gate. They are real optimization visits, separate from the three
no-gradient checkpoint replay episodes. The first-step observer copied
`RESUME-START`, `CAPTURE`, `STEP-COMPLETED` and event records; it performed no
model load, forward, backward or update.

This index has not independently reread the complete checkpoint tensor states
or the approximately 150 MB of first-capture probability arrays. Their byte
identities are retained in the producer records. A terminal independent audit
must check those originals, the complete-epoch commit chain, the full roster,
all costs and fresh full-development predictions before a further claim.
Sparse selected microbatches cannot establish whole-trajectory qualification.

The [actual-gradient policy](launch/OPTIMIZATION-POSTERIOR-POLICY-v2.json) and
[supplemental policy](launch/POSTERIOR-POLICY.json) were fixed before launch.
They record the first microbatch after resume and declared epoch milestones;
supplemental replays preserve model, gradients, mode and RNG. All recording
work consumes the declared fit allowance.

## Numerical limits retained at the execution decision

The [first-14 provenance](numeric-context/first14-RESULT.json) and its
[independent closure](decision-provenance-review/RESULT.json) bind the saved
finite-schedule cases available at the decision. They passed the original
scaled-error gate, not the whole numerical plan. The
[bound rare-count example](numeric-context/rare-count-original.json) has about
4.14% relative count error while passing the scaled gate because the reference
count is below one. That gate is `abs(error) / max(1, abs(reference)) <= .01`.

The [ordinary finite-difference investigation](numeric-context/six-logrisk-RESULT.json)
retains the failed/inconclusive primary gate for all six models. The one
above-resolution ordinary FP64 disagreement is in the discount derivative of
log G; autograd, the 80-digit derivative and high-precision finite differences
agree there. Discount is fixed in this continuation. This does not certify
every trainable-network gradient or justify changing the frozen tolerance.

A later read-only [six-model pressure summary](numeric-context/six-model-pressure-RESULT.json)
binds existing observer records without altering the decision: all six best
models fail both tiny-gap infinite-repeat value sentinels, for 12 failures out
of 18 total sentinels. The underlying 10,752 supplemental vector records are
not a historical training-coverage denominator. Finite burst tests start from
posterior position 47 and use actual future gaps; the pressure sentinels start
from positions 48/49 and repeat one tiny gap forever. Their conditions and
horizons differ. A finite-schedule pass does not cancel a pressure failure.

Learnable physical domains, global tail precision, whole-trajectory numerical
admission and scientific benefit remain **HOLD**. P5 remains gated on benefit.
The original terminal numerical audit is separate and is not declared complete
by this package. Confirmation split E has not been used in this continuation.

## Original bytes, transport failures and reproduction

[ARCHIVES.json](ARCHIVES.json) records the original ZIP identities, CRC-checked
member hashes and reconstruction order for split files. The two native
preflight ZIP parts concatenate to the exact original 581,500-byte archive;
they must not be recompressed. Original Base64 transport responses, a timeout,
same-upload-ID reconciliations and duplicate read observations are preserved
inside the [preflight transport archive index](native-preflight/CONTROL-PLANE-ARCHIVE.json)
and [launch/observer transport archive index](first-step/CONTROL-PLANE-ARCHIVE.json).
The failed transfer did not authorize another independent training run.

From the repository root, verify this snapshot without executing any model:

```bash
python -B -m qualification.hcsn_differentiable.evidence_chain \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-c2-launch-20261110/MANIFEST.json \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-c2-launch-20261110/README.md \
  --output /tmp/hcsn-c2-launch-integrity-new.json
```

Use a new output path. The [copy receipt](COPY-RECEIPT.json) records exact source
identities before and after curation; [MANIFEST.json](MANIFEST.json) fixes all
snapshot members. These checks establish the retained evidence, not numerical
admission, overall CI success, a main merge or release publication.
