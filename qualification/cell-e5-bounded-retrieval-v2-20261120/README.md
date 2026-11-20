# E5 bounded retrieval v2: complete encoding fits; original static admission stays closed

## Result

One frozen before-only policy produced 15 whole-unit byte views from the original 16 sources. All 15 complete native chat prefixes fit 3,200 tokens. Eight complete original maintainer corrections are expressible inside those exact views; seven also fit every original byte/token bound. The eighth, rich, needs 622 continuation tokens and fails the original 384 limit. Seven other sources lack at least one complete edit owner in the selected view. jsonschema retains its original mandatory-unit overflow refusal, with no v2 prompt or runtime-after read in this phase.

The ordered 1-source prefix has complete action encoding within byte/token bounds. The 4- and 16-source prefixes do not. The original static representation counter remains false for every source and every prefix, and every training-execution prefix stays false. These are source/action measurements, with zero new model loads, forwards, generations, gradient updates or upstream native replays. They are not learned successes, proof of useful work, or an agent trajectory.

The original v1 negative results at 148e37c26586677e83f0e57e100def8805c1a020 remain unchanged. The original source prefix 9dade6e90f6227dded45afa1c8462758a511a699 and 290 native testcase identities/fixtures are retained. No source was reordered or substituted.

## Full fixed-source readout

| Ordinal | Original source | Prefix tokens | Full action+EOS tokens | SFT positions | Decision |
|---:|---|---:|---:|---:|---|
| 0 | Delgan/loguru | 2851 | 236 | 3087 | COMPLETE_ENCODING_AND_TOKEN_BOUNDS_FIT |
| 1 | SethMMorton/natsort | 2539 | — | — | TARGET_SCOPE_REFUSAL |
| 2 | Textualize/rich | 1546 | 622 | 2168 | COMPLETE_TARGET_TOKEN_REFUSAL |
| 3 | coady/multimethod | 1335 | 81 | 1416 | COMPLETE_ENCODING_AND_TOKEN_BOUNDS_FIT |
| 4 | dbader/schedule | 1468 | 181 | 1649 | COMPLETE_ENCODING_AND_TOKEN_BOUNDS_FIT |
| 5 | erikrose/parsimonious | 1305 | — | — | TARGET_SCOPE_REFUSAL |
| 6 | jaraco/path | 513 | 95 | 608 | COMPLETE_ENCODING_AND_TOKEN_BOUNDS_FIT |
| 7 | jawah/charset_normalizer | 2676 | 170 | 2846 | COMPLETE_ENCODING_AND_TOKEN_BOUNDS_FIT |
| 8 | litl/backoff | 2597 | — | — | TARGET_SCOPE_REFUSAL |
| 9 | marshmallow-code/marshmallow | 1729 | 104 | 1833 | COMPLETE_ENCODING_AND_TOKEN_BOUNDS_FIT |
| 10 | pyparsing/pyparsing | 2826 | — | — | TARGET_SCOPE_REFUSAL |
| 11 | python-attrs/attrs | 2986 | — | — | TARGET_SCOPE_REFUSAL |
| 12 | python-humanize/humanize | 2132 | 78 | 2210 | COMPLETE_ENCODING_AND_TOKEN_BOUNDS_FIT |
| 13 | python-jsonschema/jsonschema | — | — | — | SOURCE_REFUSAL |
| 14 | tkem/cachetools | 727 | — | — | TARGET_SCOPE_REFUSAL |
| 15 | tox-dev/platformdirs | 1690 | — | — | TARGET_SCOPE_REFUSAL |

Loguru illustrates the measured change: its complete before-only selected method and original failing task produce a 2,851-token native prefix. All four original edits form a 236-token complete compact response including the native suffix/EOS; the full SFT sequence has 3,087 positions. This is complete encoding and length evidence only; original static admission remains false. The natsort refusal remains at ordinal 1, so it blocks the 4-source prefix even though its input fits. Attrs, the single v1 static success, is a v2 scope refusal; this uniform candidate does not improve every source.

## Frozen execution order

The policy/API intent was frozen locally before implementation. Sixteen synthetic source/edit controls passed, then the original repository formatter and check passed on desktop with all ten Python ASTs unchanged. The exact formatted source and original 16 positions were frozen before one before-only retrieval pass. All 15 prompts and the jsonschema refusal were read back. The original Qwen tokenizer then measured exact complete native prefixes without changing them.

Only after those inputs were fixed was an independent target policy and implementation frozen. Six synthetic target controls passed; the original formatter/check preserved all three ASTs. One separately owned pass read original runtime-after material for 15 records, generated the complete original v1 reference edits, checked full-runtime byte reconstruction, required every edit owner in the frozen view, and checked the complete compact action reconstructs the same runtime. Missing owners cause whole-target refusal; no edit is dropped. jsonschema is not reopened. The original tokenizer then counted every complete covered action including the full envelope and EOS.

All source/test controls ran before their corresponding formatter. Per repository instructions, tests were not rerun after formatting; AST equivalence and exact formatted-byte input/source freezes are retained. Neither control suite imports or executes upstream tasks. Independent source reviews record their actual timing relative to the owner, and do not claim to have run tests or inspected model outcomes.

All fifteen prefixes were byte-identical and token-ID-identical between the input-only and full-target counts. The retrieval policy, original input code and sixteen-row freeze were checked unchanged after target exposure. No future B/C data was read.

## Why the original counter still reports false

The unchanged original `count_tokens.py` lines 102–113 require `v1_static_context_closed`, full reference roundtrip, visible-action roundtrip, and all five original byte/token checks. This partial-view v2 producer explicitly sets `v1_static_context_closed=False` in `run_targets.py` line 188. That unresolved gate makes every original `static_representation_admitted` value and every original static prefix false, including loguru. Rich additionally fails the 384-token continuation limit. No original false is relabeled as acceptance.

The optimizer-unit, compute/verifier and B/C fields are separate null fields at original counter lines 137–139; they are not operands of that static `all()` expression. Training admission is initialized false at line 76 and never enabled. The separate seven-source and prefix-1 observations here mean only **complete action encoding and token bounds fit**.

`MEASUREMENT_READOUT_3.json` in the archive adds this explicit gate breakdown and supersedes the earlier derived readout's ambiguous `v2_representation_admitted` field name. Readout 2 is preserved as an earlier interpretation; no source, input, target, original counter or experimental result was changed.

## Bounds and unresolved gates

The original 4,096 input-token, 3,584 SFT-position, 384 continuation-token, 65,536 native-message-byte and 32,768 answer-byte bounds remain unchanged. The separate v2 prefix reservation is 3,200 full-template tokens. Counting uses the exact original Qwen2.5-Coder-1.5B-Instruct revision 2e1fd397ee46e1388853d2af2c993145b0f1098a, six frozen tokenizer assets, original package versions, template, special IDs and counter source. No approximate tokenizer or truncation was used.

The compact format is `[2, view_digest, edits]`; each edit contains the already visible runtime ordinal, operation, original line bounds, and complete replacement text. Independent expected-view authority and exact before bytes are mandatory. The hash DAG is payload→view digest→rendered prompt→outer prompt hash. Internal hash consistency does not prove a caller supplied authentic before material.

The AST counter covers lexical analysis walks, not all v1 inventory/bind parses. Time limits are checkpoint checks during retrieval; physical loading has separate byte/call caps. Logged blob bytes are successfully verified reads, not a general account of attempted I/O after corruption. The successful runs had no hash-read failures. This is not a hostile-input total-cost proof or production context integration.

The original 32 fixed-total and 32-per-source curves are unchanged. An executable optimizer-unit mapping, training forward/MAC allowance, verifier allowance and independent future B/C tasks remain null. The 64-source point lacks 48 original source materials. No production authority, reward or issuance policy is added.

## Actual cost windows

| Operation | Actual scope | Wall seconds |
|---|---|---:|
| Input preparation | Sum of 16 record windows, excluding outer startup |4.966112|
| Original formatter/check for v2 input code | Independent desktop owner |1.517263|
| Prefix tokenizer | Independent desktop owner |7.908531|
| Original formatter/check for target code | Independent desktop owner |1.048795|
| Target preparation | Independent cloud owner |7.747104|
| Complete-target tokenizer | Independent desktop owner |7.485123|

Parent and child windows are nested and must not be added together. The full-tokenizer child used 5.593275 CPU seconds with peak RSS 707,268KiB. Source preparation, tokenizer work, repository validation and training costs are separate; no training cost is inferred from these numbers.

## Evidence

`EVIDENCE_MANIFEST.json` binds every member of the complete original archive. The three `COMPLETE_ORIGINALS.tar.gz.part-*` files reconstruct the original `COMPLETE_ORIGINALS.tar.gz` by ordered concatenation and its recorded full SHA256. This complete archive retains all prospective policies/freezes, exact source bytes, original 16 views/refusal, source-only controls, formatting owners/results, all complete reference/compact targets and scope refusals, both exact tokenizer requests/results, independent reviews, and metadata corrections. No failed or refused source is removed. Full readable reports inside the archive are `MEASUREMENT_READOUT_3.json`, `READOUT_INPUT_1.md`, `COST_AND_TRUST_ADDENDUM_1.md`, and the independent review files.

The exact source, input and result identities are also provided in `BINDINGS.json`. Local prospective freezes are explicitly marked public_commit:null; this later Draft publication is not represented as having preceded the local measurements. No merge or production activation occurs.
