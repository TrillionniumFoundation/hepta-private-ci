"""Use the pinned Makepad --bindgen adapter and real WasmBridge for app tests."""
import hashlib
import re
from collections import Counter
from pathlib import Path

BRIDGE_SHA256 = '209f816c9ddf10ac364ee4a5ca73942104b4d31660c4b9ba799d9408462b3442'
PACKAGER_SHA256 = '45e9e0536cfa61f5f8620abd718103d28d620a70b0e2f631348b9e8247673b54'


def load_pinned_bridge(source):
    source = Path(source)
    bridge = (source / 'libs/wasm_bridge/src/wasm_bridge.js').read_bytes()
    packager = (source / 'tools/cargo_makepad/src/wasm/compile.rs').read_bytes()
    if hashlib.sha256(bridge).hexdigest() != BRIDGE_SHA256:
        raise ValueError('Pinned Makepad bridge hash mismatch')
    if hashlib.sha256(packager).hexdigest() != PACKAGER_SHA256:
        raise ValueError('Pinned Makepad packager hash mismatch')
    return bridge


ENV_IMPORT = re.compile(r'^import \* as (?P<alias>\w+) from [\'\"]env[\'\"];?$')
ENV_MAPPINGS = [re.compile(r'^\s*[\'\"]env[\'\"]:\s*(?P<alias>\w+),?$'),
                re.compile(r'^\s*imports\[[\'\"]env[\'\"]\]\s*=\s*(?P<alias>\w+);$')]


def glue_shape(source):
    """Keep only bounded bootstrap syntax, never full generated assets or fonts."""
    relevant = [line.strip() for line in source.splitlines()
                if re.search(r'''["']env["']''', line) and ('import' in line or ':' in line)]
    return {'sha256': hashlib.sha256(source.encode()).hexdigest(), 'bytes': len(source.encode()),
            'envSyntax': [line[:300] for line in relevant[:256]], 'envSyntaxCount': len(relevant),
            'initShape': [line.strip()[:300] for line in source.splitlines()
                          if line.startswith('async function __wbg_init(')][:2]}


def patch_test_glue(source):
    """Apply the same env/instance adaptation as Makepad493 --bindgen, fail closed.

    The only test-specific extension wraps the default initializer to construct
    the real upstream bridge, then returns its real WASM exports to the unchanged
    official wasm-bindgen test runner. No replacement env functions or test code.
    """
    lines = source.splitlines()
    imports = [(line, ENV_IMPORT.match(line)) for line in lines if ENV_IMPORT.match(line)]
    mappings = [(line, pattern.match(line)) for line in lines for pattern in ENV_MAPPINGS if pattern.match(line)]
    import_aliases = Counter(match['alias'] for _, match in imports)
    mapping_aliases = Counter(match['alias'] for _, match in mappings)
    if (not imports or len(imports) > 128 or import_aliases != mapping_aliases
            or any(count != 1 for count in import_aliases.values())):
        raise ValueError('Unexpected Makepad env import/mapping bijection')
    removed_lines = {line for line, _ in imports + mappings}
    source = '\n'.join(line for line in lines if line not in removed_lines) + '\n'
    replacements = [
        ('return wasm;\n}', 'return instance;\n}', 1),
        ('async function __wbg_init(module_or_path) {',
         'async function __wbg_init(module_or_path, env) {let memory;', 1),
        ('const imports = __wbg_get_imports();',
         'const imports = __wbg_get_imports(); imports.env = env;', 2),
        ('__wbg_init as default', '__hepta_makepad_test_init as default', 1),
    ]
    for before, after, expected in replacements:
        if source.count(before) != expected:
            raise ValueError('wasm-bindgen glue shape drift: ' + before)
        source = source.replace(before, after)
    if re.search(r'from [\'\"]env[\'\"]', source):
        raise ValueError('Unresolved env import remains')
    return source + '''
import { init_env, WasmBridge } from './__makepad_bridge.js';
async function __hepta_makepad_test_init(module_or_path) {
    const env = {};
    const set_wasm = init_env(env);
    const instance = await __wbg_init({module_or_path}, env);
    if (!(instance instanceof WebAssembly.Instance)) {
        throw new Error('Makepad test adapter requires the real WASM instance');
    }
    instance._memory = instance.exports.memory;
    set_wasm(instance);
    const bridge = new WasmBridge(instance, {});
    if (bridge.memory !== instance.exports.memory) {
        throw new Error('Makepad bridge memory binding mismatch');
    }
    globalThis.__hepta_makepad_test_bridge = {initialized: true, implementation: 'Makepad493d23a7 WasmBridge'};
    return instance.exports;
}
'''
