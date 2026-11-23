"""Exhaust the 12 prespecified HAPT posture/confidence cells for one paid-in-time waiting block."""
import argparse
import hashlib
import io
import json
import math
from decimal import Decimal, localcontext
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from wait_cells import BINS, POSTURES


def subject_data(data):
    confidence = data["scores"][:, 0].max(axis=1)
    cell = data["posture"] * 4 + np.searchsorted(BINS[1:], confidence, side="right")
    assert ((cell >= 0) & (cell < 12)).all()
    correct = (data["scores"].argmax(-1) == data["target"][:, None]).astype(int)
    groups = sorted(set(data["group"]))
    # A waited query adds (2 + next correct) * exp(-.096) - (2 + current correct).
    per_person = []
    for group in groups:
        same = data["group"] == group
        columns = []
        for c in range(12):
            chosen = same & (cell == c)
            columns.append((int((2+correct[chosen,1]).sum()), int((2+correct[chosen,0]).sum())))
        per_person.append((int(same.sum()), columns))
    return per_person


def evaluate(rows, chosen, discount):
    gains = []
    for n, columns in rows:
        a = sum(columns[c][0] for c in chosen)
        b = sum(columns[c][1] for c in chosen)
        gains.append((discount*a-b)/n)
    n = len(gains)
    wins = sum(v > 0 for v in gains)
    tail = sum(math.comb(n,i) for i in range(wins,n+1))
    gain = sum(gains)/n
    passed = gain >= Decimal(".015") and wins >= 2 and tail*20 <= 2**n
    return gain,wins,tail,passed


def calculate(folder):
    manifest = json.loads((folder/"archive_parts.json").read_text())
    seal = json.loads((folder/"fit_seal.json").read_text())
    parts = []
    for filename, rec in sorted(manifest["parts"].items()):
        raw = (folder/filename).read_bytes()
        assert len(raw)==rec["size"] and hashlib.sha256(raw).hexdigest()==rec["sha256"]
        parts.append(raw)
    payload = b"".join(parts)
    assert hashlib.sha256(payload).hexdigest()==manifest["zip_sha256"]
    panels, original_means = {}, {}
    with ZipFile(io.BytesIO(payload)) as z:
        direct = z.read("development.json")
        assert hashlib.sha256(direct).hexdigest()==seal["files"]["development.json"]
        original = json.loads(direct)
        all_actions = (np.arange(4096)[:, None] & (1 << np.arange(12))) != 0
        for name in ("train","dev"):
            key=name+".npz"
            raw=z.read(key)
            assert hashlib.sha256(raw).hexdigest()==seal["files"][key]
            with np.load(io.BytesIO(raw), allow_pickle=False) as data:
                panels[name]=subject_data(data)
                # Independently use the originally published per-query utilities of the two fixed exits.
                fixed = original[name]["fixed_exits"]
                delta = np.array(fixed["0-1"]["u"]) - np.array(fixed["0-0"]["u"])
                group = data["group"]
                weight = np.zeros(len(delta))
                for person in set(group):
                    weight[group==person] = 1/(np.sum(group==person)*len(set(group)))
                confidence = data["scores"][:,0].max(1)
                cell_gain = []
                for posture in range(3):
                    for lo, hi in zip(BINS,BINS[1:]):
                        chosen = (data["posture"]==posture) & (confidence>=lo) & (confidence<hi)
                        cell_gain.append(np.sum((weight*delta)[chosen]))
                original_means[name] = all_actions @ np.asarray(cell_gain)
    results = {}
    for precision in (32,64):
        with localcontext() as ctx:
            ctx.prec=precision
            discount = Decimal("-.096").exp()
            n_mean = n_pass = 0
            n_individual = {s:0 for s in panels}
            best = Decimal("-Infinity")
            max_wins = {s:0 for s in panels}
            for mask in range(2**12):
                cells=tuple(i for i in range(12) if mask & (1<<i))
                rr={s:evaluate(rows,cells,discount) for s,rows in panels.items()}
                assert all(abs(float(rr[s][0])-original_means[s][mask])<=1.e-12 for s in panels)
                value=min(row[0] for row in rr.values())
                if value>best: best=value
                n_mean += value>=Decimal(".015")
                n_pass += all(row[3] for row in rr.values())
                for split,row in rr.items():
                    n_individual[split]+=row[3]
                    max_wins[split]=max(max_wins[split],row[1])
            results[precision]={"number_of_tables":2**12,"subjects":{s:len(rows) for s,rows in panels.items()},
                "max_common_source_mean_gain":float(best),"tables_with_mean_gain_at_least_0_015_both":n_mean,
                "tables_passing_all_primary_numeric_criteria_both_splits":n_pass,
                "tables_passing_numeric_criteria_by_split":n_individual,"most_subjects_with_positive_gain_by_split":max_wins}
    assert results[32]==results[64]
    return {"original_fixed_exit_table_replays":2*4096, "archive_sha256":manifest["zip_sha256"],"cells_in_order":[[p,l,min(h,1.)] for p in POSTURES for l,h in zip(BINS,BINS[1:])],**results[64]}


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("evidence",type=Path)
    print(json.dumps(calculate(cli.parse_args().evidence), indent=2, sort_keys=True))
