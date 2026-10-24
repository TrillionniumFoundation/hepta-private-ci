"""Version an explicit native vision budget without changing the shared owner API."""

from pathlib import Path
import hashlib
import numpy as np

from real_encoder import canonical_sha256
from shared_feature_contract import SharedFeatureError
from shared_feature_extract import SharedFeatureEncoder

SUPPORTED_VISION_BUDGETS = (70, 140, 280, 560, 1120)


def configuration_value(value):
    """Bind native DSP arrays by exact dtype/shape/bytes instead of JSON coercion."""
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject or not np.isfinite(value).all():
            raise SharedFeatureError("finite numeric processor configuration required")
        return {"array_dtype": value.dtype.str, "array_shape": list(value.shape),
                "array_sha256": hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: configuration_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [configuration_value(item) for item in value]
    return value


class BudgetedMediaEncoder(SharedFeatureEncoder):
    def __init__(self, owner, *, vision_soft_tokens=70):
        if (owner.candidate != "embeddinggemma2_740m" or owner.profile != "full"
                or vision_soft_tokens not in SUPPORTED_VISION_BUDGETS):
            raise SharedFeatureError("full EG2 owner and supported native vision budget required")
        from teacher_snapshot import inventory
        from transformers import AutoProcessor
        if inventory(owner.snapshot)["inventory_sha256"] != owner.inventory_sha256:
            raise SharedFeatureError("processor snapshot changed before loading")
        if owner._processor is not None:
            raise SharedFeatureError("set the vision budget before the processor is shared")
        processor = AutoProcessor.from_pretrained(owner.snapshot, local_files_only=True, trust_remote_code=False)
        processor.image_processor.max_soft_tokens = vision_soft_tokens
        owner._processor = processor
        self.vision_soft_tokens = vision_soft_tokens
        super().__init__(owner)
        self.extractor_sha256 = canonical_sha256({"base_extractor_sha256": self.extractor_sha256,
            "budgeted_extractor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "effective_processor": self.processor_configuration()})

    def processor_configuration(self):
        processor = self.owner._processor
        return configuration_value({"declared_vision_soft_tokens": self.vision_soft_tokens,
                "image_processor": processor.image_processor.to_dict(),
                "audio_feature_extractor": processor.feature_extractor.to_dict(),
                "chat_template": processor.chat_template})

    def _configuration_digest(self):
        return canonical_sha256({"base_configuration": super()._configuration_digest(),
                                 "effective_processor": self.processor_configuration()})
