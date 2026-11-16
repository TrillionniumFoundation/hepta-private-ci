# HPCA recorded chat outputs: immutable archive receipt gate

**HOLD_NO_GO / DENY_ALL**. This changes only the read-only archived-evidence auditor and its adversarial tests. It does not change the historical model runner, weight, generated token stream, task roster, labels, Owner, deployment, or original recorded evidence.

## Exact starting point

- Parent: PR #6109, source `92ab69cc8309a5d94b5c77ec347cf15eb51edbad`, whose audit checks journal pairing, same-run identity, source/configuration/model-witness anchors and public-task arithmetic.
- Independent archived original readback: `chat-native-cpu-evidence-20261112/RECHECK_T6.json`, consistent with `EVIDENCE_SHA256.txt`.
- Original RESULT SHA256: `93bb1be598d8f5964ce4de890a34a48bfd606be130c2a383b5b9c962dd6c58de`.
- Original PREEXECUTION SHA256: `10a68d75e5608b494977eb8d2d923fe908fa74c18e2e0ebd40cb93f39c839d3e`.
- Original ROWS journal SHA256: `9c4dc311c45b22a179d000edbb7f994b58bd9e3e9c1246a60f26303861a19ef7`.

The original outcome is **24 exposed tasks, 12 valid leading YES/NO, 6 correct, 0 first-token EOS**. This is a public output-format diagnostic, not HPCA improvement or a prospective evaluator.

## Specific integrity flaw and the negative controls

The old auditor used candidate-supplied RESULT-to-journal and RESULT-to-preexecution SHA relationships. A substituted RESULT/JOURNAL pair can preserve source witnesses, model hashes, input token IDs, task truths, run ID, event sequence and all row-to-journal equality, while changing each decoded `text` and derived `parsed`/`valid`/`correct` fields to fabricate **24/24** correct. It can also replace each observed inference row time by zero and rehash the journal. This is a **record substitution** problem, not evidence that the actual model emitted those fabricated answers.

Tests now construct those two self-consistent forgeries while leaving token IDs and frozen source identities unchanged. The byte identities are checked *after* the detailed semantic checks so pre-existing error-specific rejection tests remain meaningful. An explicit positive control verifies the three original bytes match the archived SHA witnesses. The post-check report explicitly marks immutable receipt equality; it does not upgrade historical evidence to independently authenticated model execution.

## Reproduce the narrow gate

```sh
python3 -m unittest discover -s qualification/hpca-neuroscience-20261110 -p test_chat_evidence_audit.py -v
python3 -O -m unittest discover -s qualification/hpca-neuroscience-20261110 -p test_chat_evidence_audit.py -v
python3 qualification/hpca-neuroscience-20261110/chat_evidence_audit.py \
  --evidence-dir qualification/hpca-neuroscience-20261110/chat-native-cpu-evidence-20261112/execution \
  --source-dir qualification/hpca-neuroscience-20261110
```

The existing path-scoped `HPCA recorded chat evidence admission` workflow runs these checks on the PR exact head. **Do not mark hosted CI closed until its original job is completed and read back.** The two new negative tests were committed first as a RED candidate and the implementation was committed separately; the RED job and actual resource measurements must be checked before claiming an observed failing run.

## Hard boundary

The SHA values are historical repository evidence, not producer signatures or an independently withheld benchmark. Token IDs are still not decoded afresh against authenticated model/tokenizer bytes by this auditor. No new neural training, new B, real task effect, calibration/OOD retention, MEM no-resurrection, Core × NDU 2×2, cold Owner recovery or Adopt/NoUpdate has been demonstrated. No inherited success in this PR grants deployment or FinalUse.
