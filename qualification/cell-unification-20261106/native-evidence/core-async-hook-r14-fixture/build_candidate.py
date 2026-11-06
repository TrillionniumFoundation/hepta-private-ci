from pathlib import Path
import difflib
import hashlib
import json
import re

ROOT = Path('/workspace/scratch/08f5efd48967')
OUT = ROOT / 'core-async-hook-r14-fixture'
PATH = 'codex-rs/core/tests/suite/hooks.rs'
original = (ROOT / 'core-hooks-r14-audit/original' / PATH).read_bytes()
assert hashlib.sha256(original).hexdigest() == '1e2ff42aec153e3dec972343890bf4d970ab406e3076e089714613bf401a4bdb'
text = original.decode()
ops = []

def replace(before, after):
    global text
    assert text.count(before) == 1, before[:100]
    text = text.replace(before, after, 1)
    ops.append({'before': before, 'after': after})

replace(
    'fn write_async_user_prompt_submit_hook(home: &Path, gated: bool) -> Result<()> {',
    '''fn write_async_user_prompt_submit_hook(
    home: &Path,
    gated: bool,
    observed_prompt: &str,
) -> Result<()> {''',
)
replace(
    '''prompt = json.load(sys.stdin).get("prompt")
Path(r"{started_path}").write_text(prompt, encoding="utf-8")''',
    '''prompt = json.load(sys.stdin).get("prompt")
if prompt != {observed_prompt_json}:
    sys.exit(0)
Path(r"{started_path}").write_text(prompt, encoding="utf-8")''',
)
replace(
    '''        gated = if gated { "True" } else { "False" },
''',
    '''        gated = if gated { "True" } else { "False" },
        observed_prompt_json = serde_json::to_string(observed_prompt)?,
''',
)
replace(
    '''            write_async_user_prompt_submit_hook(home, /*gated*/ false)
                .expect("write immediate async user prompt submit hook");''',
    '''            write_async_user_prompt_submit_hook(
                home,
                /*gated*/ false,
                "observe async context immediately",
            )
            .expect("write immediate async user prompt submit hook");''',
)
replace(
    '''            write_async_user_prompt_submit_hook(home, /*gated*/ true)
                .expect("write gated async user prompt submit hook");''',
    '''            write_async_user_prompt_submit_hook(
                home,
                /*gated*/ true,
                "finish before the async hook",
            )
            .expect("write gated async user prompt submit hook");''',
)

inverse = text
for op in reversed(ops):
    assert inverse.count(op['after']) == 1
    inverse = inverse.replace(op['after'], op['before'], 1)
assert inverse.encode() == original
dest = OUT / 'source' / PATH
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(text)
patch = ''.join(difflib.unified_diff(original.decode().splitlines(keepends=True), text.splitlines(keepends=True), fromfile='a/' + PATH, tofile='b/' + PATH))
(OUT / 'repair.patch').write_text(patch)
(OUT / 'edit-operations.json').write_text(json.dumps(ops, indent=2) + '\n')

def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

# No assertion, timeout, mock response, submission or event observation is edited.
for op in ops:
    assert not re.search(r'\bassert(?:_eq|_ne)?!', op['before'])
    assert 'Duration::' not in op['before']
assert len(re.findall(r'\bassert(?:_eq|_ne)?!', text)) == len(re.findall(r'\bassert(?:_eq|_ne)?!', original.decode()))
manifest = {'base_commit': 'b44d4ca4aa0ef9f894eff29e9975938e066a82f5', 'base_tree': 'd3d2313b838422818bf9448ce5a1b86d89abdf69', 'files': [{'path': PATH, 'git_mode': '100644', 'before': identity(original), 'after': identity(dest.read_bytes()), 'exact_inverse': True}], 'patch': identity(patch.encode())}
(OUT / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
