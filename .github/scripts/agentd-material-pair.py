"""Compare source-bound operator material tests and original strict diagnostics."""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

OUT = Path(os.environ["RUNNER_TEMP"]) / "material-projection-evidence"
ARMS = ("base", "candidate")
PREFIXES = {
    "circuit_original_evaluation_model_material_tests.rs": ("original_evaluation_model_material_", 13),
    "neuron_cell_evaluation_model_material_codec_tests.rs": ("original_model_material_codec_", 8),
}


def native():
    records = {}
    for arm in ARMS:
        work = OUT.parent / ("source-private-" + arm)
        binary = OUT.parent / ("agentd-private-" + arm)
        with binary.open("rb") as stream:
            elf_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        roster = subprocess.check_output([binary, "--list"], cwd=work, text=True)
        (OUT / (arm + ".libtest.txt")).write_text(roster)
        names = re.findall(r"^(.+): test$", roster, re.M)
        cases = []
        for fixture, (prefix, expected) in PREFIXES.items():
            source = (work / "codex-rs/hepta-agentd/src" / fixture).read_text()
            original = set(re.findall(r"(?m)^(?:async )?fn (" + prefix + r"\w+)\(", source))
            selected = [n for n in names if n.rsplit("::", 1)[-1] in original]
            assert len(original) == len(selected) == expected, (fixture, selected)
            cases.extend(sorted(selected))
        # Each original case receives its own exact filter and fresh process.
        row = {}
        for name in cases:
            result = subprocess.run([binary, "--exact", name, "--test-threads=1"], cwd=work,
                                    text=True, capture_output=True, timeout=240)
            log = result.stdout + result.stderr
            (OUT / (arm + "-" + name.replace("::","_") + ".log")).write_text(log)
            row[name] = result.returncode == 0 and "1 passed; 0 failed; 0 ignored;" in log
        records[arm] = {"source": os.environ[arm.upper()],
                        "elf": elf_sha, "cases": row}
        print(arm, elf_sha, sum(row.values()), "of", len(row), flush=True)
    (OUT / "native.json").write_text(json.dumps(records, indent=2) + "\n")
    assert records["base"]["cases"].keys() == records["candidate"]["cases"].keys()
    assert all(all(r["cases"].values()) for r in records.values()), records


def strict():
    all_rows = {}
    for arm in ARMS:
        text = (OUT / ("strict-" + arm + ".log")).read_text()
        errors = collections.Counter()
        for block in re.split(r"(?m)^error(?:\[E\d+\])?: ", text)[1:]:
            finding = block.splitlines()[0]
            if finding.startswith("could not compile"):
                continue
            span = re.search(r"(?m)^\s*-->\s+([^:\s]+):\d+:\d+", block)
            errors[(span[1] if span else "<no source>", finding)] += 1
        assert re.search(r"could not compile .codex-hepta-agentd.* due to \d+ previous errors", text)
        all_rows[arm] = errors
    before, after = [all_rows[a] for a in ARMS]
    delta = {"before": before.total(), "after": after.total(),
             "resolved": sorted((before - after).elements()), "new": sorted((after - before).elements())}
    print(json.dumps(delta, indent=2), flush=True)
    (OUT / "strict.json").write_text(json.dumps(delta, indent=2) + "\n")
    expected = [
        ("hepta-agentd/src/neuron_cell_evaluation_model_material_member.rs", "field `estimand` is never read"),
        ("hepta-agentd/src/neuron_cell_evaluation_model_material_wire.rs", "method `context` is never used"),
    ]
    assert (delta["before"], delta["after"], delta["resolved"], delta["new"]) == (128, 126, expected, [])


if __name__ == "__main__":
    {"native": native, "strict": strict}[sys.argv[1]]()
