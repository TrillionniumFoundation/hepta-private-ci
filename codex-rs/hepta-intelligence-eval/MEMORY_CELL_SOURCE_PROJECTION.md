# Paired source-only Qwen writer: full vocabulary versus supervised positions

This is a read-only historical comparison, not a new model training run, citation judgement, future observation, or production deployment. Individual completed artifacts undergo the existing complete source-write retrospective, and cross-run auditing additionally binds immutable code, data, model identity, training exposure, selected evidence, prompts, adapter mode, and original answers.

Full-vocabulary generator 2c6dae45782b1ba07ba9af237f01bdecc0c5640b: run 38097606061; artifact 11689893524; ZIP SHA256 4dab11e3ceb297e8160fa342982ff68d93d86c98537b83925db857c4f0e8958c.

Supervised-position generator 7d417d2d6648c0bdeaca4bfc0b658d64b0d4f453: run 38097531656; artifact 11686688483; ZIP SHA256 bb90d42cc20b1e0a4088904e3c464f10a1c2624f662440044f4d1d28638d14e5.

Each run completed 128 Qwen2.5-3B adapter updates on the same 88 source-only facts, with 27,890 input training tokens, 1,096 supervised tokens and 921,600 trainable LoRA parameters. Projection positions decreased from 27,890 to 1,096. Max absolute per-step loss difference is approximately 7.16e-7. Inclusive write duration decreased from 465.43 to 416.61 seconds in this one matched pair (10.49%). This is not a statistically qualified speedup or lower lifetime cost.

All 56 original Qwen reader answers per run were identical. Task successes in both were: bounded hybrid 4/8; deterministic organized event reading 8/8; organized plus adapter 8/8; no-evidence base 0/8; adapter-only 0/8; initial policy 5/8; learned policy 8/8. The trained policy selected the same evidence as deterministic organization. Five adapter-only answers produced unsupported citation labels with zero delivered sources.

The faster writer has no demonstrated memory task advantage. The candidate is rejected for present controlled tasks. The eight authored tasks are already exposed and do not establish independent natural-language generalization or significance. Citations were not independently adjudicated: semantic precision remains null. There are no new future windows, qualified snapshots, production switch/rollback, external reviews, or authorization. Production acceptance remains false.

The new read-only workflow hepta-memory-projection-pair.yml downloads the two exact historic ZIPs, verifies external and internal checksums, replays the original outcome and training invariants, then outputs a new comparative receipt. It never regenerates or repairs original answers and does not relax repository-wide format, Architecture, blocking CI, or owner gates.