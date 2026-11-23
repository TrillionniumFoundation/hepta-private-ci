# Frozen students on native answer choices

This exploratory follow-on tested whether the pretrained teachers had different strengths when asked to supply actual translations, verbs, numbers and city names. On each question we compared the mean token log likelihood of the correct answer and a foil. The two answer alternatives were scored separately. The templates for confirmation had been held out from discovery and student fitting.

| Domain | Discovery FLAN / Smol (each out of 12) | Held-out FLAN / Smol (each out of 20) | FLAN-only / Smol-only on held-out |
| --- | --- | --- | --- |
| german | 8 / 7 | 18 / 15 | 5 / 2 |
| french | 12 / 9 | 17 / 8 | 10 / 1 |
| agreement | 12 / 10 | 20 / 9 | 11 / 0 |
| addition | 10 / 11 | 7 / 8 | 6 / 7 |
| python | 4 / 7 | 14 / 10 | 9 / 5 |
| capital | 7 / 11 | 18 / 17 | 3 / 2 |

The predeclared direction replicated for FLAN on German and French word translation and subject–verb agreement. Only addition retained Smol's advantage, by one question. Its 8/20 absolute accuracy was below 10/20 chance expectation. Smol's discovery leads on Python indexing and capitals reversed. Small per-domain counts, six inspected domains and recurrent concepts limit how broadly we can infer complementarity. There are zero human test users in this run.

| Frozen arm | Correct / 120 | Weakest domain / 20 | Pairs / 24 | Old / 12 | Correct on FLAN-only / 44 | Correct on Smol-only / 17 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| parent | 64 | 9 | 8 | 12 | 28 | 9 |
| t5 | 54 | 7 | 10 | 12 | 19 | 7 |
| smol | 57 | 5 | 7 | 12 | 20 | 6 |
| best_single | 57 | 5 | 7 | 12 | 20 | 6 |
| mix | 53 | 7 | 10 | 12 | 19 | 3 |
| fixed | 56 | 7 | 6 | 12 | 22 | 7 |
| sparse | 56 | 6 | 7 | 12 | 23 | 8 |

Smol was preselected as the best single teacher on pooled discovery accuracy. Every updated student scored below the 64/120 frozen parent on the held-out questions. Equal mixing and the FLAN student attained 10/24 pairs compared with the parent's 8/24. These pairs combine independent component decisions. This experiment produced no student that demonstrably inherited both teachers' strengths. Domain attribution and open-ended language generation remain separate questions.

The owned vocabulary had 1,639 features. Teachers spent approximately 45.24 s on discovery plus fitting labels and 30.38 s on held-out plus composition labels, excluding load and setup. Fitting the student bundle took 0.0613 s. All seven arms reloaded their common bundle in separate network-isolated processes, using only the query and its two candidate answers. For the fixed arm, the runner supplied the declared family. The learned top-1 gate consumed query text. Both routing policies used the 72 truth-labeled discovery items, where the fitting set contained 192 teacher-labeled examples. All 12 simple old checks passed for every arm.

The archive includes the portable student bundle, row-level teacher likelihoods, row-level prediction and routing, upstream identities, freeze receipt and scores. See [the successful run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45171513594). Archive SHA-256 is `4e9dc2f83b79db9a1076f107d1c610c9b4ad4e61d24d0ed1aaaa53dea870b508`.
