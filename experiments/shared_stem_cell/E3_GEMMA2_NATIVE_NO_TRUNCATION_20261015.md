# E3 original Gemma2 text/image pre-forward token budget (research only)

**Status: DRAFT · SHADOW_ONLY · DENY_ALL**. Child of frozen #2227 head `180cfe59b037b1c19254c79771cf26f290ce2810`. Does not modify the immutable source panel, upstream pretrained weights, baseline DINO/Granite, Head optimizer, Q24, any production worker, authority or `main`.

## Concrete missing control

The initial native physical research path constructed 192 original same-source question+image dictionaries, 192 image-only inputs and 768 option strings, then called `SentenceTransformer.encode()` directly. Although original media bytes and the pinned model manifest were checked, that research call did not invoke the existing model-owner full-text token admission method and could allow hidden truncation of source, option or text+image messages.

A source-matched five-arm accuracy result is not interpretable when one arm silently loses part of a question or candidate.

## Added fail-closed verification

- `e3_gemma2_native_budget.py` checks the exact original input payloads being passed to `encode()` using the *already verified model's tokenizer* with `truncation=False` and `add_special_tokens=True`. Any missing tokenizer, strange non-flat IDs, unknown default prompt, changed text+image pair, missing option or text beyond admission limit is rejected **before the first native encoder call**.
- A conservative 280-token estimate for one default image and another 128-token allowance for control/prompt overhead are reserved. These are conservative admission estimates, **not an observed true media token count**. For plain/option strings the cap is 8192−128; for composed text+image it is 8192−280−128.
- The original native physical producer records maximum plain, composed-pre-media and choice tokenizer lengths, and explicitly writes `actual_model_image_token_count_attested=false` and `original_model_internal_forward_count_attested=false`.
- The independent five-arm receipt assembler now requires the above bound and refuses a false true-media-token attestation, invalid budget, missing source or false production claims.
- New `test_e3_gemma2_native_budget.py` contains **18** synthetic-tokenizer security and pairing methods. The original `test_e3_five_arm_historical.py` now contains **32** methods (formerly 28), including four new missing/false token-budget witness controls.
- Dedicated stdlib-only Actions checks normal and `python -O` token-budget tests, compiles original native module and refuses to count mock-tokenizer passes as model success. Full original five-arm, OCR and native physical results still require the parent model workflow and its exact SHA acceptance.

## Still missing

This source-only tokenizer check does NOT verify actual image patch count, model processor interpolation, internal transformer forwards, device GPU memory, 421M matched cost, independent historical TEST visual necessity or three prospective source windows. It also does not establish a winning Stem, NDU gain, signed CAS/FinalUse or 4,096 Cell production readiness.

The parent #2227 real-model workflow on its **own immutable head** remains an independent run and must not be reinterpreted as a pass/fail of this child; this child must also pass its new exact-source checks.

**No production selection, no model upgrade, no main merge.**
