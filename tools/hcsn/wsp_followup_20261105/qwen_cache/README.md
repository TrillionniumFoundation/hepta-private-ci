# Short F32 Qwen cache qualification

**Actual result: PASS for the two pinned base/p50c text models on one fixed
short input. This is software execution qualification, not model efficacy.**

The single execution started at **2026-11-05 00:28:03 UTC**
(**2026-11-04 19:28:03 America/New_York**) and completed at 00:28:44 UTC.
No threshold, input, weight, package, or execution source was changed after
observing a model result.

## Frozen scope and identities

- protocol.json: SHA-256
  7d6adcac413fef4f4d7dff53daaef237a3496dbdd5678bfbd84ef29fa6613900.
- qualify_cache.py: SHA-256
  94d2575bd2b73544c4261f801ceeca49339471943622ebdb0b95eb6471e69a56.
- runtime_pins.json: SHA-256
  22cbed4ee085927b82ea5c6e458946509d60066dc723e7ebacd742c4891950d9.
- Original strict-loader source: SHA-256
  d4ff765d249b6fee60e619ea90af3f2b00e54468c9601006ed962dc1e7c994f0.
- Original strict-load receipt: SHA-256
  8cd96da30ae00a4fe8c327db646ece3f7a6e65fe8ba17da502b2fdb27a73d5e1.

The original MIT source revision is
4d09ba6d6a7e891dd8063974dfe81b3d78e3494f; the Qwen source revision is
2fc06364715b967f1860aea9cf38778875588b17. This uses the existing qualified
text exports, with all 18 export/receipt/config/tokenizer file contents checked
before and after execution.

Each model consumes all 320 language tensors through the previously qualified
strict mapping. The output embedding alias is tied. The 15 MTP tensors are
explicitly excluded from this ordinary text-decoding path. Each source learned
parameter was authenticated and **lifted exactly from BF16/F32 values into F32**.
There was no optimization, weight edit or requantization of the execution
parameters. The original export files were never changed.

Runtime binding covers actual hashes of seven named Transformers execution
sources and the METADATA/RECORD hashes and versions of six dependency
distributions. It does not certify every transitive installed binary, the OS
or an arbitrary installation with the same version labels. The recorded
RECORD identities can also constrain reproduction in a differently installed
environment; such a changed runtime requires a separately declared qualification.

## What actually ran

The original seven-token input is fixed as
[32, 11012, 6353, 12077, 2708, 3000, 13], representing
"A quiet morning brings clear light."

For each of base and p50c:

1. One cached prefill was compared with a full uncached prefix.
2. Eight greedy tokens were appended one at a time.
3. Each incremental cached call was compared with a fresh full-prefix call on
   the **same actual prefix**. Prefix lengths were 7 through 15 inclusive.
4. Every vocabulary logit had to be finite and satisfy the predeclared
   atol=0.001, rtol=0.001; greedy argmax and cache sequence length also had to
   agree.
5. All learned F32 parameter hashes were rechecked after execution.

The combined count is **18 compared pairs, 36 actual model forwards and
16 appended tokens**, with no benchmark answers or accuracy scores. A fixed
software probe does not stop early on EOS. There was no sampling or attempt
to reproduce the author's BF16/vLLM generation settings.

| Variant | Largest absolute logit difference | Largest ratio to fixed tolerance | All 9 finite/allclose/argmax/length checks |
|---|---:|---:|---|
| Base | 0.00001239776611328125 | 0.008975963108241558 | PASS |
| p50c | 0.000011920928955078125 | 0.010199081152677536 | PASS |

These differences compare cached versus uncached execution within each variant.
They are not an edited-versus-base capability measurement.

## Resource and failure accounting

The fixed combined wall budget was 180 seconds. Each model ran in a separate,
sequential owned subprocess with one logical CPU in its affinity set,
torch.set_num_threads(1) and torch.set_num_interop_threads(1).
CUDA/HIP/ROCR visibility and other thread settings were restricted only in the
child environment. Every learned parameter, buffer and logit was checked to
remain on CPU; Torch reported no initialized accelerator context.

The supervisor monitored its owned worker and observed descendants every
50 milliseconds, including RSS and VmHWM. The threshold was 8 GiB. It would
terminate only its own process group on a resource or time violation.
Polling is not an instantaneous kernel RSS ceiling. In this run, the highest
observed HWM was **5,740,130,304 bytes**, and no process was terminated.

- Total measured supervisor wall time: **40.662795775 seconds**.
- Owned-child CPU, including process startup/shutdown: **32.618291 seconds**.
- Supervisor CPU: **3.137830194 seconds**.
- These disjoint CPU measurements total **35.756121194 seconds**.

The worker-internal CPU timers are nested within owned-child CPU and must not
be added again. These numbers include the driver's input checks, loads and
short comparisons; they do not measure artifact acquisition, agent reasoning,
full benchmark generation, energy or a model-training speed advantage.

receipt.json, base.json, and p50c.json are the original complete machine
receipts, copied without modification. Their SHA-256 values are respectively:

- a055831533050e0cbdf0d79b398a1abd6e75da261d6de9d0865ad16455690b7d
- 74ab9ec6975f4ad7949b7961e861099bd4eeb37cc0d8834e5165648a2bef1e05
- 106642ee2826eee7155b7a09a44e17cd87bb2c9b7fe1ecec08e26ad0f3154288

Original worker stdout/stderr remain on the authorized host. The receipts
preserve their hashes; these logs are not part of the public file whitelist.

## Independent checks and replay

Run the standard-library frozen-record verifier:

    python verify_records.py

This checks file identities, cross-receipt equality, fixed trajectory and
execution counts, stated numeric conditions and budget consistency. It does
not load Qwen or independently recompute the full vocabulary arrays.

To repeat the actual execution, use an installation and unchanged exports
matching runtime_pins.json, plus the original loader and its receipt. Supply
their local paths explicitly and choose a new absent output directory:

    python -B qualify_cache.py \
      --protocol protocol.json \
      --protocol-sha256 7d6adcac413fef4f4d7dff53daaef237a3496dbdd5678bfbd84ef29fa6613900 \
      --pins runtime_pins.json \
      --pins-sha256 22cbed4ee085927b82ea5c6e458946509d60066dc723e7ebacd742c4891950d9 \
      --exports /absolute/path/to/qualified/exports \
      --original-loader /absolute/path/to/original/qualify_framework.py \
      --original-receipt /absolute/path/to/original/forward/receipt.json \
      --output /absolute/path/to/new/cache-qualification

No model weights or benchmark datasets are redistributed here. A successful
short F32 comparison does not qualify long-context decoding, BF16 numerical
behavior, MTP, the original sampling configuration, MATH/GSM8K/IFEval, new Astra
discovery or an improvement in Hepta/Trader task value.
