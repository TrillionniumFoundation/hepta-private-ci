"""Fail-closed Transformers 5 shim for the pinned Arctic *CPU shadow* only.

The frozen GTE custom model expects a removed PreTrainedModel helper. This
restricted test path feeds exactly one unpadded sequence per forward, so the
v4 extended additive attention bias is identically zero. No general-purpose
attention-mask emulation, publisher modification or production authorization.
"""
from importlib import metadata
from types import MethodType

METHOD = "arctic_single_unpadded_gte_mask_v1"
SCOPE = "single_row_unpadded_cpu_float32_shadow_only"


def install_arctic_unpadded_mask(encoder) -> dict:
    import torch

    cfg = getattr(encoder, "config", None)
    if (metadata.version("transformers") != "5.20.2"
            or type(encoder).__name__ != "GteModel"
            or cfg is None
            or getattr(cfg, "use_memory_efficient_attention", None) is not False
            or getattr(cfg, "unpad_inputs", None) is not False
            or getattr(encoder, "get_extended_attention_mask", None) is not None):
        raise ValueError("unexpected pinned Arctic attention API or CPU mode")
    params = list(encoder.parameters())
    if (not params or any(p.device.type != "cpu" or p.dtype != torch.float32
                          for p in params)):
        raise ValueError("Arctic attention shim requires loaded CPU float32 parameters")

    def unpadded_mask(_self, attention_mask, input_shape):
        # Deliberately refuse padded, batched, fractional and non-CPU inputs.
        # The historical v4 additive mask is 0 for an all-ones mask.
        if (not isinstance(attention_mask, torch.Tensor)
                or attention_mask.device.type != "cpu"
                or attention_mask.dtype not in (torch.long, torch.bool)
                or not isinstance(input_shape, (tuple, torch.Size))
                or len(input_shape) != 2 or input_shape[0] != 1
                or type(input_shape[1]) is not int or not 0 < input_shape[1] <= 192
                or tuple(attention_mask.shape) != tuple(input_shape)
                or not bool(torch.all(attention_mask == 1))):
            raise ValueError("Arctic shadow requires one unpadded bounded binary mask")
        return torch.zeros((1, 1, 1, input_shape[1]), dtype=torch.float32)

    encoder.get_extended_attention_mask = MethodType(unpadded_mask, encoder)
    return {"method": METHOD, "scope": SCOPE, "transformers_version": "5.20.2",
            "production_qualified": False}
