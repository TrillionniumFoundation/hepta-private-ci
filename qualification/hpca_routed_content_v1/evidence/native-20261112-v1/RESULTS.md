# Native routed-content experiment: completed, efficacy not established

The frozen experiment actually performed 64 SmolLM2 training prefills, 4096
manual SGD update slots, 1632 unrestricted main generations and 204 fresh-process
checkpoint generations. Every planned generation completed; there were no
generation exceptions. All 204 cold outputs matched their original tokens,
decoded text, frozen feature hashes and first-token head shifts exactly.

The efficacy result is negative. Across the four predeclared seeds, correctly
routed feedback scored 46.875% mean content accuracy, compared with 46.09375%
for shuffled feedback and 50% for the unchanged base. The routed-minus-shuffled
correct-count differences were -2, 0, 0 and +4 on the same 64 questions. These
results do not demonstrate a consistent content improvement. No seed was selected
as a winning candidate and no training setting was changed after scoring.

Decision remains **HOLD_NO_GO**, with **independent_future_B=false**. This is a
separate content-head development experiment, not a result from the old eight
adapters or their separate 624-generation protocol.

## Immutable source and original execution

Executed source: `b0ea141de2d5218869823b2d9e075db6d7b215dd`.
Tree: `132da19ad5829e38a3e96f304c061c0c4c96becf`.
All seven runtime/data files were read back from GitHub before execution and
matched the native source bytes. The earlier prepared commit
`878faaba7388bc679027c0af34203192e8a3f319` was never executed; a separate reviewer
found a paraphrase-template/label confound and the frozen successor fixed it
before any model call. Each content group/template contains eight YES and eight
NO labels.

Main job on `ai395`: `1a1ce85599c-2564-16db`.
Cold job on `ai395`: `1a1ce8f4634-2564-16ee`.
Both original jobs have exit code 0, complete durable logs and confirmed terminal
publication. A delayed cold-start acknowledgement was reconciled under its
original idempotency key with `reused=true` and `retried_launch=false`.

| Original | SHA256 |
|---|---|
| Main `RESULT.json` | `0bd8a380cd565fc76b42bc184357c14d25f030b69286769d0863af68819e7e2b` |
| Cold `RESULT.json` | `9b42ff62fc3c1fb1b1daf56b523ee86c2d67362c7e1ac94b681321569183be56` |
| Complete native archive | `7f04348e9d74a705fad8a707d39befb49720e6cc7ea69fe1fee587d499c04bda` |

`native-originals.tar.xz` contains 71 original files plus the manifest: complete
main/cold result rows and append-only attempt journals, every one of the 17 head
checkpoints, all 16 training receipt files, the real frozen training features,
source/data, original job requests/stdout/stderr/exit records, and independent
token decoding of all 1632 main outputs. Every archived file was checked by both
size and SHA256 after full readback. The six large pretrained model/tokenizer
assets are retained by their existing native paths and frozen hashes in PLAN
and PREEXECUTION; the large pretrained weights are not duplicated here.

## Training and generation that actually occurred

The 135M model body and original LM head remained frozen. Two private linear
heads used the real last hidden state plus a bias feature. Their learned scalar
shift changes the first generated token's Yes and No logits with opposite signs.
Every vocabulary item still competes in greedy decoding. Later tokens use the
original LM head, with the preregistered eight-token limit and natural EOS.
Extra words and malformed answers remain invalid and incorrect.

Correct and shuffled arms received the identical ordered two-coordinate external
feedback vector, initialization, training examples, permutation schedule, learning
rate, architecture and update opportunities. The shuffled arm swaps coordinates.
The group follows color versus shape task domain, never the expected answer.
Action-time features and probability expectations are consumed three paired-action
sequence steps later. This is an experimental sequence delay, not a biological
or real-time timing claim.

No-eligibility zeroes the trace. Scalar takes the vector mean and changes its
information content; it is reported as a separate ablation, not an only-routing
comparison. There were 4096 manual update slots, including 1024 no-eligibility
zero-update slots, and 3072 nonzero updates. Torch optimizer calls and body weight
updates were both zero. This is actual native content-head training, not full LM
or LoRA retraining. The cold run reloads checkpoints and repeats inference; it
does not rerun training.

All 16 trained candidates were written and frozen before evaluation labels were
parsed or used for scoring. The evaluation file bytes were hashed earlier for
identity. Tasks and labels were operator-authored and investigator-visible; this
does not establish sealed or independent evaluation custody.

## Content and retention results

Every table cell is **correct / valid / total**, with invalid answers included in
the total. The base has content `32 / 64 / 64` and retention `8 / 14 / 32`.

| Seed | Arm | Content | Retention |
|---|---|---:|---:|
| 11 | routed | 27 / 56 / 64 | 6 / 9 / 32 |
| 11 | shuffled | 29 / 58 / 64 | 5 / 10 / 32 |
| 11 | no eligibility | 32 / 64 / 64 | 8 / 14 / 32 |
| 11 | scalar | 24 / 50 / 64 | 4 / 9 / 32 |
| 17 | routed | 32 / 64 / 64 | 9 / 15 / 32 |
| 17 | shuffled | 32 / 64 / 64 | 9 / 17 / 32 |
| 17 | no eligibility | 32 / 64 / 64 | 8 / 14 / 32 |
| 17 | scalar | 32 / 64 / 64 | 10 / 18 / 32 |
| 23 | routed | 24 / 50 / 64 | 3 / 7 / 32 |
| 23 | shuffled | 24 / 50 / 64 | 3 / 5 / 32 |
| 23 | no eligibility | 32 / 64 / 64 | 8 / 14 / 32 |
| 23 | scalar | 24 / 50 / 64 | 3 / 5 / 32 |
| 29 | routed | 37 / 63 / 64 | 8 / 14 / 32 |
| 29 | shuffled | 33 / 64 / 64 | 8 / 14 / 32 |
| 29 | no eligibility | 32 / 64 / 64 | 8 / 14 / 32 |
| 29 | scalar | 32 / 64 / 64 | 8 / 14 / 32 |

| Arm | Four-seed mean accuracy | Correct observations | Valid observations |
|---|---:|---:|---:|
| routed | 46.875% | 120 / 256 | 233 / 256 |
| shuffled | 46.09375% | 118 / 256 | 236 / 256 |
| no eligibility | 50% | 128 / 256 | 256 / 256 |
| scalar | 43.75% | 112 / 256 | 228 / 256 |

The 256 observations per arm are four evaluations of the same 64 content tasks,
not 256 independent tasks. The source has 64 content `source_cluster` strings
and 32 predeclared two-channel pair blocks. Retention has 32 deliberately reused
development questions from #6132, in 16 source clusters. No new independent
task count, significance claim or future-data claim is inferred from repeated
seeds or cold generations.

The base fails the predeclared retention competency gate of at least 24 correct
and 28 valid answers out of 32. Retention adequacy cannot be claimed from these
comparisons.

## Paired routing and invalid outputs

| Seed | Routed only correct | Shuffled only correct | Both correct | Neither correct | Routed invalid | Shuffled invalid |
|---|---:|---:|---:|---:|---:|---:|
| 11 | 27 | 29 | 0 | 8 | 8 | 6 |
| 17 | 0 | 0 | 32 | 32 | 0 | 0 |
| 23 | 0 | 0 | 24 | 40 | 14 | 14 |
| 29 | 5 | 1 | 32 | 26 | 1 | 0 |

The +0.78125 percentage-point descriptive mean routed-minus-shuffled difference
coexists with a worse routed mean than the unchanged base. Seed 11 also changes
which questions are correct almost completely; aggregate counts alone conceal
this. `PAIRED_ROUTING_ORIGINALS.json` retains every paired text, token list,
validity and correctness flag for all content and retention tasks in all seeds.
The four no-eligibility conditions reproduce all 384 corresponding base rows
exactly.

## Independent readback and recovery

`audit_originals.py` does not import the experimental credit implementation.
It verifies original result pins, all seven source pins, model asset pins, frozen
candidate identity, complete started/completed journal pairs and fixed
denominators. It independently parses and scores every output. Using standard
Python arithmetic, it replays all 4096 recorded delayed update steps from the
real cached features and training labels, checks eligibility hashes and state
chains, and compares the final head arrays. Maximum final weight error is
`5.551115123125783e-16`; maximum recorded coefficient error is
`5.773159728050814e-15`, both below the explicit `1e-9` arithmetic check tolerance.
This arithmetic check makes zero new model calls and is not additional training.

Cold `all_exact=true` is independently recomputed from the 204 complete original
rows, with zero failed generations. The 204 repeat the frozen 12-task subset over
all 17 checkpoints; they are not 204 new evaluation tasks. A separate tokenizer
readback also decodes all 1632 original token lists to their exact recorded text.

The contract CI run `43170663105`, job `131022899779`, completed six tests with
zero skips. Its checkout was the PR synthetic merge
`e45cdac42c65ed0363f8b06a69b6621261df5696`, which merges the executed source into
the frozen base. Those contract tests are not counted as native model execution.

## Measured costs and reproduction

| Run | Attempts / completed / failed | Wall seconds | CPU seconds | Peak RSS KiB | Generated tokens and generation forward calls |
|---|---:|---:|---:|---:|---:|
| main | 1632 / 1632 / 0 | 279.655604 | 1015.173847 | 1138232 | 5749 |
| cold | 204 / 204 / 0 | 27.281654 | 90.378344 | 1136512 | 408 |

Main additionally used 64 real training prefills (5.193348 seconds) and 0.223677
seconds of manual head updates. Reported run costs exclude source preparation,
queue/transport waiting, prior model training, energy and Owner lifecycle.
Transport timeouts were retained and reconciled; no unknown model job was
duplicated. Archive transfer eventually used the existing authorized desktop SSH
route and authenticated `ProfHepta` GitHub CLI to publish immutable blobs. The
full GitHub readback agrees with the six already received h transport chunks.

To inspect all original files and repeat the read-only arithmetic audit, from the
repository root:

```sh
mkdir hpca-originals
tar -xJf qualification/hpca_routed_content_v1/evidence/native-20261112-v1/native-originals.tar.xz -C hpca-originals
python qualification/hpca_routed_content_v1/audit_originals.py \
  --main hpca-originals/main --cold hpca-originals/cold --source hpca-originals/source \
  --main-sha256 0bd8a380cd565fc76b42bc184357c14d25f030b69286769d0863af68819e7e2b \
  --cold-sha256 9b42ff62fc3c1fb1b1daf56b523ee86c2d67362c7e1ac94b681321569183be56
```

Native HPCA integration, a real content-kernel × NDU 2×2, independent future
evaluation, production ownership, adoption and energy benefit remain unproved.
The negative result and all original checkpoints are retained for subsequent
research; this evidence does not authorize promotion.
