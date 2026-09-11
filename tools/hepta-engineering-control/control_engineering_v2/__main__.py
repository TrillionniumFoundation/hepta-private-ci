"""Read-only import and registry self-check for the Lane G package."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    components = json.loads((root / "COMPONENTS.json").read_text(encoding="utf-8"))
    traceability = json.loads((root / "TRACEABILITY.json").read_text(encoding="utf-8"))
    result = {
        "schema": "hepta.control-engineering-self-check.v1",
        "components": len(components["components"]),
        "operations": len(traceability["operations"]),
        "authorityGranted": False,
        "externalGatesPassed": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
