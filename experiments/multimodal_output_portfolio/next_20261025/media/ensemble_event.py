"""Explicit V3 abstention ensemble; frozen V2 ASR and parser remain unchanged."""

from .selected_event import SelectedEventWaveAudit, score_selected_observation


PRIMARY = "consensus_or_single_v3"
SECONDARIES = ("base.en", "small.en")
RULE = "Accept equal nonempty digits or the sole nonempty digit; reject disagreement or two abstentions"


def ensemble_digit(predictions):
    """Only two target-free observer results are available to this function."""
    first, second = (predictions[name] for name in SECONDARIES)
    if any(value is not None and (type(value) is not int or not 0 <= value <= 9)
           for value in (first, second)):
        raise ValueError("Observer output must be a digit or an abstention")
    if first is None:
        return second
    if second is None or first == second:
        return first
    return None


class EnsembleEventWaveAudit(SelectedEventWaveAudit):
    """Combine unchanged model outputs separately for each actual clock event."""

    def __init__(self, assets, output):
        super().__init__(assets, output)
        self.receipt = {**self.receipt,
                        "component_v2_recipe": self.receipt["recipe"],
                        "recipe": {**self.receipt["recipe"], "primary": PRIMARY, "secondary": "base.en"},
                        "v2_recipe_unchanged": True,
                        "primary": PRIMARY, "secondary_observers": SECONDARIES,
                        "ensemble_rule": RULE,
                        "v2_qualification_failed": True,
                        "observer_family_independence_claimed": False}

    def observe_event(self, pcm, carrier):
        raw = super().observe_event(pcm, carrier)
        return {**raw, "predictions": {**raw["predictions"], PRIMARY: ensemble_digit(raw["predictions"])},
                "primary_observer": PRIMARY, "ensemble_rule": RULE}

    def observe_pcm(self, pcm, carrier=True):
        raw = super().observe_pcm(pcm, carrier)
        return {**raw,
                "predictions": {**raw["predictions"], PRIMARY: [event["predictions"][PRIMARY] for event in raw["events"]]},
                "primary_observer": PRIMARY, "secondary_observers": SECONDARIES,
                "ensemble_rule": RULE}


def score_ensemble_observation(observed, expected):
    """Ground truth appears only after the actual target-free observations."""
    result = score_selected_observation(observed, expected)
    success = {**result["success"], "audio": observed["speech"]["predictions"][PRIMARY] == list(expected)}
    return {**result, "success": success,
            "joint_success": all(success.values()) and observed["content_checks"]["moving_video"]
                             and observed["content_checks"]["nonempty_audio"],
            "secondary_audio_success": observed["speech"]["predictions"]["base.en"] == list(expected),
            "secondary_audio_by_model": {name: observed["speech"]["predictions"][name] == list(expected)
                                         for name in SECONDARIES},
            "primary_observer": PRIMARY, "secondary_observer": "base.en"}
