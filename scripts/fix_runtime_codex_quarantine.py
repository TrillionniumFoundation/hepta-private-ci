#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs"
text = PATH.read_text(encoding="utf-8")

old = '''        let signed = signed(&key, proposal);
        assert!(matches!(
            verifier(&key).verify(&signed, &quarantine, 2_000),
'''
new = '''        let wrong_revision = signed(&key, proposal);
        assert!(matches!(
            verifier(&key).verify(&wrong_revision, &quarantine, 2_000),
'''
if text.count(old) != 1:
    raise SystemExit("expected exactly one shadowed signed-resolution fixture")
text = text.replace(old, new)

old = '''            || self.authority_epoch == 0
            || self.agent_generation == 0
'''
new = '''            || self.authority_epoch == 0
            || self.revocation_revision == 0
            || self.agent_generation == 0
'''
if text.count(old) != 1:
    raise SystemExit("expected exactly one quarantine state validation block")
text = text.replace(old, new)
PATH.write_text(text, encoding="utf-8")
