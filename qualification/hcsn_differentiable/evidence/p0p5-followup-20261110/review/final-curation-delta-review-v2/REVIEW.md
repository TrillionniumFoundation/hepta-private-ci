# Independent frozen curation delta review

## Result and exact scope

The frozen 472-file evidence snapshot passes the independent local integrity and receipt-binding audit. One mathematical wording correction remains: CURRENT must explicitly restrict its drift-sign recurrence classification to the fixed continuum diffusion/regenerative reference. No training, numerical oracle, model forward, native process observation, external publication check, or new scientific admission was performed in this review.

The reviewed top MANIFEST SHA256 is `bc8721b37d4a69c28a25a028dd6375ebbeaaa41111bafc97a22b7239609f5bc6`. CURRENT had SHA256 `05383a803ea62d839dc77c612bcc722332c51978997436005c34818adfcbe55f` and 445 lines. This report does not silently substitute any later document correction or later-arriving archive.

`execution/RESULT.json` records all 472 file identities, 38 archive instances including recursively embedded ZIPs, 182 relative Markdown file-link checks across four documents, 55 cost-artifact references, and 245 explicit source-field/hash/sum bindings. All passed; inputs and reviewer source were unchanged. The comparison with the preserved first curation review finds 195 unchanged files, four changed files, 273 added files, and no removals. Historical failed assembly reports and their old manifests remain opaque evidence rather than current root indexes.

The complete waited audit process took 0.550129093000578 seconds and 0.49149999999999994 child CPU seconds. These are costs of this local JSON/archive review only, not of the underlying experiments, informal preceding document inspection, or later writing and packaging. `EXECUTION.json` binds the exact command, source, stdout and stderr. No scientific or repository-wide CI credit follows from this integrity pass.

## Scope correction MATH-01

CURRENT's paragraph beginning “With fixed positive reset distance” correctly states the continuous-model classification but does not explicitly identify its model class. With fixed positive reset distance, constant drift and nonzero diffusion, the continuous reference has finite mean cycle time `d + x_r/(-mu)` for negative drift, almost-sure hitting with infinite mean active time at zero drift, and a defective first-hit law at positive drift. Repeated reset cycles then permit escape and only finitely many future events almost surely in the positive-drift continuum reference.

The current finite implementation is different. `operator.py` identifies its tail as `returning_shifted_exponential`; `initial_probability` reconstructs integrated tail mass using the fixed exponential basis; `_construct` integrates each step from fixed finite-cell and exponential-tail source densities. `MODEL.md`, section 2, already explains that the approximation is `Q P_dt R`, reconstructs the tail after every propagation, and does not preserve the exact semigroup. The tail coefficient is not an absorbing state at infinity. These facts do not justify carrying the continuum escape or stationary-rate classification over to arbitrary repeated finite-QPR propagation, FP64 kernels, conditioning schedules or trained parameters.

Recommended narrow correction: introduce the paragraph with “For the fixed continuum diffusion/regenerative reference, with a fixed positive reset distance, ...” and state that these continuum asymptotics do not qualify the finite QPR chain, whose returning-tail reconstruction can change long-run recurrence and event rates. This review requests a documentation scope correction, not an unperformed numerical experiment or an asserted finite-chain stationary rate. The source checked for this finding is bound below:

| Input | SHA256 |
| --- | --- |
| CURRENT.md | `05383a803ea62d839dc77c612bcc722332c51978997436005c34818adfcbe55f` |
| MODEL.md | `8919ff5f44af1e8929f2a6838d765f8e0333c807190834f6a957db8a142b611b` |
| operator.py | `cb3eed1bcfbd3b10cc331a193a5d4b6a3d4309db899e0d8f821477f97b7dbdc1` |
| contract.py | `79e1127dc126fb8ac97ce7542bac2c9d70c71e0fd2d24416f146d4ec82be099e` |

## Baselines, C1 and observed quality

The evidence distinguishes original fresh baseline adequacy (26/36), seven original epoch-cap continuations, and combined-chain adequacy (33/36). All three original memorization failures remain failures. The original 36 artifact reviews and the seven C1 reviews are separate from those adequacy gates. The six-core table uses all three seeds, selects one common learning rate per core using mean development quality, and charges both learning rates plus relevant C1 phases. The chosen rate is .003 for each core; it is not the best seed or a held-out confirmation result. The quality target remains the predeclared .30; descriptive 300/900/1800 cuts are not new optimized thresholds.

The separate `c1-clock-outcomes-independent-review-v1` recheck recomputed the small-artifact metric/count/clock/table claims without repeating model inference. It verified 351 nonnegative early/late C1 intervals bounded by complete child-process wall, 43 confusion-matrix metric sets, exact first declared plateau epochs for all seven continuations, and six common-LR/all-candidate cost rows. The table's first-observed threshold times retain their original report-versus-epoch sampling convention; CURRENT now discloses that limitation. Native reviewers' exact fresh forwards are source-bound original claims, not forwards rerun by this delta audit.

C1 is explicitly an adaptive additional phase after the original cap observations. It adds no new seed, LR or diagnostic, inherits the original fit's actual remaining wall envelope, and can extend calendar time beyond the original 15,000-second campaign endpoint. The nine original workers are generic; no permanent three-baseline semaphore is claimed. Original dispatch uses `min(14400, remaining campaign time)`, so equal nominal limits are not reported as equal granted opportunities. Late dispatch and non-crossing observations remain censored. No original HCSN final checkpoint was reviewed for this subset. Lack of a saved resume-start checkpoint is disclosed: terminal optimizer/RNG invariants and implementation checks do not directly observe the pre-first-continuation-step restore.

The first strict clock review failed on all seven C1 records because the historical producer sampled elapsed time twice. That failure and its 22.93758828798309-second child process remain charged. The independent supplement preserves both raw clock samples, requires their ordering and outer bound, and passes the later value to the unchanged logical helper. It does not widen tolerances or modify original logs. The later single-clock producer fix has a separate source, draft PR and red/green regression; it was not used by historical C1.

## Cost provenance and pending status

The formerly unresolved native batch-32 failure now has original report, controller and process receipts. It completed zero optimizer updates, returned handled exit code 2 after a CPU allocator failure under an 8-GiB address-space limit, and is not described as an OS OOM kill. Its inner wall is 48.838508114917204 seconds, full process wall 52.01704302197322 seconds, and peak RSS 4,383,834,112 bytes. All three original v3 probes are retained and charged; the v6 micro4/micro8 originals replace a derived view of the same two runs without charging them twice.

The seven C1 continuations retain distinct overlapping scopes: 198.27188770193607 seconds of controller elapsed time, 499.411218 child CPU seconds including preflight, 492.04821365186945 summed attempt outer wall seconds, and 492.1036352769006 summed wrappers. They are not summed into calendar duration. Original final fit CPU excludes import/startup; cumulative per-epoch CPU and C1 phase samples are not retrofitted into an exact per-fit exit total. Independent audits, failed transport attempts, source/preflight validation and red/green tests retain their own costs. Energy, VRAM, complete historical provider costs and complete experiment totals remain unknown.

The frozen assets index has 16 verified assets and one incomplete official-data starter, with no metadata-only entries promoted to verified payloads. Starter 732265694 has null server digest, one upload ending HTTP408 and authenticated readback HTTP404; declared size is not verified uploaded bytes. No retry, replacement, deletion or publication is inferred from an embedded asset-list omission. The completed seven-chain archive is bound to its separate full-readback receipt. Two large independent-review aggregate RESULTs and three newer archive reconciliations were pending/excluded from this frozen snapshot; their later arrival can only be a separate appendix. This audit performs no fresh network readback.

## P1, C2, hardware and CI limits

P1 still separates recorded training states from supplemental final-model exports and finite schedules from indefinite repetition. The exact v8 recorder limit permits at most 1.2243% of sample-position-layer states over the minimum 30 epochs before its byte cap, not an observed retained count or random coverage guarantee. Content and complete-model identity are not reconstructed from the inner tensor digest. Old pressure failures remain and whole-training numerical admission stays HOLD.

C2 v2 closes the three independently demonstrated structural guard counterexamples using 21 synthetic tests; no native snapshot, runner or C2 training execution is claimed. Actual terminal checkpoint and resource eligibility remain pending. The prospective clock fix likewise confers no historical C1 source credit.

The actual native Xeon/AVX2 CPU FP64 attention worker reports CPU flash SDPA forward/backward with one Torch thread and one inter-op thread at 32-by-256-by-25 input, 8,134 valid events and an explicit causal mask. Its worker hash is bound to the controller and v8 source identity. It performed no optimizer step. Instrumented profiler/BLAS observations establish the executed path only; they do not prove GPU optimization, ordinary training speed, comparative energy or a particular assembly microkernel.

The hosted 92-test report remains tied to its recorded tested tree and old fixture source. CURRENT does not treat it as current all-source CI or the full repository's required workflow success. Source draft PRs and independent future clock publication remain separate from merge/main adoption. Scientific benefit, full HCSN numerical admission, real multimodal benefit and full repository CI remain unqualified.

The old width-16 index's final sentence describes what was unread “at indexing time.” Later asset receipts supersede that observation without erasing its historical meaning. A future convenience link could point to the newer receipt; this is not a blocking inconsistency.
