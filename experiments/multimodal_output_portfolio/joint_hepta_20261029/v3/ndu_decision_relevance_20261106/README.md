# Decision-relevant identification: diagnosis and exact mechanism

This follow-up makes two separate contributions to the research decision:

1. [DIAGNOSIS.md](DIAGNOSIS.md) explains every old DP/myopic comparison using
   the initial-action Bellman lift. It binds existing frozen evidence and
   leaves the 144-cell negative result unchanged.
2. [MODEL.md](MODEL.md) proves the threshold for a state intervention that
   only unlocks information, with terminal reward strictly equal to answer
   correctness. It identifies a directly estimable decision statistic and
   proves exact equivalence to same-structure MLE plus DP.

The latter equivalence closes the proposed superiority comparison **negatively
before sampling**. [protocol.json](protocol.json) records that no random
calibration or confirmation was run. The designed known-law examples show why
lookahead can matter; they cannot establish a new algorithm's superiority.

Reproduce the exact rational qualification from the repository root:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_decision_relevance_20261106.verify_mechanism \
  --output /tmp/ndu-pure-information-mechanism-new.json
```

The [qualification receipt](evidence/mechanism-final.json) contains 36 declared
contract/law pairs and 968 feasible count triples. The count enumeration and
constructed confidence examples are algebraic checks, not independent samples,
Monte Carlo coverage estimates or real-LLM runs. Time in these examples is the
model's charged physical duration; actual operating-system and model execution
remain separate evidence. No large training framework is justified here.

The initial engineering receipt is retained as
[mechanism-before-conservative-radius.json](evidence/mechanism-before-conservative-radius.json).
The accepted source uses an outward rational radius for admission; the earlier
receipt used an ordinary floating radius and is not the accepted implementation.
