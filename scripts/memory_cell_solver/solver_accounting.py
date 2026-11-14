"""Recover observed costs even when a worker exits without a final result."""

import json
from pathlib import Path


def model_observations(output):
    output = Path(output)
    started = list(output.glob("generation-*/query-start.json"))
    responses = list(output.glob("generation-*/response.json"))
    receipts = list(output.glob("generation-*/receipt.json"))
    prompt, generated, measured = 0, 0, 0
    errors = []
    for path in sorted(responses):
        try:
            usage = json.loads(path.read_text())["usage"]
            values = [usage[k] for k in ("prompt_tokens", "completion_tokens")]
            if any(type(v) is not int or v < 0 for v in values):
                raise ValueError("invalid returned usage")
            prompt += values[0]
            generated += values[1]
            measured += 1
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append({"path": str(path), "error": str(error)})
    return {
        "model_queries_started": len(started),
        "model_queries_returned": len(responses),
        "model_queries_with_complete_receipts": len(receipts),
        "responses_with_measured_tokens": measured,
        "prompt_tokens": prompt,
        "generated_tokens": generated,
        "token_totals_are_lower_bounds": len(started) != measured or bool(errors),
        "usage_errors": errors,
        "physical_attention_forwards_not_measured": True,
    }
