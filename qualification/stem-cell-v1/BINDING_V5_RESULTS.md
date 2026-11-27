# V5 results: binding learning improved, full-fit admission still failed

The frozen 97M Granite token representation and unchanged 38,466-parameter
Reader learned most controlled two-hop ownership/storage bindings. None of the
three seeds passed the preregistered full128 fitting gate. Natural continuation,
feedback training and fresh evaluation therefore remained closed. This run
provides no new evidence of NDU reasoning gains or multimodal transfer.

## Actual training results

All seeds used the same 32 paired-world training groups, complete-group batches
of 16, depth three, final-hop CE plus .5 paired-world margin, and Adam at .001.
Each ran the full 8,000-update budget (128,000 candidate exposures per seed).
These are final checkpoints, not the best observed diagnostic checkpoints.

| Seed | Correct / 128 | Both worlds / 64 | All four / 32 | Saved-probability CE | Fit CPU seconds | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 41 | 122 (95.31%) | 59 (92.19%) | 29 (90.63%) | .066152 | 121.576 | Failed |
| 47 | 125 (97.66%) | 61 (95.31%) | 30 (93.75%) | .032511 | 124.016 | Failed |
| 53 | 125 (97.66%) | 62 (96.88%) | 30 (93.75%) | .033289 | 130.322 | Failed |

The fitting gate requires 100% candidate and paired-world correctness and
CE <= .10 at a scheduled training-only diagnostic. No seed met it. At the first
250-update diagnostic, accuracies were already 96.88%, 97.66% and 96.09%.
The subsequent trajectories include plateaus and transient collapses. A larger
update budget did not make this recipe reliably solve the entire training set.
Seeds repeat the same examples; they are not 384 independent held-out cases.

A separate, earlier development probe applied the original V4 training recipe
to the complete 128 training candidates without natural-task mixing. At 1,000
updates it finished at 50% accuracy and probability CE .693412. This comparison
changes sampling, loss, supervision and budget together; it cannot identify
their separate causal contributions or establish an equal-cost advantage.

The synthetic-only warmups were also scored on the old 827-candidate natural
internal tune: F1a .4752/.4712/.5464 and EM .0773/.0412/.0619. These are exposed
training-source diagnostics, not new natural generalization. The warmups did
not start from natural-trained Readers, so this is not a forgetting estimate.

## Representation and resource evidence

A separate non-neural diagnostic checked the existing training cache only.
All 128 cases had distinct exact signatures, both before and after the Reader's
LayerNorm, modulo its known token/fact permutation invariances. The longest
fact had 11 content tokens, below the 62-token payload; no controlled fact was
cut by chunking. This rules out exact input collisions on this finite training
set. It does not prove efficient learnability, rule out collisions after the
learned rank-32 projection, or establish the best Encoder choice.

| Measured scope | CPU seconds | Wall seconds |
| --- | ---: | ---: |
| Preparation child, startup through exit | 3.396 | 2.521 |
| Warmup child, startup through exit | 400.315 | 399.594 |
| Three fit calls, nested in warmup | 375.914 | Recorded per call |
| Six physical inference panels, nested in warmup | 12.515 | Recorded per batch |
| Non-neural cache diagnostic, separate child | 3.377 | 2.639 |
| Final independent raw audit, separate command | 5.512 | Recorded in receipt |

Use the first two rows for the incremental experiment total: 403.711 CPU seconds
and 402.115 wall seconds. Do not add nested fit, diagnostic or inference costs
again. The warmup child's peak RSS was 1,168,744 KiB (about 1.115 GiB), including
the frozen Encoder load, cached features and runtime. V4 cache generation is
historical, not newly performed encoding. No new fresh-domain encoding occurred.
Complete formula FLOPs and individually measured case latencies are unavailable.

## Independent verification and limits

The stdlib auditor verified all three weight files, training receipts, complete
binding panels and natural internal panels; it rescored 99 diagnostic probability
arrays and checked 75 input files before/after auditing. All 48 runtime files
match the prepared design. It independently obtained the same three failed
gates and checked that later-phase start/completion artifacts do not exist.
Audit PASS means evidence consistency, not learning qualification. Weight-file
bytes are independently checked; tensor digests and hardware clocks are not
independently reconstructed or attested.

The first partial audit exposed a numeric definition error: logit-space CE at
one diagnostic was .837835, while CE reconstructed from saved FP32 softmax
probabilities was .838083. The independent auditor now keeps these quantities
separate, retains the reported logit loss without pretending to reconstruct it,
and recomputes all canonical probability scores and gates. This did not change
the frozen runtime, training, weights, probabilities or gate. Its failed receipt
is retained. A later audit invocation with an incorrect process-receipt path
also failed before scoring; that receipt is retained too. No neural run was
repeated for either audit correction.

After the audit fix, all 499 local tests passed, including the supplied native
NDU control/replay binaries. Repository formatting completed. Hosted CI was
not consulted; no official validation JSONL was read or scored; no merge or
production promotion occurred.

## Next controlled implementation target

The evidence supports investigating cross-fact readout and optimization before
copying larger encoders. One small candidate is a rank-32 single-head residual
fact-to-fact bridge, about 4,096 weights, compared with an equally enlarged
ordinary Head under the same frozen sampling plan. A separate feature experiment
could jointly encode the four short facts to isolate cross-sentence context,
with a new feature version and measured Encoder cost. These are proposals,
not results from this run. They should be compared separately, then pass the
full-fit gate before the already implemented continuation and feedback paths
are admitted.
