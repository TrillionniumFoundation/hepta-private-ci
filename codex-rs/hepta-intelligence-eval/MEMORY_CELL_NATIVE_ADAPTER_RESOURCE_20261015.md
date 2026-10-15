# Actual LoRA resource-versus-output effect — 2026-10-15

**Research-only, fail-closed and source-pinned. No new pretrained inference or production qualification.**

The original completed GitHub workflow [38675845950](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38675845950) generated 128 real answers on two *exposed development slices* at exact source `2b33c6321f52711761ec626ead27c9482c7c1cb0`. The two ZIPs are externally SHA-256 pinned in `memory_parametric_behavior_audit.py`; its independent verification covers 199 individual original files. This extension reads each of the **32 original saved LoRA tensor files**, independently hashes and binds `adapter_model.safetensors`, `adapter_config.json`, `lineage.json`, and their request-level training receipts, then verifies the matching `parametric_only` and `rag_lora` pair reused one identical training record. No training or model is invoked by this auditor.

| Actual original receipt | LoCoMo 16 tasks | LongMemEval 16 tasks | Total |
| --- | ---: | ---: | ---: |
| Four-step adapter training executions | 16 | 16 | **32** |
| Recorded optimizer updates | 64 | 64 | **128** |
| Training input tokens | 2,787 | 12,250 | **15,037** |
| Sum of recorded training elapsed seconds | 28.2446 | 50.5009 | **78.7454** |
| SHA-verified saved adapter tensor bytes | 14,992,896 | 14,992,896 | **29,985,792** |
| Saved adapter models | 16 | 16 | **32** |

Every original adapter records 230,400 trainable parameters, positive nonzero parameter delta norm, `base_unchanged=true`, and a successful model-reload manifest. The per-training-instance optimizer tensor allocation was recorded as 1,843,680 bytes. **Do not sum optimizer-state sizes as simultaneous resident memory**: the original worker may train serially and its process peaks need independent provenance. File sizes above count saved adapter tensors only, *not* complete raw evidence, indexing, duration-dependent retained storage, extraction, query loads, revocation or recovery.

The separate original-answer audit finds **63/64 parameter arm pairs produce byte-identical answers**. In the one differing answer, both diagnostic token-F1 values remain zero; among the **56 scored parameter comparisons**, zero improve F1, and the eight unscored LoCoMo comparisons remain missing. A scored-task “cost per extra correct answer” is **undefined, not zero**. These data do not prove no possible future learnability; they fail the *current* promotion gate. No independent semantic sufficiency or citation verifier signed this result, no new source family was tested, and no retrospective resource curve substitutes for TCO.

`memory_native_adapter_cost.py` rejects altered entire ZIPs, missing or duplicate saved adapters, incorrect checkpoint/config hashes, lineage/Reader/roots mismatches, changed four-step counts, absent training evidence, cross-arm training drift, nonfinite or negative timings, and report overwrite. Ten original-ZIP-backed regression methods cover this. The committed aggregate JSON can be rederived byte-for-byte without downloading any model weights for inference.

Reproduction:

```sh
export MEMORY_NATIVE_LOCOMO_ZIP=/path/original-locomo-11946307808.zip
export MEMORY_NATIVE_LONGMEMEVAL_ZIP=/path/original-longmemeval-11946513138.zip
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_memory_native_adapter_cost.py' -v
python3 scripts/memory_cell/memory_native_adapter_cost.py \
  --locomo "$MEMORY_NATIVE_LOCOMO_ZIP" \
  --longmemeval "$MEMORY_NATIVE_LONGMEMEVAL_ZIP" --output NEW_REPORT.json
```

**Disposition: NO-GO** for promoting per-question LoRA as a superior MemoryCell until a prospective family-disjoint, independently adjudicated same-Reader/same-evidence test establishes real task or citation gains and complete lifecycle resource allocation. `production_qualified=false`.
