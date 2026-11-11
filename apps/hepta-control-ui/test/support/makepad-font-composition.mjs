// Source-integrity checks only. Runtime font semantics remain in the original probes.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const fontPaths = ['src/text/fonts.rs', 'src/shader/draw_text.rs', 'src/text/rasterizer.rs'];
const consumerPaths = [
  'makepad-draw/src/shader/draw_text.rs',
  'makepad-draw/src/text/font.rs',
  'makepad-draw/src/text/loader.rs',
  'makepad-platform/src/hepta_font_consumer.rs',
  'makepad-platform/src/lib.rs',
  'makepad-platform/src/script/res.rs',
  'makepad-platform/src/os/web/web_network.rs',
];
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const validDigest = value => assert.match(value, /^[a-f0-9]{64}$/);

export async function readComposedMakepadFontSources({
  revision, fontIdentity, fontPatch, consumerIdentity, consumerPatch, readSource,
}) {
  for (const [identity, patch] of [[fontIdentity, fontPatch], [consumerIdentity, consumerPatch]]) {
    assert.equal(identity.upstream, revision, 'Wrong pinned Makepad revision');
    assert.equal(digest(patch), identity.patchSha256, 'Wrong overlay patch bytes');
  }
  assert.deepEqual(fontIdentity.files.map(file => file.path), fontPaths);
  assert.deepEqual(consumerIdentity.files.map(file => file.path), consumerPaths);
  const expected = new Map();
  for (const file of fontIdentity.files) {
    validDigest(file.beforeSha256);
    validDigest(file.afterSha256);
    expected.set(`makepad-draw/${file.path}`, file.afterSha256);
  }
  for (const file of consumerIdentity.files) {
    validDigest(file.afterSha256);
    if (file.path === 'makepad-platform/src/hepta_font_consumer.rs') {
      assert.equal(file.beforeSha256, null, 'Consumer recorder must be a new file');
    } else {
      validDigest(file.beforeSha256);
    }
    if (expected.has(file.path)) {
      assert.equal(file.beforeSha256, expected.get(file.path), 'Wrong ordered overlay preimage');
    }
    expected.set(file.path, file.afterSha256);
  }
  const sources = new Map();
  for (const [path, expectedDigest] of expected) {
    const bytes = await readSource(path);
    assert.equal(digest(bytes), expectedDigest, `Wrong composed source: ${path}`);
    sources.set(path, bytes.toString('utf8'));
  }
  return new Map(fontPaths.map(path => [path, sources.get(`makepad-draw/${path}`)]));
}
