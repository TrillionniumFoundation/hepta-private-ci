"""Public action support and observed content effects, without quality labels.

Image bytes are immutable within an episode. A second read of the same current
ROI releases no new observation. Filenames are storage locations, not content:
renaming a crop must not manufacture an action effect or a feature-cache miss.
"""

from .controllers import ACTIONS
from .metering import canonical_sha


def public_actions(packet, state):
    """Share the host's executable public support with every controller."""
    observed, prepared = state["observation"], state["prepared_roi"]
    current_roi = observed["kind"] == "roi" and observed["bbox"] == prepared
    return tuple(
        action
        for action in ACTIONS
        if not (action == "READ_ROI" and (prepared is None or current_roi))
        and not (action == "WRITE_TEXT" and state["text_committed"])
        and not (
            action == "RENDER_IMAGE"
            and (
                not packet["requirements"]["image"]
                or packet["initial_delivery"]["image"] is not None
            )
        )
    )


def observation_key(packet, observed):
    """Bind pixel features to their source-coordinate and public text context.

    Raw OCR can be shared by pixel digest. Its mapped candidates cannot: identical
    pixels at two source locations have different source coordinates and features.
    """
    return canonical_sha(
        {
            "schema": "ndu.real.observation-context.v1",
            "image_sha256": observed["sha256"],
            "bbox": observed["bbox"],
            "kind": observed["kind"],
            "prompt": packet["prompt"],
            "source_size": packet["source_size"],
            "public_text": packet["public_text"],
        }
    )


def public_content(prepared, observed, delivery):
    """Return value-owned content digests before the host mutates its state."""
    image = delivery["image"]
    return {
        "preparation": canonical_sha(prepared),
        "observation": canonical_sha(
            {key: observed[key] for key in ("sha256", "bbox", "kind")}
        ),
        "text": canonical_sha(delivery["text"]),
        "image": canonical_sha(
            None if image is None else {key: image[key] for key in ("sha256", "bbox")}
        ),
    }


def action_effect(action, before, after):
    """Receipt of executed byte/geometry changes; semantic gain is unmeasured."""
    changed = [key for key in before if before[key] != after[key]]
    return {
        "schema": "ndu.real.action-effect.v1",
        "action": action,
        "before": before,
        "after": after,
        "changed": changed,
        "outcome": "terminal"
        if action == "STOP"
        else "state_changed"
        if changed
        else "no_public_change",
        "semantic_quality_gain": None,
    }
