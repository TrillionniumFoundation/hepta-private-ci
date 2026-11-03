"""Regenerate small native runtime fixtures by actually fitting every shard."""

import json
from pathlib import Path

from population_training import sha, train_populations
from test_training import fixture
from training import current_rows


def main():
    export = fixture(12)
    config = {"shard_count": 2, "seed": 43, "steps": 180, "dimension": 16, "total_hidden": 24, "threshold": 0.9}
    result = train_populations(export, config)
    destination = Path(__file__).resolve().parents[2] / "codex-rs/hepta-neuron/tests/fixtures/associative-memory"
    expected = {"schema": "hepta.memory.population-fixture.v2", "synthetic_fixture": True,
        "independent_evaluation": False, "configuration": config, "types": {}, "fit_receipt": result["receipt"]}
    for kind, rows in current_rows(export).items():
        raw = result["artifacts"][kind]["native"].encode()
        (destination / f"population.{kind}.native.json").write_bytes(raw)
        expected["types"][kind] = {"native_digest": sha(raw), "rows": [
            {"entity": row["record"]["entity"], "value": row["record"]["value"], "source_id": row["source_id"]}
            for row in rows]}
    (destination / "population.expected.json").write_text(json.dumps(expected, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
