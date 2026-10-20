"""Read explicit repository-local diagnostic opt-ins; absence keeps them off."""

import json
import sys
from pathlib import Path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate diagnostic configuration key")
        result[key] = value
    return result


def diagnostic_options(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {"feature": False, "maximum": False}
    if path.stat().st_size > 1024:
        raise ValueError("diagnostic configuration exceeds 1024 bytes")
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=unique_object
    )
    if not isinstance(value, dict) or set(value) != {"feature", "maximum"}:
        raise ValueError("diagnostic configuration requires feature and maximum only")
    if any(type(item) is not bool for item in value.values()):
        raise ValueError("diagnostic options must be booleans")
    if value["maximum"] and not value["feature"]:
        raise ValueError("maximum diagnostic requires the diagnostic feature")
    return value


if __name__ == "__main__":
    path = (
        Path(sys.argv[1])
        if len(sys.argv) == 2
        else Path(".github/hepta-cognitive-diagnostic.json")
    )
    for name, enabled in diagnostic_options(path).items():
        print(f"{name}={str(enabled).lower()}")
