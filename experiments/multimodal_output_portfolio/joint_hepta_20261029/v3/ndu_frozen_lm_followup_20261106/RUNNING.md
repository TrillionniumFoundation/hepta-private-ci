# Published follow-up freeze and execution

All nine registered model files have been downloaded and matched to their
published Git/LFS hashes. The shared isolated runtime resolves to the original
runtime and its package inventory is copied byte-for-byte. No new package
installation or model forward has occurred at this checkpoint.

`freeze.json` binds all inference, prompt, acquisition, transport, task, tool,
source and model identity materials before the first request to this model.
The four unchanged boundary tests pass in the new module location. They check
the packaging and contract; they are not four new independent observations.

After publishing this freeze, execute the single qualification with `--qualification`
and then the fixed 16 episodes using separate new output directories:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_frozen_lm_followup_20261106.run \
  --runtime /path/to/followup_lm --output /new/qualification --qualification
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_frozen_lm_followup_20261106.run \
  --runtime /path/to/followup_lm --output /new/task-pilot
```

The shared runtime is referenced by `followup_lm/venv`; the model files are in
`followup_lm/model`. This document records the pre-execution state. Later
results and complete failed/successful attempts must be archived separately.
