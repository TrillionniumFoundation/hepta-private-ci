"""Original GitHub archival source-owner and separate postseal gold custody.

Requires exact SHA-pinned download and validated extraction. No GitHub bearer
credential may reach the signed external redirect origin. The source-owner
removes raw human QA before uploading any model-execution artifact.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import json
from g5_material_custody import download_original, extract_pinned
from g5_batched_encoder import verified_encoder_only
from g6_coverage_source import write_new
from g8_source import build


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=('source_owner','reviewer'),required=True)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--source',type=Path)
    a=p.parse_args()
    if a.mode=='source_owner' and a.source is None:
        raise ValueError('source-owner must bind the full-corpus packet destination')
    download_original(a.archive)
    extract_pinned(a.archive,a.root,mode=a.mode)
    if a.mode=='source_owner':
        verified_encoder_only(a.root)
        source_file=a.root/'locomo.json'
        value=build(source_file.read_bytes())
        write_new(a.source,value)
        source_file.unlink()
        if source_file.exists() or (a.root/'reader').exists():
            raise RuntimeError('unsafe raw publisher content remains in model-only directory')
        print(json.dumps({'source_digest':value['digest'],'train_roots':6,
              'held_gold_exported':False,'disposition':'HOLD_NO_GO'},sort_keys=True))
    else:
        if not (a.root/'locomo.json').is_file():
            raise RuntimeError('independent original gold material is unavailable')
        print('original human-label owner ready only after sealed model predictions')

if __name__=='__main__':main()
