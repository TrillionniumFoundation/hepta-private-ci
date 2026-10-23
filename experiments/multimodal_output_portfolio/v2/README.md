# Controlled multimodal generation, v2

This is the next implementation stage of the existing learned four-modality pilot. The v1/v1.1 source, protocol and negative confirmation remain intact. This protocol is frozen before new heldout generation; implementation and independent checks precede the source-frozen confirmation run.

The extension exposes initialization, each residual refinement and one immutable all-modality emission. A finite controller chooses acquisitions, a supported semantic portfolio and a generation depth while charging every acquisition, initialization, refinement, emission and modeled decision overhead. Its generation depth is selected at commitment; it does not yet adapt to newly observed latent failures within refinement.

A separate fine-tuning stage reselects a finite recursive policy and differentiates its recursive entropic utility through the actual generator's terminal losses. Encoders and the calibration law remain fixed. The objective uses the external loss, including clipped raw error and locally constant discrete contradiction. Gradients are piecewise, not a smooth global-optimality guarantee. New controls do not change the definition of NDU in the canonical registry.

`protocol.json` defines data separation, training budget, comparisons and gates. A passing software gate does not imply an empirical benefit, dedicated-host execution, native runtime integration or foundation-model capability. Each is tracked separately in the blocker ledger and results.

The initial local environment was repaired by installing pinned NumPy1.26.4 and PyTorch2.5.1 CPU into an isolated environment. No pretrained-model download or external model API is required for this closed synthetic mechanism experiment.
