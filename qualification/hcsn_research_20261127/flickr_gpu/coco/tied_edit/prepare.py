"""Prepare the registered cross-source caption and image splits."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(os.environ.get('HEPTA_FLICKR_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / 'prepare_packages'))
import numpy as np
from PIL import Image, ImageOps


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dhash(image):
    small = np.asarray(image.convert('L').resize((9, 8), Image.Resampling.BILINEAR))
    return np.packbits((small[:, 1:] > small[:, :-1]).ravel())


def main():
    base = ROOT / 'tied_edit' / 'data'
    base.mkdir(exist_ok=True, parents=True)
    manifest = json.loads((ROOT / 'data' / 'manifest.json').read_text())
    receipt = json.loads((ROOT / 'coco_source_receipt.json').read_text())
    roster = json.loads((ROOT / 'coco_restored' / 'selected.json').read_text())
    assert sha(ROOT / 'data' / 'manifest.json') == 'ba7083f60f12be990ede3f9a60f04524aa81228989bf6384f1684f225c26dd1e'
    assert (ROOT/'coco_restored/verification.json').is_file()
    upstream = {key: value for key, value, _ in receipt['jpeg']}
    vocab = {w: i for i, w in enumerate(manifest['vocab'])}
    assert len(vocab) == 3490
    exact, fingerprint = set(), []
    for split, record in manifest['splits'].items():
        for field in ('pixels', 'ids'):
            filename = f'{split}_{field}.npy'
            assert sha(ROOT / 'data' / filename) == record['files'][filename]
        pixels = np.load(ROOT / 'data' / f'{split}_pixels.npy', mmap_mode='r')
        ids = np.load(ROOT / 'data' / f'{split}_ids.npy')
        exact.update(v.decode() for v in ids)
        fingerprint.extend(dhash(Image.fromarray(px)) for px in pixels)
    assert len(exact) == len(fingerprint) == 7999
    pop = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None], axis=1).sum(1).astype(np.uint8)
    output = {'source': sha(ROOT / 'coco_source_receipt.json'), 'flickr_manifest': sha(ROOT/'data/manifest.json'), 'splits': {}}
    for split, count in [('train', 1024), ('val', 192), ('test', 384)]:
        rows = roster[split]
        assert len(rows) == count
        assert hashlib.sha256('\n'.join(r['file'] for r in rows).encode()).hexdigest() == receipt['ordered_splits'][split]
        prev = np.stack(fingerprint)
        pixels, captions, identities, choice, dropped, later = [], [], [], [], [], []
        ncap = ntrunc = nunc = nlex = 0
        for row in rows:
            path = ROOT / 'coco_restored' / 'images' / row['file']
            ident = sha(path)
            assert ident == upstream[path.name]
            with Image.open(path) as image:
                cropped = ImageOps.fit(image.convert('RGB'), (64, 64), method=Image.Resampling.BILINEAR)
                code = dhash(cropped)
                px = np.asarray(cropped).copy()
            dist = int(pop[np.bitwise_xor(prev, code)].sum(1).min())
            later.append((ident, code))
            if ident in exact or dist <= 2:
                dropped.append({'file': path.name, 'sha256': ident, 'exact': ident in exact, 'nearest_distance': dist})
                continue
            all_captions = row['captions']
            subset = [int(ident[:8], 16) % len(all_captions)] if split == 'train' else list(range(5))
            if split != 'train':
                assert len(all_captions) == 5
            tokens = np.zeros((len(subset), 32), dtype=np.int16)
            for j, idx in enumerate(subset):
                words = re.findall(r"[a-z]+(?:'[a-z]+)?|[0-9]+|[^\w\s]", all_captions[idx].lower())
                ntrunc += int(len(words) > 30)
                ids = [vocab.get(w, 3) for w in words[:30]]
                nunc += ids.count(3)
                nlex += len(ids)
                seq = [1] + ids + [2]
                tokens[j, :len(seq)] = seq
            ncap += len(subset)
            choice.append(subset)
            identities.append(ident)
            pixels.append(px)
            captions.append(tokens)
        exact.update(x[0] for x in later)
        fingerprint.extend(x[1] for x in later)
        dest = base / f'{split}.npz'
        with dest.with_suffix('.part').open('wb') as stream:
            np.savez_compressed(stream, images=np.stack(pixels), tokens=np.stack(captions), ids=np.asarray(identities, dtype='S64'), caption_index=np.asarray(choice, dtype=np.int16))
        dest.with_suffix('.part').replace(dest)
        output['splits'][split] = dict(input_images=count, images=len(pixels), captions=ncap, lexical=nlex, unknown=nunc, truncated=ntrunc, excludes=dropped, sha256=sha(dest))
    temp = base/'manifest.part'
    temp.write_text(json.dumps(output, indent=2, sort_keys=True))
    temp.replace(base/'manifest.json')


if __name__ == '__main__':
    main()
