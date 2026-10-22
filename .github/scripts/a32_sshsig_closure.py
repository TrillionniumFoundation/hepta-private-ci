"""Structured configured-closure identity admission, ported from reviewed Mac v2."""
import re

from a32_sshsig_guard import require


def forbidden_closure_label(label):
    parts = re.fullmatch(r'(?:(@{1,2}[^/]*))?//([^:]*):([^:]+)', label)
    require(parts is not None, f'malformed configured dependency label: {label}')
    repository, package, target = parts.groups()
    if re.match(r'^codex-rs/(?:core|cli|code-mode|code_mode|code-mode-host|code_mode_host|v8-poc)(?:/|$)', package, re.I):
        return True
    v8_identity = r'(^|[/@_+~.-])(?:lib)?(?:rusty[_-]?)?v8(?=$|[/_+~.-])'
    # Repository/package identities catch every file or rule in real V8 trees.
    # A source target such as uuid//:src/v8.rs is not a V8 repository/package.
    if re.search(v8_identity, repository or '', re.I) or re.search(v8_identity, package, re.I):
        return True
    target_identity = target.rsplit('/', 1)[-1]
    for suffix in ('.a', '.so', '.dylib', '.dll', '.lib'):
        if target_identity.lower().endswith(suffix):
            target_identity = target_identity[:-len(suffix)]
            break
    # Match rule/archive identifiers, not arbitrary source-file basenames.
    # Real V8 source-file targets still fail the repository/package checks above.
    return re.fullmatch(r'[A-Za-z0-9_+~-]+(?:\.[0-9]+)*', target_identity) is not None and re.search(v8_identity, target_identity, re.I) is not None



def validate_closure(data, owners):
    labels = sorted({line.split()[0] for line in data.decode().splitlines() if line.startswith(('//', '@'))})
    require(set(owners) <= set(labels), 'configured owner missing/incompatible')
    forbidden = [label for label in labels if forbidden_closure_label(label)]
    require(not forbidden, 'unreviewed V8/full-CLI configured closure; stop, do not prune dependencies: ' + repr(forbidden))
    return labels
