# HPCA native greedy diagnostic: complete retained negative result

Execution source: `0b75caf446a18807e527f8e2ed9937ae3cae515d`.
Native job: `1a1cd370436-2564-121a`, succeeded, exit 0.
The same ai395 host loaded the original base model and all eight retained adapters.

## Observation

The frozen 24 public operator OOD prompts were evaluated under nine conditions:
base and interleaved/bursty adapters for seeds 11, 17, 23 and 29.
All **216 generation attempts emitted exactly token [2], native EOS**, producing
empty decoded text. Each condition therefore had **0/24 valid leading YES/NO
responses and 0/24 correct responses** under the frozen parser.
The allowance was at most eight generated tokens with native EOS stopping.
These remain 24 distinct public tasks, not 216 independent tasks.

No model training or new two-choice scoring was performed in this run.
Each row's two_choice_prediction is the frozen historical reference.
No label inversion or fitted threshold was used to reinterpret the exposed B2.

## Retained originals and review

RESULT.json contains all 216 raw rows (103557 bytes, SHA256
`90f8025d20df63aa2be140b4f5b8f688d538e16b3e96a783e58b1d0c88d5c61e`).
RESULT.json.evidence/ROWS.jsonl contains all 433 records (120807 bytes, SHA256
`ceebabbcc323247c9afe2065f9f3be0fea7e09e2e261106cf524bf235c043e04`):
216 starts, their 216 adjacent completions and the final rows_complete record.
The result and journal were transferred with fixed file versions and checked
against their original whole-file hashes.

PREEXECUTION, launch/exit records, GNU time output, model stdout/stderr,
39-test raw logs, native terminal status and the original 13-file MANIFEST
are also retained byte-for-byte. Every MANIFEST entry was verified after
transfer. The original manifest predates README and itself; it is not a claim
to cover every later review or publication file.

A separate agent in this same session independently recomputed all condition,
task, family, truth, score and source/input bindings, then checked the journal
sequence, unique start/completion pairing, exact row equality and single terminal
record. RAW_REVIEW.json records that scope. This is consistency review of
operator-held evidence, not external custody or independent task sampling.
ARCHIVE_README_ORIGINAL.md preserves the earlier native summary before review.

## Runtime, cost and validation

Runtime was Python 3.14.4, torch 2.9.1+cpu, transformers 4.57.3 and peft 0.18.0,
with four CPU threads and original model/adapter identities in PREEXECUTION.
Its resolved is_assistant field was false.

The measured phase was 10.227863733889535 seconds wall and
33.180033789 seconds process CPU, excluding imports, tokenizer loading and
initial hashing. Outer GNU time measured **13.65 seconds wall, 35.08 seconds
user CPU and 1.04 seconds system CPU**, with a lifetime peak of 1207508 KiB.
The wrapper wall measurement was 13.696691853925586 seconds.
Outer process timing includes startup but excludes model acquisition, remote
control, evidence retrieval and energy costs. Peak RSS is not additive across
conditions. Invalid one-token outputs provide no useful-output efficiency claim.

The actual 0b75 source passed 39 targeted native tests and its exact-source
PR workflow completed successfully (run 43128297832). Successor source
1609fa0c45c723fccc541e773967dc26a913c47a adds is_assistant=False and one
counterexample test; its 40-test workflow was still queued at this archival
observation. The 216 model attempts were not rerun with the successor.
just fmt was not executed because neither just nor the native sparse
worktree's codex-rs/justfile was available.

The first native git archival operation remains UNKNOWN because no terminal
receipt was delivered. Its ordinary push cannot overwrite the newer branch.
This GitHub API archival transfer is complete; it did not replay model inference.

Independent calibration, future sources and old-task retention remain MISSING.
HOLD_NO_GO / DENY_ALL; no independent efficacy, production adoption or energy claim.
