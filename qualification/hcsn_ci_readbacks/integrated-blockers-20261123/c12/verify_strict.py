"""Compare two original GitHub job logs to the qualified list of compiler diagnostics."""
from collections import Counter
import argparse
import json
from pathlib import Path
import re

here = Path(__file__).resolve().parent
reference = json.loads((here.parent/"combined-43e5/strict-remaining.json").read_text())["diagnostics"]
fields = ("path", "line", "column", "diagnostic")
expected = Counter(tuple(row[key] for key in fields) for row in reference)

def inspect(log):
    clean = re.sub(r"\x1b\[[0-9;]+m", "", log)
    clean = re.sub(r"^\d{4}-\d+-\d+T[\d:.]+Z ", "", clean, flags=re.M)
    matches = re.finditer(r"^error: ([^\n]+)\n\s*-->\s*(\S+\.rs):(\d+):(\d+)\s*$", clean, re.M)
    observed = Counter(("codex-rs/"+path, int(line), int(col), text)
                       for text, path, line, col in (m.groups() for m in matches))
    assert "could not compile `codex-hepta-agentd` (lib) due to 115 previous errors" in clean
    assert observed == expected
    return sum(observed.values())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_job_log", type=Path)
    parser.add_argument("merge_job_log", type=Path)
    args = parser.parse_args()
    for file in (args.source_job_log,args.merge_job_log):
        print(file.name, inspect(file.read_text(encoding="utf-8")))
