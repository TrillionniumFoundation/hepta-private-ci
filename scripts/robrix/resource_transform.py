"""Execute the exact pinned Makepad JS transform, without reimplementing it."""
import hashlib
import subprocess
from pathlib import Path

COMPILE_SHA = '45e9e0536cfa61f5f8620abd718103d28d620a70b0e2f631348b9e8247673b54'


def minifier_source(original):
    if hashlib.sha256(original.encode()).hexdigest() != COMPILE_SHA:
        raise ValueError('Pinned Makepad JS transform source hash drift')
    start = original.index('fn minify_js(input: &str) -> String {')
    end = original.index('pub fn cp_brotli(', start)
    return original[start:end] + r'''
fn main() {
    use std::io::{Read, Write};
    let mut source = String::new();
    std::io::stdin().read_to_string(&mut source).unwrap();
    std::io::stdout().write_all(minify_js(&source).as_bytes()).unwrap();
}
'''


def minify(binary, data):
    return subprocess.run([str(binary)], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True).stdout


def check_real_js(binary, source, scratch):
    """Check all actual transformed bootstrap modules before the heavy app build."""
    records = {}
    files = [('libs/wasm_bridge/src/wasm_bridge.js', b'')]
    files += [('platform/src/os/web/' + name, b"import init from '../bindgen.js';\n" if name == 'web_worker.js' else b'')
              for name in ['audio_worklet.js', 'web_gl.js', 'web_worker.js', 'web.js', 'auto_reload.js']]
    for index, (relative, prefix) in enumerate(files):
        raw = prefix + (source / relative).read_bytes()
        transformed = minify(binary, raw)
        if not transformed or transformed == raw:
            raise ValueError('Expected real Makepad JS transformation: ' + relative)
        module = scratch / f'makepad-transform-{index}.mjs'
        try:
            module.write_bytes(transformed)
            subprocess.run(['node', '--check', str(module)], check=True)
        finally:
            module.unlink(missing_ok=True)
        records[relative] = {'sourceSha256': hashlib.sha256(raw).hexdigest(),
                             'minifiedSha256': hashlib.sha256(transformed).hexdigest()}
    return records


def check_resource_contract(binary, source):
    """Byte-validation integration fixture only; never an application artifact."""
    import tempfile
    import shutil
    from package_resources import validate_pinned_resources, SMALL_FONT_OMISSIONS
    with tempfile.TemporaryDirectory(prefix='makepad-byte-contract-') as temporary:
        package = Path(temporary)
        # These explicit placeholders exercise the resource validator only.
        for name in ['index.html', 'bindgen.js', 'robrix.wasm']:
            (package / name).write_text('resource-validation-test-placeholder')
        pairs = [('libs/wasm_bridge/src/wasm_bridge.js', 'makepad_wasm_bridge/wasm_bridge.js', b'')]
        pairs += [('platform/src/os/web/' + name, 'makepad_platform/' + name,
                   b"import init from '../bindgen.js';\n" if name == 'web_worker.js' else b'')
                  for name in ['audio_worklet.js', 'web_gl.js', 'web_worker.js', 'web.js', 'auto_reload.js', 'full_canvas.css']]
        for original, target, prefix in pairs:
            path = package / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(prefix + (source / original).read_bytes())
        for crate, directory in [('makepad_widgets', 'widgets'), ('makepad_platform', 'platform'), ('makepad_wasm_bridge', 'libs/wasm_bridge')]:
            root = source / directory / 'resources'
            for original in root.rglob('*'):
                if original.is_file() and original.name not in SMALL_FONT_OMISSIONS:
                    target = package / crate / 'resources' / original.relative_to(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, target)
        raw = validate_pinned_resources(package, source, source, binary)
        for original, target, prefix in pairs:
            if target.endswith('.js'):
                (package / target).write_bytes(minify(binary, prefix + (source / original).read_bytes()))
        transformed = validate_pinned_resources(package, source, source, binary)
        damaged = package / 'makepad_platform/web_gl.js'
        damaged.write_bytes(damaged.read_bytes() + b'\n/*unexpected drift*/')
        try:
            validate_pinned_resources(package, source, source, binary)
        except ValueError as error:
            if 'web_gl.js' not in str(error):
                raise
        else:
            raise AssertionError('Unrecognized JS bytes were accepted')
        return {'rawResourceCount': len(raw['verifiedResources']),
                'transformedResourceCount': len(transformed['verifiedResources']),
                'unknownBytesRejected': True, 'applicationExecution': False}
