# Restore five original scientific SVGs

The archive contains the original vector files for the HCSN free-boundary,
HCSN refinement, and STEM bakeoff figures listed below. The companion PNGs
remain at their historical paths for direct viewing.

From the repository root, run the existing archive reader to restore the
SVGs at their original paths.

```sh
python3 experiments/hcsn_free_boundary_v1/archive.py restore \
  --manifest qa/repository-consolidation/20261124/scientific-figure-storage/scientific_figures.json \
  --destination .
```

To inspect the figures separately, pass an empty directory as the destination.
The reader verifies the archive and each member, keeps identical files and
refuses to overwrite a different file.

| Original vector path | Original SHA-256 |
| --- | --- |
| `experiments/hcsn_free_boundary_v1/figures/content_and_runtime.svg` | `3c1d26fa2b2e598442bccc97f24a433e38474fe599868208a60f7962109cbab4` |
| `qa/stem-bakeoff/evidence/20261024-cell-parameter-field-v3/action-ranking.svg` | `2cb0acbbf17b53bd7e9afe734bdba5a9ddae1a081859e84c236596e2562d3151` |
| `qa/stem-bakeoff/evidence/20261024-cell-parameter-field-v3/primary-results.svg` | `18b792ed48ac0fad2e440ad8c742d9446e9c034abf3f44f53c6a6801e49e9421` |
| `qa/stem-bakeoff/evidence/20261024-cell-parameter-field/objective-vs-task.svg` | `9e619d8cd6f80283cc1b3cb607281671ff316c8b94f6210d853b7c0ce5e6cc22` |
| `qualification/hcsn_differentiable/evidence/20261108/refinement.svg` | `c986ef562aecbe0e56c3c16b81e9a5c88a759e7d329bc953cd85981ed6dbe048` |

## Multimodal preflight vectors

The two multimodal portfolio reports display SVGs at their original relative
paths. The display copies remove spaces immediately before newlines in path
data. To recover the exact SVG bytes from commit
`480e83532df57ec691ce70ff7ecb572717887a7e`, restore into a separate directory.

```sh
python3 experiments/hcsn_free_boundary_v1/archive.py restore \
  --manifest qa/repository-consolidation/20261124/scientific-figure-storage/multimodal_preflight_originals.json \
  --destination /tmp/multimodal-preflight-originals
```
