# Relocating the clock review without changing its source

Preparation only; no review or experiment has been rerun.

The historical `clock_semantics_review.py` has three path globals: `TARGET`,
`CORE`, and `OUT`. Its computations are ordinary functions using that module's
global dictionary. A separate wrapper can load the script under a non-main name,
replace those three in-memory paths, and invoke `main()`. The original script,
frozen study sources/protocol, and previous receipt remain byte-for-byte intact.

Use an **entirely new output directory**, and keep this wrapper outside the frozen
study root. The study runner hashes every top-level `.py` file; placing a new
wrapper there would change its frozen source inventory.

Example wrapper (not executed during preparation):

```python
from pathlib import Path
import hashlib
import json
import runpy

script = Path('/path/to/clock_semantics_review.py').resolve()
target = Path('/path/to/ndu_clock_semantics_20261106').resolve()
core = Path('/path/to/retained/ndu_jac/core.py').resolve()
out = Path('/path/to/new-clock-review-output').resolve()

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(script) == '849ab9f9fcbc6b42bef8d72d5c32175332840a6d1d0cfa1807639023569c8056'
assert sha(core) == 'a04d3a1cc038448e9a2f7fc5f5336c60a80f06171833517f045e90cf7a1b6578'
out.mkdir(parents=True, exist_ok=False)

loaded = runpy.run_path(str(script), run_name='clock_review_relocated')
# Mutate the function's actual globals, not merely the returned mapping:
# runpy may return a separate shallow mapping.
module_globals = loaded['main'].__globals__
module_globals['TARGET'] = target
module_globals['CORE'] = core
module_globals['OUT'] = out
loaded['main']()

(out / 'relocation-receipt.json').write_text(json.dumps({
    'kind': 'same_authored_review_replay_with_explicit_path_relocation',
    'original_review_script_sha256': sha(script),
    'retained_core_sha256': sha(core),
    'target': str(target),
    'core': str(core),
    'output': str(out),
    'source_files_modified': False,
    'additional_independent_or_external_review_claimed': False,
}, indent=2) + '\n')
```

The original script checks its target's freeze and original result bindings,
computes before/after source hashes, and creates its output JSON exclusively.
A corrected THEORY/README can coexist with the same frozen `.py`/protocol/result;
a replay's hashes will identify the actual documentation it read. It is a new
replay receipt, not an overwrite or reinterpretation of the original 266-check
review. The script's hardcoded reviewer identifier denotes its original author;
reusing that script is not another independent or external review.

No Torch, model files, network endpoint, model forward or actual task worker is
needed. The review uses Python standard-library mathematics, dynamically imports
the checked retained finite JAC evaluator, and reads the existing study evidence.
The 81-cell primary grid remains unchanged. This note describes a replay method;
it does not claim this relocated command has been executed.
