"""Exact IID pilot sensitivity for whether new sources could support the two sign tests."""
import json
from collections import Counter
from fractions import Fraction
from math import comb
from pathlib import Path
from zipfile import ZipFile


def project(multiplicity, n):
    denominator = sum(multiplicity.values())**n
    favorable = 0
    for free_only in range(n+1):
        for both in range(n-free_only+1):
            paid_only = n-free_only-both
            a, b = sorted((free_only+both, paid_only+both))
            if a >= 5 and b >= 6:
                weight = (comb(n, free_only) * comb(n-free_only, both)
                          * multiplicity["free"]**free_only * multiplicity["both"]**both * multiplicity["paid"]**paid_only)
                favorable += weight
    return Fraction(favorable, denominator)


def grouped(trace):
    rescues = {}
    for g, y, a, b in zip(trace["group"], trace["target"], trace["free_answer"], trace["paid_answer"], strict=True):
        rescues.setdefault(g, []).append(a != y and b == y)
    assert all(len(v) == 4 for v in rescues.values())
    return Counter("paid" if not any(v) else "free" if all(v) else "both" for v in rescues.values())


def summarize(counts):
    nn = list(range(4, 33))
    curve = {n: project(counts,n) for n in nn}
    assert all(curve[n] <= curve[n+1] for n in nn[:-1])
    min_size = {str(q): next(n for n in nn if curve[n]>=q) for q in (Fraction(4,5),Fraction(9,10),Fraction(19,20))}
    return {"source_counts": dict(counts), "minimum_sources_for_opportunity_only": min_size,
            "opportunity_feasibility_at_fixed_n": {str(n): round(float(curve[n]), 6) for n in (8, 12, 16, 24)}}


def run():
    import argparse, hashlib
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("frozen_study", type=Path)
    evidence = p.parse_args().frozen_study / "evidence"
    name = "paid-roster-04.zip"
    archive = evidence / name
    manifest = json.loads((evidence / "archive_manifest.json").read_text())["archives"][name]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["sha256"]
    member = "outcomes/train_dev_traces.json"
    with ZipFile(archive) as z:
        raw = z.read(member)
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == manifest["files"][member]["sha256"]
    values = json.loads(raw)
    train = grouped(values["train_out_of_source"])
    dev = grouped(values["dev"])
    pooled = train + dev
    leave_one = {}
    for key in pooled:
        leave_one[key] = summarize(pooled-Counter({key:1}))["minimum_sources_for_opportunity_only"]
    print(json.dumps({"source_sha256": digest, "assumption": "four windows per source; future independent groups drawn with the pilot's three empirical opportunity types; hindsight oracle only",
        "train": summarize(train), "dev": summarize(dev), "pooled": summarize(pooled), "omit_one_source_of_type": leave_one}, indent=2, sort_keys=True))


if __name__ == "__main__":
    run()
