# Exact pinned mmBERT tied alias and physical proof (research / DENY_ALL)

This additive P0 experiment preserves the source V13 research owner and the
immutable `jhu-clsp/mmBERT-small` revision
`0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`.

The actual GitHub-hosted V14 key diagnostic run `38868208653` completed source
and synthetic-merge jobs. Both original SHA-checked result ZIPs show 137 saved
tensors and 138 runtime tensor names, with only
`model.embeddings.tok_embeddings.weight` a state-only key. Their `missing_keys`
were empty under that stand-alone loading sequence. The earlier V13 full task
run had refused a missing non-tied/randomly initialized MLM parameter before
emitting any original task feature. The exact mismatch between execution paths
has not been independently explained by the names-only diagnostic.

This change permits only zero, one, or both original tied alias names in a
Hugging Face loading metadata report. It DOES NOT mean a missing tensor is
accepted as pretrained. The existing `FrozenMMBert` then still must:

1. pin original 40-hex Hub revision, use local-only safetensors, no remote code;
2. physically prove decoder/input embedding storage alias in actual PyTorch;
3. byte-compare the ENTIRE original tied table against source safetensors;
4. byte-compare ALL 137 serialized tensors, including scalars and shapes;
5. refuse any extra source/loaded tensor, nonfinite or mismatched weight;
6. execute an actual CPU Encoder forward on a label-free fixed probe;
7. emit only digests, integer counters and `DENY_ALL` research flags.

One preexisting strict original full-state byte verifier remains authoritative;
there is no new fallback, randomly initialized model or unpinned revision.
The V15 separate hosted workflow must actually pass before a fresh physical
mmBERT source can be reported as verified. An exact physical probe never proves
human task success, NDU training benefit or production authorization.

Failure of Laya, Gemma, mmBERT or Granite remains an explicit failure in the
original all-four collector; this sidecar cannot promote a partial subset.
