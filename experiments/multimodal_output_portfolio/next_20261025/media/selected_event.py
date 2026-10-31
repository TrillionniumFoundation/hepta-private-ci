"""Explicit development-selected ASR identity; original observer bytes stay fixed."""

from .event_observer import EventWaveAudit, RECIPE
from .runtime import score_observation


PRIMARY, SECONDARY = "base.en", "small.en"


class SelectedEventWaveAudit(EventWaveAudit):
    """Same frozen event transform, with the primary identity selected on old dev."""

    def __init__(self, assets, output):
        super().__init__(assets, output)
        self.receipt = {**self.receipt, "recipe": {**RECIPE, "primary": PRIMARY, "secondary": SECONDARY},
                        "selection": "60 old qualification events are development only; base 50/60 versus small 46/60",
                        "v1_primary_small_failed": True}

    def observe_pcm(self, pcm, carrier=True):
        return {**super().observe_pcm(pcm, carrier), "primary_observer": PRIMARY,
                "secondary_observer": SECONDARY}


def score_selected_observation(observed, expected):
    """Score the named primary after observation without relabeling its model ID."""
    result = score_observation(observed, expected)
    success = {**result["success"], "audio": observed["speech"]["predictions"][PRIMARY] == list(expected)}
    return {**result, "success": success,
            "joint_success": all(success.values()) and observed["content_checks"]["moving_video"]
                             and observed["content_checks"]["nonempty_audio"],
            "secondary_audio_success": observed["speech"]["predictions"][SECONDARY] == list(expected),
            "primary_observer": PRIMARY, "secondary_observer": SECONDARY}
