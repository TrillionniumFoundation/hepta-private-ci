# HPCA content grammar: independent zero-neural-update strong-control preflight

**Verdict: HOLD_NO_GO / no promotion.** This is an additional, read-only comparator for [HPCA routed-content #6172](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6172), not a replacement for its original real-model experiment. It never edits production Cell, PERC, MEM, PRED, CTRL, VERIFY, ACT, LEARN, StageOwner, candidate weights or permissions.

## Original frozen source and experiment

- Frozen model-experiment GitHub source commit: `b0ea141de2d5218869823b2d9e075db6d7b215dd` (tree identity reported by #6172: `132da19ad5829e38a3e96f304c061c0c4c96becf`).
- `TASKS.json`: SHA-256 `87a8caa9539642d7c0e0e0cd0b400b134a456e4565d01bf06521618471b31756`.
- `TRAIN_FEEDBACK.json`: SHA-256 `6eb1856e01ad94462b44d1fdcc6ee2a32d93801da45652eaef642d3d2e756de7`.
- `PLAN.json`: SHA-256 `b60ba8b2c4adc6556ef35d3115c5099b1a60f4d6f8a91634538c10e2b250fbdf`.
- This separate rule source was read back byte-for-byte from the first GitHub source commit `f22a53ed7af397dbd25025ee48739f0e716a5873` and matched the exact Python argument executed on the operator host. No evaluation-label content was passed to the process.

## Actual execution, not an estimated or proposed run

- Authenticated configured host: **ai395**; original durable process job `1a1ce94b459-2564-1706`. Exit **0**, no timeout, no cancellation, stdout fully retained (2849/2849 bytes), stderr 0 bytes. See [ORIGINAL_EXIT.json](ORIGINAL_EXIT.json) and [ORIGINAL_STDOUT.json](ORIGINAL_STDOUT.json).
- Executable `/usr/bin/python3 -c <exact published source>`; source in [rule_control.py](rule_control.py); exactly the same 3 frozen UTF-8 input files provided over stdin in a JSON envelope.
- Resource contract: CPU quota 100%, memory max 536,870,912 bytes, timeout 45 seconds. Recorded inside-process wall **0.00032439 s** for rule computation; total Python-process user CPU **0.007912 s**, system CPU **0.003956 s**, peak RSS **20,792 KiB**. These figures exclude host job admission, process startup beyond measured segment, input transfer, source authoring, model-data creation, energy, and production lifecycle; they are **not** a full resource-equated comparison with model training.
- Seven manually defined affirmative/adversarial fixture checks passed, including three prompt templates, cross-entity spoofing, cross-group invalid assignment, unsupported value, and trailing-answer injection. Source roster/hash/split checks also passed.
- **Training-only development:** 64/64 training answers agree with the deterministic fact/question grammar. **Content:** exactly 64 predictions produced, 32 `yes` and 32 `no`; prediction-map SHA-256 `514a42afa42e95078a5236fe26171b5f475dbd0a8533e35e2f49fe493e9ccf72`. These are predictions **not scored against evaluation labels**; do not call them 64 correct or a measured OOD gain. The additional 32 retention tasks are intentionally unsupported and not scored.
- Model calls **0**; optimizer calls **0**; parsed grammar examples **128**. This is an ordinary task-specific algorithmic competitor, not an instance of learned neuronal plasticity.

## Why this changes the next decision

The content prompts explicitly encode a record's color/shape and ask equality with a stated query. A source-bound deterministic parser can answer this narrow fixture with no parameter training, so model-only routed-versus-shuffled gains cannot by themselves establish a need for a neural mechanism. Once #6172's 16 frozen candidates and actual generation results are immutably archived, evaluate this **unchanged** grammar rule against the same content labels, fixed 64-task denominator, invalid-output policy and inclusive full costs; do not readjust it on development evaluation outcomes. Compare train/retention/OOD separately, and report capability-envelope differences when the parser abstains. Retain the normal-language LLM and contextual-gradient baselines; this narrow parser is an additional strong control rather than a substitute.

The rule had access to public question facts and the declared group ID, not evaluation truth. This alone does **not** establish independent future-B custody, human-relevant competence, common information economics across all tasks, owner NoUpdate/Adopt, cold recovery, or scientific efficacy. No existing completed smoke rerun. **HOLD_NO_GO / DENY_ALL**.
