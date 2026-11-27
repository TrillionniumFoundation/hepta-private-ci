# HCSN recovery, later C2 observations and preparation scope

This immutable appendix restores verifiable source and observation bytes after
the scratch contents became unavailable on 2026-11-11. It also records missing
originals explicitly. The latest complete-epoch observation archived here is
**2026-11-10 23:49:03 UTC**. At that observation three candidates had producer
terminal reports and three remained active. The original all-six native task
was still reported running by a separate read-only status response ending at
2026-11-11 00:08:14 UTC. Neither observation establishes its later state.

The [recovery scope](recovery/SCOPE.md),
[training recovery record](training/RESTORE-RESULT.json),
[numerics loss inventory](numerics/LOSS-RECOVERY-REGISTER.json) and
[mathematics/preparation inventory](math-recovery/KNOWN-LOSS-AND-RECOVERY.json)
distinguish complete original bytes, exact source restoration, captured tool
summaries, unavailable original receipts and new preparation. A hash without
its file is not counted as recovered evidence. No model or numerical oracle
was rerun to manufacture a replacement original receipt.

## Recovered C2 observations

The three new enclosing capsules retain the original native ZIP bytes,
observer sources, launch requests and available raw control responses. They
have new capsule identities; the old cloud-only enclosing packages are still
listed as missing.

| Observation | Original native ZIP bytes | Original native ZIP SHA256 |
| --- | ---: | --- |
| v6, 23:13:44 UTC | 183394 | 032c04659d6eb45e37a78a55207a8c51f1fb0c450b097f2edf223c92197f7a7f |
| v7, 23:30:25 UTC | 146046 | 72364b58d0fada4ff022559a54378fcb4e127597b836dff899e137b152b99beb |
| v8, 23:49:03 UTC | 152527 | f733bf0822ee9847b1e76a74be543f3d0eed782e2f610dbb6ba13c4d5fc2050e |

The capsules are [v6](training/hcsn-c2-observation-v6-exact-store-recovery-20261111.zip),
[v7](training/hcsn-c2-observation-v7-exact-store-recovery-20261111.zip) and
[v8](training/hcsn-c2-observation-v8-exact-store-recovery-20261111.zip).
The preceding complete prefix and its original source are retained in the
[earlier terminal numerical appendix](../p0p5-terminal-numerics-20261110/README.md).
The [restoration registry](training/VERIFIED-GIT-BLOB-REGISTRY.json) records the
separate persistence readbacks. Source restoration made no native training call.

The [v8 metadata index](training/V8-METADATA-INDEX.json) reads only the saved
observer scalars. Its [source](curation/summarize_recovered_c2_v8.py) and
[complete child receipt](curation/v8-index-execution/RESULT.json) are new,
explicitly scoped preparation evidence. They do not independently replay a
model, inspect probability tensors or select a new common learning rate.

| Seed | LR | Complete epoch | Strict best D macro-F1 | Best epoch | Observed state |
| --- | --- | ---: | ---: | ---: | --- |
| 101 | .001 | 77 | .2793821424 | 77 | Active |
| 101 | .003 | 76 | .3878342597 | 74 | Producer plateau |
| 211 | .001 | 77 | .3005516559 | 76 | Active |
| 211 | .003 | 50 | .3910932361 | 40 | Producer plateau |
| 307 | .001 | 78 | .2708893398 | 78 | Active |
| 307 | .003 | 72 | .3498305889 | 62 | Producer plateau |

The three terminal producers report adequate training under the original
heuristic. Independent all-six terminal admission remains pending. Strict best
selection and the .002 significant-improvement plateau anchor are distinct:
seed 101 / .003 has a strict best at epoch 74 but its last significant anchor
is earlier, so its ten stale epochs are not inconsistent with that best epoch.
The .001 candidates continue under their original limits and stopping rules.

| Producer terminal | New complete updates | C2 complete wrapper wall, s | Parent + C2 complete wrappers, s | C2 child wait4 CPU, s |
| --- | ---: | ---: | ---: | ---: |
| 101 / .003 | 348 | 8750.490398453 | 23128.517257252 | 8746.954086 |
| 211 / .003 | 36 | 1266.181475260 | 15643.131377665 | 1263.453444 |
| 307 / .003 | 312 | 7909.714266597 | 22286.683894893 | 7905.963201 |

These wall bills include complete original parent and C2 wrapper processes.
They are not first-time-to-quality measurements and are not spread backward
over earlier epoch observations. The new child CPU measurements are complete
for their recorded child processes; the historical original-fit CPU still has
missing startup/exit components, so cumulative CPU is unknown. Peak process
RSS is not VRAM, memory at the quality target, energy or provider billing.

The original 300/900/1800-second views stay unchanged. No later common-rate
selection, six-opportunity resource aggregate, confirmation score or superiority
claim is computed from this partial roster. The original C2 task identity,
source v4, physical parameters, six candidates and per-fit cumulative limits
are unchanged.

## Mathematical qualification boundary

The new [rare-tail note](math-recovery/rare-tail-review/NOTE-REVIEWED.md) and
[independent review](math-recovery/rare-tail-review/REVIEW.json) bind the new
document's exact bytes. The [source index](rare-tail-context/SOURCE-INDEX.json)
retains the previously committed operator, fixed-grid diagnosis and numerical
index. The earlier uncommitted draft is not represented as recovered.

For fixed finite rates, a finite homogeneous chain reaches a reachable marker
with a leading integer power of time. A diffusion started a positive distance
from the absorbing boundary instead has a negative small-time logarithmic
rate. The note also derives the different square-root and linear onsets for
constant and linearly vanishing boundary densities, the F/G discount bounds,
and the inability of a fixed finite phase chain to encode a strictly positive
deterministic wait exactly. A discrete semigroup can improve composition
consistency without qualifying those continuum tails or age laws.

These are deductions under explicit assumptions. There is no new numerical
scan, no fitted replacement operator and no assignment of the twelve existing
perpetual-value failures to individual mechanisms. The previously observed
finite scaled passes, relative-error limits, unresolved ordinary-FD checks
and whole-training numerical HOLD are unchanged.

## Software preparation and missing source

The [numerics recovery scope](numerics/SCOPE.md) retains exact recovered
supervisor sources and the original resource-program manifest, plan and four
available implementation modules. Four other implementation modules and
additional preparation files were not recovered as complete original bytes.
The partial directory is evidence of recovered bytes, not an executable or
qualified complete resource program. A new version is being prepared under
the same frozen statistical plan; it must have its own source and validation.

The original eleven-test supervisor receipt was exactly recovered. The later
twelve-test output is a captured tool record; its complete original RESULT
and independent closure bytes are not recreated. The obsolete first supervisor
had an adopted-descendant accounting defect and is not approved for use.
The restored later source includes the rejection guards, but its availability
alone is not a new execution or a recovered complete validation chain.

The [new renderer preparation](math-recovery/c2-resource-renderer-preparation-v2/README.md)
adds explicit rejection of unknown total CPU, incomplete direct-child CPU and
adopted-child wait records. It has one new syntax compile receipt and has not
rendered actual C2 results. It still binds the old resource-program manifest;
the pending replacement analysis program needs a separately reviewed rebind
before the renderer can consume its output. No actual-use authorization is
supplied by the preparation templates.

The independent terminal auditor's complete, earlier published core remains
available in its [original preparation](../p0p5-c2-progress-20261110/terminal-auditor/preparation/MANIFEST.json).
Its 1800-second core limit is unchanged. The uncommitted bootstrap preparation
has a separate loss record and requires new preparation before deployment.
The actual all-six terminal auditor and the 120-second resource analysis have
not run in this appendix.

## Hosted CI and integrity are separate gates

The [original hosted science ZIP](ci-science/ORIGINAL.zip) is restored exactly:
121491 bytes, SHA256
`34e6215b003b7d6de550c3636cd364d01af2639ecb2cdb80220ec2a236083ae3`.
The [new recovery receipt](ci-science/RECOVERY.json) checks its full size/hash,
member hashes and CRC. The [original identity](ci-science/identity.json) binds
source head `b908827` and tested merge `00a2b987` to the same full tree
`573c6399fcc2c2b9ef4197f4f503520cde3cad51`. Run 42922677682 attempt 1 reports
92 passing fixtures, zero failures/errors/skips, unchanged source, and success
for its declared science steps. Its fixture process records 11.482606229 wall
seconds and 11.464115111 CPU seconds. This is the old hosted execution's
evidence; recovery did not rerun that workflow or those tests.

The [new blocking-CI readback](ci-blocking/DIAGNOSIS.json) retains failures in
run 42922677728, which was still in progress at this observation. Its readiness
log again names the empty root README's missing discovery link. Another cargo
log request returned `Transport closed`, so that job's underlying cause remains
unestablished here. The complete returned responses are preserved in
[their new archive](ci-blocking/RAW-RESPONSES.zip). Six implicated file blobs
are unchanged between the prior published source head and `b908827`; this
does not explain every failed job or establish repository-wide success.

The appendix's manifest proves retained bytes and the evidence checker verifies
those bytes and file links. It does not turn a preparation check, a producer
terminal, a finite numerical fixture or an operational recovery into a
scientific-benefit claim. Confirmation E is unscored by this campaign, with
the previously disclosed historical schema/clock exposure retained. Broader
P1/P2/P3/P4 benefit and P5 adoption remain gated.
