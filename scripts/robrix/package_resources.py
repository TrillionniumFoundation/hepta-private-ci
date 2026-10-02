"""Validate actual Makepad package resources; never fabricate runtime assets."""
import hashlib
import re
from urllib.parse import urlsplit, unquote
from pathlib import Path

UTILS_SHA256 = '533d4fe7dfcddcda0d735f1a39d0c6446327607a4dedf4ee7e165d6f79e7e555'
CORE_ASSETS = ['makepad_wasm_bridge/wasm_bridge.js', 'makepad_platform/web_gl.js',
               'makepad_platform/web.js', 'makepad_platform/full_canvas.css',
               'makepad_platform/audio_worklet.js', 'makepad_platform/web_worker.js']
SMALL_FONT_OMISSIONS = {'GoNotoKurrent-Bold.ttf', 'GoNotoKurrent-Regular.ttf',
                        'LXGWWenKaiBold.ttf', 'LXGWWenKaiRegular.ttf', 'NotoColorEmoji.ttf'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def patch_packager(source):
    if sha(source.encode()) != UTILS_SHA256:
        raise ValueError('Pinned cargo-makepad dependency resolver hash drift')
    old = '''                    let dir_file = build_dir.join(format!("{}.path", name));
                    if let Ok(path) = std::fs::read_to_string(&dir_file) {
                        dependencies.insert(name, Path::new(&path).into());
                    }'''
    new = '''                    let resource_root = std::env::var("MAKEPAD_RESOURCE_ROOT")
                        .expect("exact Makepad resource root required");
                    if let Some(path) = hepta_dependency_dir(build_dir, &name, Path::new(&resource_root))
                        .expect("invalid Makepad dependency resource marker") {
                        dependencies.insert(name, path);
                    }'''
    if source.count(old) != 1:
        raise ValueError('Pinned cargo-makepad marker lookup shape drift')
    parser = 'pub fn extract_dependency_paths(line: &str) -> Option<(String, Option<PathBuf>)> {'
    if source.count(parser) != 1:
        raise ValueError('Pinned cargo-makepad dependency parser shape drift')
    source = source.replace(parser, parser + '\n    if hepta_dependency_heading(line) { return None; }')
    return source.replace(old, new) + '\n' + Path(__file__).with_name('makepad_marker.rs').read_text()


def parser_regression_source(patched):
    """Exercise the real pinned parser together with actual Cargo tree row syntax."""
    start = patched.index('pub fn extract_dependency_paths(')
    end = patched.index('pub fn get_crate_dir(', start)
    helper = Path(__file__).with_name('makepad_marker.rs').read_text()
    regression = r'''
#[test] fn actual_pinned_parser_resolves_marker_basename_and_ignores_only_headings() {
    for line in ["│   │       [build-dependencies]", "[dev-dependencies]"] {
        assert_eq!(extract_dependency_paths(line), None);
    }
    let f = Fixture::new();
    f.write(true, "source/platform");
    let (name, path) = extract_dependency_paths("│       │   ├── makepad-platform v2.0.0 (https://github.com/makepad/makepad?rev=493d23a7630f487d29912dd73f2cbb5b639b74ca#493d23a7)").unwrap();
    assert_eq!(name, "makepad-platform");
    assert_eq!(path, None);
    assert_eq!(hepta_dependency_dir(&f.build(), &name, &f.source()).unwrap(), Some(f.source().join("platform")));
    assert!(!hepta_dependency_heading("[build-dependencies]/../"));
}
'''
    prefix, closing = helper.rsplit('}', 1)
    return 'use std::path::{Path, PathBuf};\n' + patched[start:end] + prefix + regression + '}' + closing


def package_inventory(package):
    package = Path(package).resolve()
    for relative in ['index.html', 'bindgen.js', 'robrix.wasm', *CORE_ASSETS]:
        path = package / relative
        if not path.is_file() or path.stat().st_size == 0 or not path.resolve().is_relative_to(package):
            raise ValueError(f'Missing or escaping actual Makepad package asset: {relative}')
    return {str(path.relative_to(package)): sha(path.read_bytes())
            for path in sorted(package.rglob('*')) if path.is_file()}


def validate_pinned_resources(package, source, compiled_source):
    """Verify packaged bytes against both pinned tool checkout and built dependency."""
    package, source, compiled_source = map(Path, (package, source, compiled_source))
    expected = {'makepad_wasm_bridge/wasm_bridge.js': ('libs/wasm_bridge/src/wasm_bridge.js', b'')}
    for name in ['audio_worklet.js', 'web_gl.js', 'web_worker.js', 'web.js', 'auto_reload.js', 'full_canvas.css']:
        expected['makepad_platform/' + name] = ('platform/src/os/web/' + name,
                                              b"import init from '../bindgen.js';\n" if name == 'web_worker.js' else b'')
    for crate, relative in [('makepad_widgets', 'widgets'), ('makepad_platform', 'platform'), ('makepad_wasm_bridge', 'libs/wasm_bridge')]:
        root = source / relative / 'resources'
        if root.is_dir():
            for path in root.rglob('*'):
                if path.is_file() and path.name not in SMALL_FONT_OMISSIONS:
                    expected[f'{crate}/resources/{path.relative_to(root)}'] = (str(path.relative_to(source)), b'')
    for destination, (relative, prefix) in expected.items():
        original = (source / relative).read_bytes()
        if (compiled_source / relative).read_bytes() != original:
            raise ValueError('Compiled Makepad resource differs from pinned source: ' + relative)
        target = package / destination
        if not target.is_file() or target.read_bytes() != prefix + original:
            raise ValueError('Packaged Makepad resource missing or changed: ' + destination)
    inventory = package_inventory(package)
    return {'verifiedResources': {name: inventory[name] for name in expected},
            'verifiedUrls': verify_relative_urls(package),
            'smallFonts': True, 'uploadsPermitted': False}


def compiled_resource_root(metadata, revision):
    expected = {'makepad-platform': 'platform', 'makepad-widgets': 'widgets',
                'makepad-wasm-bridge': 'libs/wasm_bridge'}
    directories = {}
    for name in expected:
        matches = [p for p in metadata['packages'] if p['name'] == name]
        if len(matches) != 1 or not (matches[0].get('source') or '').endswith('#' + revision):
            raise ValueError('Ambiguous or unpinned resource dependency: ' + name)
        directories[name] = Path(matches[0]['manifest_path']).resolve().parent
    root = directories['makepad-platform'].parent
    if any(directories[name] != root / relative for name, relative in expected.items()):
        raise ValueError('Makepad resource dependency paths escape the common pinned checkout')
    return root


def verify_relative_urls(package):
    package = Path(package).resolve()
    urls = {}
    for relative in ['index.html', 'bindgen.js', *CORE_ASSETS]:
        path = package / relative
        text = path.read_text()
        pattern = r'''(?:\b(?:href|src)\s*=\s*|\bfrom\s*|\bimport\s*\(\s*)["'](\.{1,2}/[^"']+)["']'''
        for url in re.findall(pattern, text):
            target = (path.parent / unquote(urlsplit(url).path)).resolve()
            if not target.is_relative_to(package) or not target.is_file():
                raise ValueError(f'Missing or escaping packaged URL: {relative} -> {url}')
            urls[f'{relative} -> {url}'] = str(target.relative_to(package))
    return urls
