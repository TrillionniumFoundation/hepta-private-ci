"""Import only the externally pinned, already-restored P39 development archive."""
import argparse
import json
from pathlib import Path
import shutil

from experiment import digest, save

parser = argparse.ArgumentParser()
parser.add_argument('restored', type=Path)
parser.add_argument('archive_manifest', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
expected = '2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e'
if digest(args.archive_manifest) != expected:
    raise ValueError('Unpinned archive manifest')
archive = json.loads(args.archive_manifest.read_text())
for name, record in archive['members'].items():
    if digest(args.restored / name) != record['sha256']:
        raise ValueError('Restored member mismatch: '+name)
bank = json.loads((args.restored/'bank/manifest.json').read_text())
cohort = json.loads((args.restored/'cohorts/manifest.json').read_text())
images = {r['image_id']: r for r in cohort['source_sample']['images']}
ids = bank['image_ids']
lookup = {key: i for i, key in enumerate(ids)}
rows = []
for image_id in ids:
    image = images[image_id]
    if image['license']['id'] not in (4, 5):
        raise ValueError('Unexpected historical license')
    rows.append(dict(id=str(image_id), source_id=image['flickr_url'], page_id=str(image_id),
                     image_sha256=image['image_sha256'], source_license=image['license']))
examples = []
for old, new in [('train', 'train'), ('dev', 'temperature'), ('calibration', 'calibration'), ('test', 'test')]:
    for line in (args.restored/f'cohorts/{old}.jsonl').read_text().splitlines():
        item = json.loads(line)
        examples.append(dict(image=lookup[item['image_id']], text=lookup[item['source_caption_image_id']],
             y=item['label'], kind='historical_pair' if item['label'] else 'historical_crossed',
             split=new, block=item['pair_block_id'], original_row_id=item['row_id']))
args.output.mkdir(parents=True, exist_ok=False)
shutil.copyfile(args.restored/'bank/features.npz', args.output/'features.npz')
save(args.output/'manifest.json', dict(kind='historical_P39_development_only', rows=rows,
     historical_examples=examples, original_archive_sha256=expected,
     checkpoint_revision=bank['base_identity']['checkpoint_revision'],
     image_only_contains_fixed_neutral_text=bank['image_only_contains_fixed_neutral_text'],
     notes='Previously seen COCO pairing data; no fresh holdout, no original encoding replay, no CLIP claim'))
