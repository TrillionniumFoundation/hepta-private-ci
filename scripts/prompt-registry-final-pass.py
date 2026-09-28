#!/usr/bin/env python3
"""Isolated source authoring; no patcher is copied into the delivery tree."""
from pathlib import Path
import re
import subprocess
import sys
root = Path(sys.argv[1]).resolve()
tooling = Path(__file__).resolve().parent
subprocess.run([sys.executable, str(tooling / 'prompt-registry-finish-source.py'), str(root)], check=True)
path = root / 'scripts/hepta-prompt-registry-map.py'
text = path.read_text()
# The committed owner has no separate prompt_runtime_commit.rs. Map the actual
# owner and lease-store files instead of a guessed split-file design.
phantom = '    "codex-rs/hepta-agentd/src/prompt_runtime_commit.rs",\n'
if text.count(phantom) != 1:
    raise SystemExit('unexpected source inventory')
text = text.replace(phantom, '')
old = '    paths = sorted(git("ls-files", "--", *INPUTS).splitlines())'
new = '''    committed_paths = git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    paths = sorted(path for path in committed_paths
                   if any(path == item or path.startswith(item + "/") for item in INPUTS))'''
if text.count(old) != 1:
    raise SystemExit('source inventory anchor changed')
text = text.replace(old, new)
path.write_text(text)
path = root / 'codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs'
text = path.read_text()
helpers, tests = text.split('#[test]', 1)
helpers, replaced = re.subn(r'\.expect\("([^"\n]*)"\)', lambda m: '.unwrap_or_else(|error| panic!("' + m.group(1) + ': {error}"))', helpers)
if replaced == 0:
    raise SystemExit('no reviewed helper expect calls found')
path.write_text(helpers + '#[test]' + tests)
print('Replaced', replaced, 'fallible test-helper expects; no lint suppression or weakened assertions')
for name in ['scripts/hepta-prompt-registry-map.py', 'scripts/hepta-prompt-registry-qualify.py']:
    compile((root/name).read_text(), name, 'exec')
