# Greedy translation from the packed expert graph

Sixteen English source sentences had 32 independently authored FLORES-101 French and German references. Each original or packed Marian model decoded from just the English source. Both packed specialists also served the explicit target-language route in a new teacher- and reference-inaccessible, network-isolated process. Each live result for that route matched the separately computed component output. Fixed and learned route scores were assembled from the same individually generated hypotheses and recorded selections. All three policies selected the intended translation specialist on every request.

| Generator or route | German corpus chrF++ | French corpus chrF++ | Mean sentence chrF++ across both | Both scores ≥35 /16 sources |
| --- | ---: | ---: | ---: | ---: |
| Released German specialist used for both languages | 60.73 | 16.10 | 38.93 | 0 |
| Released French specialist used for both | 16.34 | 68.56 | 42.45 | 0 |
| Packed German specialist used for both | 60.98 | 16.17 | 39.01 | 0 |
| Packed French specialist used for both | 16.31 | 69.37 | 42.76 | 0 |
| Requested-language graph of packed experts | 60.98 | 69.37 | 65.87 | 14 |
| Discovery-fixed graph of packed experts | 60.98 | 69.37 | 65.87 | 14 |
| Discovery-trained top-1 graph of packed experts | 60.98 | 69.37 | 65.87 | 14 |

The explicit target language makes routing simple. The expert parameters are externally pretrained translation models, re-encoded into deterministic compact components. The behavioral student in the separate choice experiment can rank choices and has no free-form decoder. No live user participated and the points threshold is a registered automatic reference score. This small established benchmark can overlap pretraining. Its 16 shared English sentences determine the sample size for bilingual performance.

Original and packed decoded **text** matched on 11/16 German outputs and 14/16 French outputs. The raw batch-padded token arrays matched for only 2 German and 14 French examples because a changed output in a batch changes other rows' trailing padding. The complete decoded text, token arrays, references, source line numbers and routes are retained in `free-bilingual.zip`. An independent Python standard-library implementation reconstructs the reference strings from the original corpus and recomputes all 224 score assignments to within 1e-8 of sacrebleu 2.5.1. It also checks each declared bilingual threshold count.

[Generation protocol](./PROTOCOL.md) · [Frozen execution](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45183499802) · [Human corpus and model attribution](../ATTRIBUTION.md)
