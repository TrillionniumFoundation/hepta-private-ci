from pathlib import Path
import json
import numpy as np

# Open this notebook from the extracted experiment directory or its parent.
ROOT = Path.cwd()
if not (ROOT / 'results' / 'aggregate.json').exists():
    ROOT = ROOT / 'rrsnn_experiments'
assert (ROOT / 'results' / 'aggregate.json').exists(), 'Extract the full ZIP first.'
summary = json.loads((ROOT / 'results' / 'aggregate.json').read_text())
print(summary['completed_runs'], summary['selected_reference_baseline'])
