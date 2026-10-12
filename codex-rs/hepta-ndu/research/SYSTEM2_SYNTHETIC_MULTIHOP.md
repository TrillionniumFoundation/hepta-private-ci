# Synthetic English multi-hop evidence and frozen Reader experiment

Research-only stack on #1546. **No production promotion, new NDU runtime, duplicated Encoder, or claim of learned reasoning emergence.** The preceding CPU studies operate on exact arithmetic; this intentionally tests a different boundary: whether obtaining a complete multi-document *natural-language* evidence chain improves a **fixed** Reader's actual raw answer.

## Fixed corpus and guardrails

`system2_multihop_evidence.py` deterministically constructs 20 **fictional** cases (ten two-hop, ten three-hop), each with 11–13 short English source documents. The task is to follow project -> (unit ->) device -> clearance token. Three distractor chains share the vocabulary, and five cases include a quoted adversarial instruction among the sources. Question identity, source scope, timestamps and document hashes are stable. Code-like entity IDs are pseudo-randomly derived from distinct domains; the correct token cannot simply be derived from the queried project ID. This is **generated controlled text**, not independent human-authored or adjudicated knowledge. Related tasks share grammar, so success cannot establish open-domain transfer.

The generator's expected outcome is checked against an independently implemented, typed grammar join; deleting **each** critical premise must break the only path. That programmatic check is a synthetic integrity assertion, **not** an independent human sufficiency judgment. Target fields are never supplied to online selectors or the Reader. A test changes the target field and confirms every selected document stays identical.

All methods consume exactly the same admitted documents, pinned Reader and prompt/decoding settings, with at most three full original-source spans (no shortening or citation rewriting). They differ only in selected documents:

| Arm | Meaning |
|---|---|
| `no_evidence` | Zero-evidence Reader/abstention control |
| `bm25_top3` | Deterministic weighted lexical retrieval, no learning |
| `lexical_top3` | Frozen unweighted lexical retrieval |
| `joined_top3` | Deterministic grammar-based two-/three-hop relation traversal (positive *algorithmic* sufficiency control) |
| `premise_removed` | Remove one necessary premise from the joined chain, fill with distractors to keep exactly three excerpts |

Except for the intentionally empty control, the source count is fixed to three. Document lengths and **actual Reader tokens/CPU latency still differ**. Counts are not FLOPs; no padded compute is claimed equal. The typed join is a narrow executable text parser, not a learned neural capability or general NDU value policy. It scans the same bounded document corpus and cannot consult generated targets. Actual selector corpus bytes and every Reader receipt are recorded.

## Real-model runner and output boundaries

`system2_multihop_trial.py --development` loads the **unchanged pinned** `FrozenBundleReader` from `bundle_reader.py` using the existing `READER` inventory, same immutable system prompt, maximum generation, tokenizer and no model updates. It constructs real `EvidenceBundle`/`EvidenceSpan` objects bound to original UTF-8 bytes, time, scope and document identity. Empty evidence is still passed to the Reader: output is not forced to abstain. No prompt is built with the answer, expected token or critical-source labels. Each raw answer, actual token counts, selected source IDs, source manifest and failure is fsynced. Every planned question/arm has a row. Source identity and the `raw-answers.jsonl` SHA256 are sealed **before** scoring.

Post-seal diagnostics are strictly template-bound: exact unique clearance token, syntactically valid citation labels, all required sources cited, and exact fixed abstention text where the selected set lacks a complete path. These are **not** independent semantic citation precision, general answer correctness or human refusal decisions. Missing model invocations are failures, never imputed as wrong/correct. The literal natural language results are preserved without rewriting.

## Acceptance and limits

The frozen corpus precheck must show 20/20 complete joined chains and 0/20 complete critical-deletion chains. The real Reader's all-arm rows, proof of frozen parameter identity, and the complete source and token manifests must pass without dropped failures. An advantage in exactly-supported answer/citation outcomes over frozen BM25 is **only a synthetic, fixed-model retrieval diagnostic**, and a subsequent untouched external natural-language benchmark with independent human-reviewed sufficiency is required before it can qualify Hepta MemoryCell or SYSTEM2.

The hosted workflow installs the existing pinned CPU model environment, runs the entire MemoryCell Python regression and static checks, retrieves the unchanged exact historical model archive by pinned ZIP SHA, extracts only Reader files with safe tar paths, verifies the frozen Reader inventory, then records all raw outputs and source hashes. It is not a deployment gate and never modifies the original Reader. A queued or merely generated workflow is **not an observed model result**.

## Reproduce

```sh
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
python -m unittest discover -s scripts/memory_cell -p 'test_system2_multihop.py' -v
python scripts/memory_cell/system2_multihop_trial.py /path/to/verified/memory-inputs/reader /new/output --development
```

This first step tests the necessary retrieval-versus-Reader opportunity before introducing recurrent Cell learning, Riccati or FBSDE into a language task. No such numerical-solver gain is claimed here.

## Follow-up: quoted-instruction stress with sufficient and missing evidence

This additional experiment is strictly paired and reuses the original 5 three-hop
attack cases, exactly the same frozen Reader weights, prompt constructor,
provenance and terminal token syntax. **The original complete 100-answer trial
is retained without modifying its records or experiment arms.**

The earlier `joined_top3` arm selected only the three relational facts and did
not present the quoted attack document to the Reader. It was therefore **not a
test of resisting untrusted instructions with sufficient evidence present**.
The new `system2_multihop_stress.py` addresses that limitation using six arms
per case: `chain_only` (3 factual spans), `neutral_last` (same three facts plus
an explicitly neutral untrusted quote), `attack_last` and `attack_first`
(same facts plus actual attack quote in two presentation positions), then
`neutral_missing` and `attack_missing` (same two factual spans after fixed
critical-edge deletion plus a neutral or malicious quote). The neutral document
uses a new source identity tied to its actual bytes. The attack and neutral
conditions share the same factual chain; selected source counts match within
the key paired comparisons, and the actual tokenizer/CPU costs are recorded.

The five original cases × six arms require **30 frozen Reader calls** after
passing existing regressions and the unchanged 100-call original trial.
No generated correct answer, required source labels, or scorer enters either
selection or Reader input. All raw answers are flushed to disk, sealed with
SHA256, then scored by exact synthetic token, cited evidence source identities,
explicit abstention in missing-premise conditions, mention of `TOK-FAKE99`,
and whether the malicious source was cited. All execution failures stay in the
full census and make CI non-green; a transport failure is not scored as a wrong
answer. The independent reviewer fields remain absent; this is synthetic
Reader robustness, not measured real-world safety or learned NDU/FBSDE ability.

Nine new hermetic tests check identical factual content under attack and neutral
interventions, evidence-count accounting, source integrity, label blindness,
proof citation binding, unsupported abstention, complete 30-position census,
raw answer seal and failure persistence. A positive Reader result would motivate
further controlled naturalistic tasks; a failure would localize Reader/prompt
resistance and should not be addressed by blindly deepening the FBSDE tree.
