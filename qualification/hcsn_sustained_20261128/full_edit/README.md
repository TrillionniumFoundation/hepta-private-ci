# Training on the full CREMA-D corpus by recurrent direct writes or BP

All five methods saw the same 4,984 unique training clips per pass, in the same seed-specific order, for four passes. The six-layer encoder has 731,168 parameters. Direct and matched-site BP use six hidden matrices and one shared output projection, totalling 70,656 parameters. Each held clip is scored against 72 text prompts. Selection used 1,147 development clips before scoring the 1,311 held clips from 16 additional actors. These recordings have been used in other development trials. See [protocol](PROTOCOL.md).

| Method | Development-selected raw held NLL ↓ | Held top-1 | Mean charged seconds per seed |
|---|---:|---:|---:|
| Direct, six hidden layers and shared output | 4.90713 | 5.64% | 28.21 |
| Direct, shuffled hidden labels | 5.06199 | 5.64% | 28.86 |
| Direct, shared output only | 5.14385 | 5.36% | 19.74 |
| AdamW on the same seven matrices | 3.81273 | 9.99% | 57.00 |
| AdamW on all parameters | 3.01426 | 22.20% | 71.81 |

Times include fitting four passes and the exploratory three-checkpoint protocol. For an equal-quality comparison, raw NLL 4.1 on both development and held actors was reached by 0/3 direct seeds, 3/3 matched-site BP seeds (16.11–17.25 s) and 3/3 full BP seeds (19.79–20.25 s). Full BP alone reached raw 3.6 in every seed. Its faster time to the 4.1 gate than the entire direct trial is compatible with its longer four-pass total.

Direct minus matched-site BP held NLL was +1.09440 nats, paired actor bootstrap interval [+1.00424,+1.18120]. Relative to full BP the difference was +1.89287 [+1.69182,+2.08416]. Direct minus shuffled was −0.15485 [−0.23290,−0.07563]. Correct hidden supervision contributed information while leaving a substantial gap to end-to-end optimization.

Under the separately registered development temperature and full training-class prior, direct scored 4.08362 (top-1 5.34%), matched BP 3.74311 (10.68%) and full BP 2.95992 (22.98%). The two-set 4.1 gate passed on 2/3, 3/3 and 3/3 seeds respectively. The mean direct–full gap remained +1.12370 [+0.88859,+1.35299]. The verifier independently scored 90 development/held files, 7,963,920 logits, 45 candidate hashes and eight actor contrasts. See [verification](verification.json), [all results](terminal.json), and [selection seal](development_seal.json).
