# Frozen Qwen0.5B: credential wording / identifier-prefix factorial

Research-only on PR #1546, not a production Reader replacement or evidence
of learning, NDU recursion, FBSDE or Riccati benefits.

## Motivation from completed authenticated output

Exact archived [run 38321223762](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38321223762)
completed 320 new Qwen2.5-0.5B-Instruct calls with 160 original JSON
controls. The independently sealed [paired audit
38333136697](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38333136697)
replayed every one of the 240 original question-arm pairs on 60 synthetic
questions: under JSON **and** line-record evidence, **zero of 120
sufficiently evidenced responses was an exact correct answer**. In line
format ALL 120 were refusals; JSON single-fact was 60/60 refusals and
JSON two-fact was 23/60 refusals. All 120 insufficient conditions in
each view received appropriate exact refusals. Text formatting alone is
unqualified, and does not resolve over-refusal.

One possible *untested* mechanism: the fictional task asks for a
"clearance token", which may elicit conservative credential-related
behavior rather than a pure failure to bind a device to a source.
This trial tests a narrow **lexical sensitivity hypothesis**, not an
assertion about the Qwen safety policy.

## Exactly predeclared 2x2 source vocabulary intervention

Use original source generator indices **60:80**: 20 new but correlated
synthetic device/task worlds, outside previously exposed 0:60.
Each world has four fixed evidence arms: one target fact, target fact
plus one competing-token fact, one unrelated token fact, and no evidence.
Observable source selection runs on the original question/document bytes
with the gold answer REDACTED, *before* any output token/scoring label.

For every question-arm we run FOUR registered paired profiles:

| Profile | Relation description | Identifier |
| --- | --- | --- |
| credential_tok | clearance token | TOK-XXXXXXX |
| inventory_tok | inventory code | TOK-XXXXXXX |
| credential_tag | clearance token | TAG-XXXXXXX |
| inventory_tag | inventory code | TAG-XXXXXXX |

The lexical substitutions are applied consistently to the question,
ALL selected source facts, the generation-system instruction, and
the answer-format expectation. Source fragments acquire distinct
byte-bound identities; no source is silently omitted or rewritten
after prediction. Source selection does not consult the expected answer.
Original valid source scope/times are retained.

Total **20 worlds x 4 arms x 4 profiles = 320** NEW model calls.
The same externally SHA-pinned original Qwen2.5-0.5B-Instruct revision
`a338b55dd21219a5f4da42bc11a9313d1a27d4cc`,
original model inventory, tokenizer, greedy 64-token decoder and
1024-token input ceiling remain. The previously completed strong-Reader
archive is verified before loading or calling the model.

This intervention necessarily changes lexical tokens and prompt lengths;
therefore it is **not compute-matched** and any difference cannot be
attributed uniquely to a hidden refusal/safety mechanism. It also does
NOT measure broad natural-language, semantic citation or production
sufficiency.

## Response and cost adjudication

Store every attempt's start, status, exact source IDs, original answer
and model/source/token receipts in flushed and fsynced JSONL.
Seal ALL raw answers before post-hoc scoring. A failed or interrupted
call stays failed/unknown; it is never silently counted as a free
negative example.

Report individually:
- exact answer-only TOK/TAG correctness under either supported arm;
- exact refusal output on ALL arms and **over-refusal** under supported arms;
- correct refusal on insufficient arms and unsupported identifier copying;
- input/output tokens and measured decoder CPU/wall nanoseconds.

The **inventory_tag** profile is the only fixed primary candidate for
further independent testing: at least 15/20 supported exact answers in
EACH positive arm AND >=18/20 exact refusals in EACH negative arm.
Other profiles are diagnostic, not post-hoc model/prompt picks.
An observed pass would only support another independent confirmation,
not production authorization or NDU/FBSDE reasoning improvement.

The old Reader may fail for reasons unrelated to the word "clearance";
neither the existence of a prompt-like pattern nor a refusal is a
certificate of safety. Gold-answer string equality is an exact synthetic
grammar diagnostic, not independent human semantic evaluation.

## Reproduction

From the exact PR head, after using the historical archive and pinning
the unmodified Qwen tokenizer/safetensors inventory:

```sh
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
python scripts/memory_cell/system2_reader_lexical_factorial.py \
  /tmp/original-qwen.zip /tmp/pinned-qwen /tmp/factorial --development
```

The isolated GitHub workflow runs full MemoryCell tests, pinned Ruff,
the complete model/ZIP/source checks and the 320 registered calls.
It uploads full answers, raw SHA256 seal, source identity and failure
census; main and production paths are never changed.
