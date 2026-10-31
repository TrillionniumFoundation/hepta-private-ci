"""Frozen unrestricted speech observation, separated from target scoring."""

import re
from pathlib import Path

from ...abc_next.temporal.external import ExternalObserver


WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def parse_digits(transcript, carrier=False):
    """Parse exact digit content without correcting recognized lexical errors."""
    result = []
    for token in re.findall(r"[a-z]+|[0-9]+", transcript.lower()):
        if token in WORDS:
            result.append(WORDS.index(token))
        elif token.isdigit() and len(token) <= 2:
            result.extend(int(value) for value in token)
        elif carrier and token in {"the", "digit", "is"}:
            continue
        else:
            return None
    return result if len(result) == 2 else None


class FrozenSpeechObservers:
    """Two separately frozen model sizes, with shared-family dependence declared."""

    def __init__(self, assets):
        assets = Path(assets)
        self.models = {name: ExternalObserver(assets / ("whisper-" + name))
                       for name in ("base.en", "small.en")}
        self.receipt = {name: model.load_receipt for name, model in self.models.items()}

    def observe(self, actual_waveform_path, carrier=False):
        observations = {name: model.observe(actual_waveform_path)
                        for name, model in self.models.items()}
        return {"observations": observations,
                "predictions": {name: parse_digits(row["transcript"], carrier)
                                for name, row in observations.items()},
                "target_supplied": False,
                "observer_family_independence_claimed": False}
