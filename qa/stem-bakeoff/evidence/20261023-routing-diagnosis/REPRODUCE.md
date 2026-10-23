# Reconstructing and repeating the diagnosis

## Verify the delivered bundle

Use the adjacent publication manifest to verify each 6 MiB chunk and the reconstructed compressed archive SHA-256. Join chunks in numerical order. Extract only after the whole-archive checksum matches. MANIFEST.json inside the archive records each relative member, byte count and SHA-256; the outer publication receipt records the manifest SHA.

## Inputs and path semantics

- driver/ contains the exact five Python modules executed for run-002.
- inputs/historical/ contains the complete registered parent/single/split checkpoint layout and all pinned historical JSON/router inputs.
- inputs/repository-source/ contains the 107 pinned memory_cell Python sources plus specified Git documentation/dependency files. It is an auditable source snapshot, not a fabricated Git checkout.
- runs/run-001/ preserves a never-executed preparation. runs/run-002/ preserves the completed event.
- Historical absolute paths in JSON receipts are evidence of the original run location. Do not edit those receipts to make them look portable. The preparation API explicitly rebases artifact locations from the supplied historical directory while checking names, roots, scope, version manifests and byte inventories.

## Reproduction environment

Use a clean checkout of TrillionniumFoundation/hepta-private-ci at commit d61a36e21d1ad6d90614c145455b88c647c430e8. Obtain the pinned SmolLM2-135M-Instruct base using the acquisition command below or provide an existing publisher-verified directory. Base bytes are an external reproducible input, not hidden adapter data.

The observed runtime was Python 3.12.14; direct package versions are recorded in runs/run-002/execution-start.json (torch 2.5.1+cpu, transformers 4.57.1, peft 0.17.1, safetensors 0.6.2, tokenizers 0.22.2 and numpy 1.26.4). The pinned repository requirements and README provide environment installation instructions. This is not a container image or a hermetic transitive dependency lock.

Set these explicit paths for your extraction and checkout; none of the original scratch paths is required by the reusable driver:

```sh
BUNDLE=/absolute/path/to/hepta-routing-diagnosis-20261023
REPO=/absolute/path/to/clean/hepta-private-ci
MODEL=/absolute/path/to/pinned-smol135m
WORK=/absolute/path/to/new-routing-diagnosis-work
git -C "$REPO" checkout --detach d61a36e21d1ad6d90614c145455b88c647c430e8
python -B "$REPO/scripts/memory_cell/prepare_parametric.py" --output "$MODEL" --download
mkdir "$WORK"
cp "$BUNDLE"/driver/*.py "$WORK"/
python -B "$WORK/diagnosis_trial.py" prepare --repo "$REPO" --historical "$BUNDLE/inputs/historical" --model "$MODEL" --output "$WORK/reproduction-001"
```

The prepare command performs no model calls. Inspect its new protocol and pins, then explicitly run:

```sh
python -B "$WORK/diagnosis_trial.py" execute --output "$WORK/reproduction-001"
```

The driver sets CPU thread limits to 2 and uses fresh child processes. It performs exactly 2,904 decoder queries, 1,272 parent feature forwards, 2,400 router updates and zero decoder updates. Plan roughly 24 minutes on the observed environment; other hardware/runtime can differ. Do not run a competing large model in the same memory-limited process group.

Do not execute the archived run-001 or run-002 folders again. A new location requires new preparation receipts and timestamps; never rewrite the original experiment pins. No automatic retry is implemented. Preserve any new failure/partial-work receipts rather than restarting under the same output path.

A repeat is still a repeat of an exposed synthetic cohort. Neither reformatting the published source nor obtaining similar numbers turns it into independent confirmation or closes the Phase 3, total-budget or multi-host gaps.
