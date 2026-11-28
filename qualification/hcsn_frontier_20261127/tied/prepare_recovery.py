"""Reconstruct only the two deduplicated annotation lists from the original five IDs."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path('/tmp/hepta-hcsn-flickr8k-c511-9c415')
BASE = ROOT / 'tied_edit'
SOURCE = Path.home() / '.local/share/hepta-research/hcsn-attention-free-recovery-e0bf/source_provenance/original_two_annotation_rows.json'
ORIGINAL = BASE / 'src/prepare.py'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    assert digest(ORIGINAL) == 'f5b1caf535a0fa51ea80d0a49b18b0d351f5420f3c3d386d618a7dfe6e6f5c06'
    assert digest(SOURCE) == '59fa751256d0b1b673a78aee1c38576215fa2e182337390c1ef421309194d037'
    authority = json.loads(SOURCE.read_text())
    rows = {row['filename']:row for row in authority['images']}
    observed = {}
    assert len(rows) == 2
    def original_captions(row, split, image_sha):
        archive = rows.get(row['file'])
        if archive is None:
            return row['captions']
        assert archive['split'] == split
        captions = [s['raw'] for s in archive['sentences']]
        assert list(archive['sentids']) == [s['sentid'] for s in archive['sentences']]
        assert len(captions) == len(set(archive['sentids'])) == 5
        assert len(row['captions']) == 4 and list(dict.fromkeys(captions)) == row['captions']
        old_index = int(image_sha[:8], 16) % 4 if split == 'train' else None
        new_index = int(image_sha[:8], 16) % 5 if split == 'train' else None
        observed[row['file']] = dict(split=split, jpeg_sha256=image_sha, annotation_ids=archive['sentids'],
                                    from_unique_text=4, to_distinct_annotations=5,
                                    source_support_index=new_index, deduplicated_support_index=old_index,
                                    support_text_changes=(captions[new_index] != row['captions'][old_index]) if split == 'train' else None)
        return captions
    src = ORIGINAL.read_text()
    old = "all_captions = row['captions']"
    assert src.count(old) == 1
    effective = src.replace(old, 'all_captions = original_captions(row, split, ident)')
    evidence = dict(annotation_archive_sha256=authority['archive_sha256'], annotation_member_sha256=authority['member_sha256'],
                    extracted_rows_sha256=digest(SOURCE), original_preparer_sha256=digest(ORIGINAL),
                    effective_preparer_sha256=hashlib.sha256(effective.encode()).hexdigest(),
                    adapter_sha256=digest(Path(__file__)), original_roster_sha256=digest(ROOT/'coco_restored/selected.json'))
    os.environ['HEPTA_FLICKR_ROOT'] = str(ROOT)
    assert not (BASE/'results/seal.json').exists()
    space = dict(__name__='recovered_preparer', __file__=str(ORIGINAL), original_captions=original_captions)
    exec(compile(effective, str(ORIGINAL), 'exec'), space)
    space['main']()
    assert set(observed) == set(rows)
    evidence.update(reconstructed=observed, manifest_sha256=digest(BASE/'data/manifest.json'))
    target = BASE/'annotation_repair_e0bf.json'
    tmp = target.with_suffix('.part')
    tmp.write_text(json.dumps(evidence,sort_keys=True,indent=2)+'\n')
    tmp.replace(target)
    print(json.dumps(evidence,sort_keys=True),flush=True)

if __name__ == '__main__':
    main()
