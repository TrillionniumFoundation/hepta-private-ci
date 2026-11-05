"""Reload registered external adapters with each actual backbone activation."""

from pathlib import Path

from .local_models import LocalModels


class AdaptedLocalModels(LocalModels):
    """Frozen bases plus learned output parameters; activation costs stay in actions."""

    def __init__(self, vlm_dir, sd_dir, adapters, threads=2):
        super().__init__(vlm_dir, sd_dir, threads)
        if set(adapters) != {"vlm", "sd"}:
            raise ValueError("Register checkpoint path and SHA for both model families")
        self._adapters = {key: {"path": str(Path(spec["path"])), "sha256": spec["sha256"]}
                          for key, spec in adapters.items()}
        self._adapter = self._adapter_hook = self._adapter_family = None
        self.adapter_activations = []

    def _detach_adapter(self):
        handle, self._adapter_hook = self._adapter_hook, None
        self._adapter = self._adapter_family = None
        if handle is not None:
            handle.remove()

    def _activate(self, key):
        if key not in self._adapters:
            raise ValueError("Unknown model family")
        if self.active == key and self._adapter_family == key and self._adapter_hook is not None:
            return
        attempt = {"family": key, **self._adapters[key], "status": "loading"}
        self.adapter_activations.append(attempt)
        try:
            self._detach_adapter()
            super()._activate(key)
            if key == "vlm":
                from .train_adapter import load_adapter
                model = self.model
            else:
                from .train_image_adapter import load_image_adapter as load_adapter
                model = self.pipeline.unet
            self._adapter, self._adapter_hook = load_adapter(model, attempt["path"], attempt["sha256"])
            self._adapter_family = key
            attempt["status"] = "verified"
        except (Exception, KeyboardInterrupt) as exc:
            attempt["status"] = ("cancelled" if isinstance(exc, KeyboardInterrupt) else
                                 "timeout" if isinstance(exc, TimeoutError) else "failed")
            attempt["error_type"] = type(exc).__name__
            self._detach_adapter()
            self.active = None
            self.model = self.processor = self.pipeline = self.img2img = None
            raise

    def identity(self):
        result = super().identity()
        result.update(backend="local_pretrained_with_registered_output_adapters",
                      base_parameters_frozen=True, generator_adaptation="external_learned_output_parameters",
                      registered_adapters={k: dict(v) for k, v in self._adapters.items()},
                      active_adapter=self._adapter_family,
                      adapter_activations=[dict(row) for row in self.adapter_activations],
                      adapter_cost_scope="verification_and_installation_inside_each_backend_action")
        return result
