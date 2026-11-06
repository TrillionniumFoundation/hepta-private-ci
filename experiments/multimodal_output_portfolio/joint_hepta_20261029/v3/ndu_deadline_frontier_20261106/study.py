"""Retain every deterministic deadline/budget cell and its executable certificate."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction as F
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import scipy

from .binary_deadline import minimax
from .frontier import Contract, Tree, encode


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    here = Path(__file__).parent
    inputs = sorted(here.glob("*.py"))+[here/"protocol.json", here.parent/"ndu_identification/model.py"]
    before = {str(p.relative_to(here.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    protocol = json.loads((here/"protocol.json").read_text())
    began, cpu = time.perf_counter(), time.process_time()
    rows, certificates = [], []
    cells = [(Contract(t), None if b is None else F(b))
             for t in protocol["joint_deadlines"] for b in protocol["expected_resource_budgets"]]
    cells += [(Contract(t, family="gated"), None if b is None else F(b))
              for t, b in protocol["gated_cells"]]
    cells += [(Contract(8, max_probes=8, family="bernoulli"), None),
              (Contract.paid_catalog(39, max_probes=13), None)]
    for i, (contract, budget) in enumerate(cells):
        start = time.perf_counter()
        tree = Tree(contract)
        result = tree.solve(budget)
        e, c, mass = tree.evaluate(result["policy"])
        if (e, c, mass) != (result["errors"], result["resources"], (F(1), F(1))):
            raise ArithmeticError("Saved executable policy differs from reported certificate")
        if result["gap"] > F(protocol["maximum_certificate_gap"]):
            raise ArithmeticError("Rational optimality interval exceeds the declared tolerance")
        common = dict(cell=i, contract=asdict(contract), budget=budget)
        row = common | {k: v for k, v in result.items() if k != "policy"}
        row["wall_seconds"] = time.perf_counter()-start
        row["five_percent_status"] = ("FEASIBLE" if result["upper"] <= F(1, 20) else
                                      "IMPOSSIBLE" if result["lower"] > F(1, 20) else "UNRESOLVED")
        rows.append(row)
        certificates.append(common | result)
    binary = [minimax(n) for n in protocol["catalog_sample_caps"]]
    first = next(r for r in binary if r["risk"] <= F(1, 20))
    after = {str(p.relative_to(here.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    if before != after:
        raise ArithmeticError("Source changed during execution")
    raw = json.dumps(certificates, default=encode, sort_keys=True, separators=(",", ":")).encode()
    archive = gzip.compress(raw, mtime=0)
    (output/"certificates.json.gz").write_bytes(archive)
    report = dict(schema="ndu.deadline-frontier.reference.v1", generated_at_utc=datetime.now(timezone.utc).isoformat(),
                  protocol=protocol, source_sha256=before, source_unchanged=True,
                  rows=rows, binary_catalog=binary, smallest_five_percent_sample_cap=first["n"],
                  minimum_complete_macro_model_time=first["hard_model_time"],
                  wall_seconds=time.perf_counter()-began, cpu_seconds=time.process_time()-cpu,
                  python=platform.python_version(), scipy=scipy.__version__,
                  certificate_archive_sha256=hashlib.sha256(archive).hexdigest(),
                  certificate_payload_sha256=hashlib.sha256(raw).hexdigest(),
                  new_observations=0, llm_calls=0, external_api_calls=0,
                  host_currency_cost=None, independent_confirmation=False,
                  scope="Classical finite known-law benchmark; declared model time and prices; not actual tool time or new RL")
    (output/"result.json").write_text(json.dumps(report, default=encode, indent=2)+"\n")
    print(json.dumps({"cells":len(rows), "binary_rows":len(binary),
                      "minimum_samples":first["n"], "minimum_model_time":first["hard_model_time"],
                      "max_gap":float(max(r["gap"] for r in rows)), "wall_seconds":report["wall_seconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
