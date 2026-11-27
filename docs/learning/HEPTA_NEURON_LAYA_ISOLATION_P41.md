# P41 — immutable Laya publisher bytes with isolated tokenizer compatibility

**Status: DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** This is a
research-only child of [P40 #3437](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3437)
at frozen commit `6d2eb241a021a8ef6e58742d808fd26e70c0d6c3`.
No original ancestor, main, artifact owner, CNS routing or Final-use authority
is changed.

## Executable incompatibility repaired at the shadow loader boundary

Pinned upstream Laya source revision
`c7527708f9f5220c669d8aa385077cd28d04708a` invokes
`_fix_tokenizer_config(model_dir)` during `Agent.__init__`. For some
checkpoint tokenizer configurations it **rewrites**
`tokenizer/tokenizer_config.json` in the supplied model directory, changing
`TokenizersBackend` to `PreTrainedTokenizerFast` and converting a list of
`extra_special_tokens` to a mapping.

P39/P40 verifies the original SHA256-pinned publisher checkpoint again after
all forwards. Loading directly from that original snapshot would permit an
upstream compatibility mutation, undermining source custody and conflating the
actual tokenizer preprocessing with publisher bytes.

P41 adds `replacement_laya_view.load_laya_cpu_isolated` and invokes it from
`replacement_physical.run` for the three **complete** Laya policies. It:

1. Creates a private, temporary tokenizer-tree copy after computing bounded
   original file inventories. It rejects symlink/non-regular tokenizer entries,
   missing tokenizer bytes and oversized inventories.
2. Keeps the actual original `model.safetensors` and Encoder directory as
   source-pinned, read-only-intended inputs to the shadow loader. Only the
   tokenizer tree is an independent copied write target.
3. Permits solely the two explicitly known JSON compatibility transformations
   observed in the frozen upstream implementation. It checks all other copied
   tokenizer bytes remain identical and refuses new/deleted members.
4. Rejects changes to the original tokenizer tree, weights, Encoder config or
   policy config. Deletes the private view after model/tokenizer construction
   and before the real original-weight forward calls.
5. Records the original and effective tokenizer inventory/config SHA256s,
   whether a registered normalization happened, the original model weight
   SHA256 and `no_original_snapshot_mutation_observed`. The separate raw
   five-arm auditor rejects missing or inconsistent disclosure.

The loader still re-verifies the original P38 checkpoint after all real
forward passes, as in P39/P40. A symlink is used **only inside this temporary
research view** to avoid copying gigabytes of verified model weights. This is
not a hard security boundary against arbitrary upstream Python; the owner
must separately qualify sandboxing, real device execution and immutable
artifact custody.

## Tests and honest limits

`python3 -m unittest discover -s qa/stem-bakeoff -p 'test_replacement_laya_view.py' -v`

The new tests use tiny fake weights and a simulated pinned upstream rewrite;
they verify registered normalization, original-byte custody, private-view
cleanup, unregistered modifications, linked inputs, missing config and added
files. The cross-arm audit tests reject a missing/mismatched compatibility
report, including a forged original weight identity.

The updated physical shadow workflow runs these tests on the exact PR head,
and the five original-weight CPU arms remain mandatory. A passing isolated
unit fixture cannot show original pretrained Laya model execution. Nor does
a CPU checkpoint probe close the six independently signed production
qualification stages: future/non-English/retrieval and negative transfer
quality, adequate sample sizes, full 64–4096 Cell target-host evidence,
signed Artifact CAS/state migration/CNS/fence/restart/rollback/Final-use,
operator acceptance and terminal blocking CI.

**No model selection, Cell Split, memory effects, authorization, promotion,
merge, release or production traffic is admitted.**
