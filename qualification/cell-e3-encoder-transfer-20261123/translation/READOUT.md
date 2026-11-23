# Human-reference bilingual choice trial

Two pretrained Marian specialists qualified on different languages using the original FLORES-101 human translations. On a new set of 32 English lines, the English–German expert selected 32/32 correct German references and 24/32 French references, and the English–French expert scored 24/32 and 32/32 respectively. Each teacher contributed eight exclusive held-out successes. Both had already passed the discovery criterion on other English lines. Source, development and test line identities, labels and both candidate strings are reconstructible from the original licensed archive and retained seed.

| System | Held-out choices /64 | Dev-style retention /32 | Both languages right /8 |
| --- | ---: | ---: | ---: |
| Frozen third MiniLM parent | 59 | 31 | 8 |
| Preselected German-teacher behavioral student | 57 | 30 | 8 |
| Mean teacher targets | 58 | 29 | 8 |
| Fixed or learned behavioral expert graph | 58 | 30 | 7 |
| Original German specialist | 56 | 29 | 5 |
| Original French specialist | 56 | 27 | 7 |
| Fixed graph of two independently packed specialists | **64** | **32** | **8** |
| Learned top-1 graph of the same packed specialists | **64** | **32** | **8** |

For this bounded task, the system combined the open specialists' skills by carrying their quantized model parameters into two independently reconstructed components. The actual teacher directories were hidden by a fresh mount namespace during cold evaluation. The independently learned answer encoder remained below its own parent. Student training consumed 96 source lines per language with two teacher streams plus 16 separate discovery lines per language for routing. Individual target-language requests were explicit. Each foil is a different full reference sentence in the requested language with a nearby word count. There are only 32 independent English holdout sources, shared across target languages. A deployment without access to proprietary teacher weights would have to rely on the behavioral lane.

German unique source tensors occupied 297,874,388 bytes and their retained quantized file 75,310,085 bytes. French tensors occupied 300,773,864 bytes and their quantized file 76,040,606 bytes. Combined sizes are 598,648,252 and 151,350,691 bytes (about 3.96× smaller, excluding tokenizer, config, tensor index and runtime float buffers). Inference reconstructs float tensors before execution. Each packed specialist reproduced its uncompressed teacher's choices on 112/112 combined holdout, retention and component items. This measures stored weight size and choice fidelity. GPU speed, runtime memory reduction and quality on unrestricted requests were not measured by this choice trial.

The original archive has SHA-256 49fa80207b09fcc0eca8253ed13303b3a0ae0f16081af862601c73ac76f2cba6. All 15 published arm results cover 112 items and have been rescored from source. `bilingual-results.zip` includes the selected inputs, hypotheses, decoded weight identities, training and inference costs, every raw teacher margin, student selection and the original attribution. Both complete packed weight files and tokenizers were uploaded in [the component artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45182790906/artifacts/14821574236). Their sha256 checks and original upstream source revisions are retained in the repository. Rebuild using `material.py` and the exact versions in `SOURCES.json`. [Qualified choice run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45182790906) · [Attribution and distribution terms](./ATTRIBUTION.md)
