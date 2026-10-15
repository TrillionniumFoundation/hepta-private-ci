# E22: original E21 answer-information obstruction (P0 / DENY_ALL)

This research-only additive child extends the genuine-Reader E21 parent [PR #2252](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2252) at frozen starting HEAD `78aa6df0d5fe8ab2f3240748dbee02b10dc4937f`. It changes **neither the original pretrained weights nor E15 held Heads, original source labels, original E21 scoring arithmetic, model selection, utility.ndu, or production Cell execution**.

## Source-bound two-phase execution

1. Run the existing E21 **real original-pretrained** source-head + synthetic-merge blind job. From its 33 sealed authentic MultiRC answer predictions (4 passage groups / 8 questions), E22 computes each of the six Reader methods' exact probability equality, fixed hard-threshold equality, unequal answer pairs and within-question probability span. **No human labels, original scoring ZIP or Parquet** enters this stage.
2. Write a create-once E22 blind report and SHA alongside the original E21 answer prediction SHA. Both are sealed before original human labels are downloaded or opened. An alternative answer string is *not* physically re-encoded in E22; old logits are not a counterfactual model forward.
3. Independently re-open the original pinned human validation material **only in the original E21 post-seal scoring job**, reconstruct the exact 33 task IDs using the inherited original E14 source-label owner, and require two original E15 E21 score artifacts to agree on per-candidate and whole-question results.
4. Verify exact/threshold invariance cannot yield a fully correct answer slate when each original question contains both true and false answers. This is a narrow deterministic obstruction: tiny nonzero probability differences may still encode useful semantic information, and a different Reader architecture is not ruled out.
5. Preserve exact-head E21 original tests (8 blind + 18 original-human) and add **9 synthetic-contract adversarial E22 tests**, ordinary and `python -O` in the label-free job. The E22 tests do **not** contribute another real pretrained inference or independent source family.

## Source-only local tests

```sh
PYTHONPATH=qualification/shared-stem-system2-architecture python3 -m unittest discover \
  -s qualification/shared-stem-system2-architecture -p test_e22_answer_sensitivity.py -v
PYTHONPATH=qualification/shared-stem-system2-architecture python3 -O -m unittest discover \
  -s qualification/shared-stem-system2-architecture -p test_e22_answer_sensitivity.py -v
```

The locally executed 9 normal + 9 optimized **synthetic-contract** tests passed on the exact uploaded two Python Git blobs. Real E21 original-source / source-head + merge CI must **complete successfully** before claiming that the new E22 original-human result exists; any queued, timed-out or missing artifact means **not completed**, not zero and not GO.

## Scientific limits and next causal experiment

This is a necessary **Reader output information geometry** diagnostic. It does *not* test whether the original text Encoder itself contains sufficient answer information, or independently identify the necessary supporting premise. The next physical question/premise tests must re-run the **actual original pretrained Reader** under identical source budget for full evidence, key-premise removed, wrong-premise substituted, answer swapped, no-evidence and independently sufficient-evidence conditions. The independent human evaluator must score complete questions and actual request-wide model/Reader/Verifier/FBSDE cost, with separate prospective source families.

**No NDU / FBSDE slow-path admission** from source-only geometry. Both current and future results remain `DENY_ALL`, `production_accepted=false`, `model_selected=false`, `semantic_sufficiency_certified=false` until independently qualified. The fixed external objective, original claims and original production permissions are immutable.
