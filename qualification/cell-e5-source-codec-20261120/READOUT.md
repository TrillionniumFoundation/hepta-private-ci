# E5 source codec: completed representation measurements

The frozen implementation reconstructs all sixteen historical maintainer corrections exactly, but only one source meets the frozen visible-context and original token limits. The ordered E5 prefixes **1, 4 and 16 are all not representable under this implementation and the original bounds**. This is an infrastructure result; there is no new training run or measured learning improvement.

## Identity and prospective boundary

The five Draft stages are #6786, #6787, #6788, #6789 and #6790. The final prospective source/input freeze was published and independently read back at commit `bbb907067afa97ed61c0df8967de60f3196b683e` before the target runner read actual runtime-after bytes. Its `SOURCE_FREEZE.json` SHA256 remains `9b61e52fb89ff2ec06e9bd75db7c60971196488b79bfb1bd809d0c004f157e0c`; the eleven source modules and all sixteen contexts are unchanged. The original ordered source prefix remains `9dade6e90f6227dded45afa1c8462758a511a699`, with materials from #6783 at `63f494553a735bd55a3fef7cfe2e76604cd6db7d`.

Inputs come from the complete retained before-runtime scope and the original fixed task tests/fixtures. Some task test/fixture bytes originate in the upstream after revision because they were already used by the retained before native run. Runtime-after files and changed-file/changed-node information do not select visible inputs. All 290 original selected testcase identities and all their parameters are retained. The loguru input retains all 36 complete script/output fixtures required by its eighteen parameter choices. No prompt, target, parameter or required fixture was truncated.

## Actual reconstruction and coverage

All sixteen deterministic reference action payloads reconstruct the complete retained after-runtime map byte-for-byte, including all seventeen changed runtime files and the coupled Python/Cython pair. This structural check uses the full retained material map. Eleven payloads also succeed against the independently frozen visible-unit permission set. Five do not: loguru, parsimonious, backoff, marshmallow and cachetools reference a source unit outside that set. Those units were not added afterward. Every source also passed two actual tampering controls: changed source-root binding and changed before bytes were rejected, for 32 checks total.

The table uses the original zero-based source ordinal. `Visible edits` counts permitted target edit entries, not model successes. `Static closed` is the limited resolver contract described below. Every row passed the structural exact roundtrip; that fact does not override a visibility, static-contract or token-bound failure.

| Ordinal | Source | Visible edits / total | Static closed | Input tokens | Complete target tokens | Whole SFT positions | Static representation |
|---:|---|---:|:---:|---:|---:|---:|:---:|
| 0 | Delgan/loguru | 0/4 | no | 61,642 | 367 | 62,009 | rejected |
| 1 | SethMMorton/natsort | 1/1 | no | 4,290 | 141 | 4,431 | rejected |
| 2 | Textualize/rich | 7/7 | no | 9,083 | 856 | 9,939 | rejected |
| 3 | coady/multimethod | 1/1 | no | 6,978 | 127 | 7,105 | rejected |
| 4 | dbader/schedule | 1/1 | no | 6,498 | 229 | 6,727 | rejected |
| 5 | erikrose/parsimonious | 1/4 | no | 15,102 | 400 | 15,502 | rejected |
| 6 | jaraco/path | 1/1 | no | 10,224 | 145 | 10,369 | rejected |
| 7 | jawah/charset_normalizer | 4/4 | no | 75,705 | 300 | 76,005 | rejected |
| 8 | litl/backoff | 3/6 | no | 12,072 | 434 | 12,506 | rejected |
| 9 | marshmallow-code/marshmallow | 0/1 | no | 47,797 | 150 | 47,947 | rejected |
| 10 | pyparsing/pyparsing | 6/6 | no | 74,108 | 751 | 74,859 | rejected |
| 11 | python-attrs/attrs | 1/1 | yes | 1,277 | 138 | 1,415 | fits |
| 12 | python-humanize/humanize | 1/1 | no | 22,415 | 130 | 22,545 | rejected |
| 13 | python-jsonschema/jsonschema | 4/4 | no | 34,408 | 456 | 34,864 | rejected |
| 14 | tkem/cachetools | 0/2 | no | 6,205 | 185 | 6,390 | rejected |
| 15 | tox-dev/platformdirs | 2/2 | yes | 12,235 | 250 | 12,485 | rejected |

The complete native chat inference prefix is limited to 4,096 tokens; the complete SFT sequence to 3,584 positions; and the complete assistant continuation to 384 generation positions. The original 65,536-byte native message and 32,768-byte answer limits also remain unchanged. Target counts include the complete native assistant ending, with no output shortening. The full labels would mask every prefix token and retain every target token; this measurement performs no actual gradient update.

Fifteen inputs and fifteen complete SFT sequences exceed their original token bounds. Five outputs exceed 384 positions (rich 856, parsimonious 400, backoff 434, pyparsing 751 and jsonschema 456). Six prompts exceed the native message byte limit. All answer payloads fit the raw answer byte bound (266–2,931 bytes). Attrs alone fits the limited static contract and every representation bound, with 1,277 input tokens, 138 complete target tokens and 1,415 total positions. It remains at ordinal 11 and is not substituted into the prefix. Platformdirs is statically closed under v1 but its 12,235 input tokens exceed the bound.

`MEASUREMENT_READOUT.json` retains exact per-source rejection reasons, all original bound flags, edit coverage and missing unit IDs. `TARGET_READOUT.json` and `TOKENIZER_READOUT.json` are exact copies of their original measured result bytes.

## What was actually executed

The final before-only owner completed in 27.995708 seconds. After the GitHub freeze readback, the guarded target owner completed in 10.919592 seconds (target child 10.772037 seconds, self CPU 10.466194 seconds). The independent desktop tokenizer owner completed in 8.431660 seconds; its tokenizer child reports 7.459664 wall seconds, 11.567681 self CPU seconds and peak RSS 725,648 KiB. Owner and nested child times overlap and must not be added. Exact argv, timeout, terminal identity, stdout and stderr are retained.

Token counting used only the already frozen local tokenizer for Qwen/Qwen2.5-Coder-1.5B-Instruct revision `2e1fd397ee46e1388853d2af2c993145b0f1098a`, with the exact native template and special IDs. Its freeze SHA256 is `ee0b5f244964e7aaa69280310085d46a4a8d971075f3e655c86c6f6d61fe7aca`. The counter verified all six tokenizer/configuration file hashes and the frozen versions (Transformers 4.57.3, Tokenizers 0.22.2, Jinja2 3.1.6), then loaded the tokenizer locally with remote code disabled and offline network flags. It did not instantiate an AutoModel/Predictor or read weights. The original overlength tokenizer warning is retained in stderr; overlength sequences were counted completely and rejected, never run through a model.

All new model loads, forwards, generation calls, optimizer updates and upstream native task replays are **zero**. The existing E1/E2 56-call NoUpdate evidence, its two 32-update arms, the original E3 budget and both original E5 32-unit curves are unchanged. Unit-to-optimizer, compute/verifier, native-candidate and independent future-panel bindings remain null; `training_execution_admitted` is false for every row.

## Verification scope and limits

The assembled eleven-module implementation is 2,841 Ruff-formatted lines and is split into five reviewable Draft stages. It passed the unchanged original repository `just fmt` and `--check` in an isolated detached clone using the existing offline Ruff 0.15.13; each source AST was identical before and after formatting. All 24 combined synthetic boundary/tampering tests passed. Earlier prototype diagnostics and the actual failed synthetic invocation caused by two missing test imports remain in the previously published static-attempt archive. These checks do not prove all Python or Cython semantics.

`v1_static_context_closed` only means this implementation found no unresolved item inside its explicit static resolver contracts. It is not arbitrary Python semantic completeness, runtime correctness, native compilation or task success. External API assumptions remain named contracts; unsupported dynamic loaders, project receivers, metaclasses, class construction and module initialization effects lead to specific rejections. Conservative over-inclusion or rejection is possible. The five visibility failures and fifteen token-bound failures are results of this frozen implementation, not impossibility proofs for these upstream tasks or decentralized learning. No after-target result was used to modify visible inputs, reorder sources or select a replacement prefix.

There is no learned student action in this experiment: the reference actions are exact historical maintainer corrections used to verify the codec. Structural roundtrip, a limited static contract and matching hash digests do not establish model usefulness, multi-teacher complementarity, an unforgeable contribution proof or proof of useful work.

## Retained evidence

`MEASUREMENT_ARCHIVE.json` describes the split `measurement-originals.tar.xz` archive and every member. Reassemble the numbered parts in order, check each part hash and the full archive hash, then inspect the archive without executing contained code. The archive contains all sixteen complete target payloads, all target per-source/raw result files, the complete tokenizer request, the actual tokenizer results and owner receipts, native transfer receipts, and the prospective freeze publication/readback receipts. Every member was independently checked after local reassembly. The preceding `frozen-inputs` and `static-attempts` archives remain intact in the original freeze commit.

Measurement join SHA256: `64cd542ab7cf9792c3b19b70ea8624bf79fc94cf6a4a694ae0b967bb3b6f915c`. Target result SHA256: `e5f5ee55da86c539e979166e1a289b994107f596bea38aa1982b1c01f641b211`. Tokenizer result SHA256: `c52ccbc597eff51027f79bb1c5de8da98392465d9c3d79f2cf139d590d0b4136`.
