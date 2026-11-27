"""Complete source bytes and actual exact typed operations for this fixture."""

import hashlib
from pathlib import Path
import time
import zlib

from exact_baselines import measure_baselines
from population_fixtures import dataset, exact_baseline, source_digest
from quantized_adapter import canonical_bytes


def measure_exact(data, output, write_json):
    output = Path(output)
    regenerated = dataset(data["seed"])["sources"]
    if (
        not source_digest(data["sources"])
        == data["sources_sha256"]
        == source_digest(regenerated)
    ):
        raise ValueError(
            "public seed/generator does not reproduce the measured complete source ledger"
        )
    result = measure_baselines(data["sources"], output)
    start = time.perf_counter()
    probes = data["retention_final"] + data["transfer_final"] + data["ood_final"]
    answers = []
    for probe in probes:
        answer, roots = exact_baseline(data["sources"], probe["operation"])
        answers.append(
            {
                "probe_id": probe["probe_id"],
                "answer": answer,
                "roots": roots,
                "exact": answer == probe["value"],
            }
        )
    result["typed_operation_seconds"] = time.perf_counter() - start
    result["typed_operation_exact"] = sum(row["exact"] for row in answers) / len(
        answers
    )
    result["typed_operation_rows"] = answers
    result["typed_operation_input"] = (
        "supplied structured operation, not natural-language parsing"
    )
    result["source_ledger_semantically_complete"] = True
    # This synthetic fixture is deterministic. Charge the actual retained generator;
    # do not describe its realized assignments as an irreducible entropy lower bound.
    source = Path(__file__).with_name("population_fixtures.py").read_bytes()
    seed = canonical_bytes(
        {"seed": data["seed"], "source_sha256": hashlib.sha256(source).hexdigest()}
    )
    bundle = len(seed).to_bytes(4, "little") + seed + source
    generator_rows = {}
    for name, payload in (
        ("seed-and-generator.bin", bundle),
        ("seed-and-generator.zlib9", zlib.compress(bundle, 9)),
    ):
        (output / name).write_bytes(payload)
        generator_rows[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "lossless": True,
            "requires_python_standard_library": True,
        }
    result["measurements"].update(generator_rows)
    if zlib.decompress((output / "seed-and-generator.zlib9").read_bytes()) != bundle:
        raise ValueError("generator compression round trip failed")
    complete = result["measurements"]
    best = min(complete, key=lambda name: complete[name]["bytes"])
    result["smallest_complete_exact_representation"] = {"name": best, **complete[best]}
    result[
        "runtime_and_operation_implementation_bytes_excluded_from_data_only_baselines"
    ] = True
    result["irreducible_entropy_bound_claimed"] = False
    write_json(output / "population-baseline.json", result)
    return result
