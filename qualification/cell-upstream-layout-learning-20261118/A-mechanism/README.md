# Completed A execution and observed failure mechanism

The original A owner completed its prescribed 24 new generations and exited successfully. All 24 actual raw answers failed the unchanged patch-admission gate; none started a native test child. These are model-task failures even though the experiment owner completed normally. The necessary A condition for promoting native feedback has failed; the original B3 evaluation is still completed under its predeclared budget and does not override that A failure.

| Arm | New calls | First | Final | Common P prefix | Input tokens | Output tokens | Output-cap hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Document evidence | 12 | 0/4 | 0/4 | 0/4 | 26,338 | 17,551 | 7 |
| Native feedback | 12 | 0/4 | 0/4 | 0/4 | 25,844 | 17,618 | 8 |

The original P A calls are reused, not regenerated. P also had first/final scores of 0/4. Recovery has four opportunities per current-policy arm and zero successes; first-success preservation has no opportunities and is vacuous.

## Actual A-only diagnosis

The read-only tokenization and receipt audit added no forward pass, generation, verifier call or native child. It did not read B3 tasks or outputs. The actual encoded groups were regenerated exactly; every positive target matched the original verified maintainer answer and native terminator. Failed actions and feedback were masked. Each supervised target position was assigned to exactly one head chunk. All actual inference messages, rendered prompt hashes, token counts and generation-policy digests matched their receipts, without input truncation. Native common-P-prefix inputs exactly matched their corresponding saved training prefixes. The document layout's flattened history is its declared experimental treatment.

The actual imported loss gathers hidden position `p` for label `p+1`; the first supervised token at index `L` is predicted from hidden index `L-1`. Each chunk mean is multiplied by its target count divided by the full group's target count; clipping and the optimizer step happen once after all chunks. Both fits loaded the same actual parent parameters with fresh empty AdamW state. All 64 recorded loss and gradient norms were finite. Mean loss over the first/last eight updates was 0.8068/0.4841 for document evidence and 0.8023/0.4994 for native feedback. This is target fitting, not demonstrated free-generation improvement.

The unchanged original errors are:

- 16 unterminated JSON strings, two invalid escapes and one extra-data JSON error.
- Two duplicate JSON keys, two nonunique or absent literal old-text matches, and one invalid edit schema.
- Fifteen responses reached the 2048-token cap.

For example, both attrs current-policy arms began an entire function in the `new` string, then repeated escaped quotation marks. A repeated 16-token sequence appeared 969 times before the cap. The corresponding verified target is a finite local edit. Both humanize common-prefix responses had a repeated 16-token sequence 2024 times. The original full answers and hashes remain in the retained call records; representative exact prefixes/suffixes and reference-target snippets are in `CALLS.json`.

No specific causal-shift, mask, template or optimizer-wiring error was found by these checks. They do not measure why learned probabilities produced these strings, and they do not justify changing the current gate, adding steps to chase B3, or claiming that more training will generalize.

## Existing interface inventory

The adjacent `structured-interface-survey/` records read-only observations. The installed Transformers version has an allowed-token callback hook, but no ready grammar implementation was found in the scoped paths. The repository's existing multiline apply-patch primitives have lenient parsing and fuzzy context fallbacks, so they cannot directly replace the current exact-old-text gate. A future strict wrapper or constrained decoder would require CPU admission controls, the same interface for every compared arm, unchanged path/AST/native-test restrictions, and actual decoding-cost accounting. JSON syntax alone does not prevent unbounded string or escape repetition. No new decoding policy was installed or tested here.

## Evidence boundaries

Execution source remains `78099aa6af4c70c00f26cb11888e20aa59510014`. This publication adds original A results and a read-only diagnosis; it does not relabel execution source or alter scores. `CAUSAL_AUDIT_SOURCE.txt` retains the exact previously executed introspection script. The prospective evaluation collector has been formatted and linted, but is not represented as completed until its own archive receipt exists. Both complete adapters and training originals are separately retained in `training/ACTUAL_TRAINING.tar.xz`.
