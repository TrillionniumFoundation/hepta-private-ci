"""Reuse original archived source custody, but issue a G6 full-evidence label-free source packet.

The model Worker is given only four verified MiniLM files plus the sealed TRAIN
support/HELD unlabelled source packet. Original gold belongs to a separate
postseal reviewer process. No Github token is forwarded to the signed redirect.
"""
from __future__ import annotations

from pathlib import Path
import argparse

from g5_material_custody import download_original, extract_pinned
from g6_coverage_source import build, write_new
from g5_batched_encoder import verified_encoder_only


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--mode', choices=('source_owner','reviewer'), required=True)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--source', type=Path)
    args=p.parse_args()
    if args.mode=='source_owner' and args.source is None:
        raise ValueError('source owner must supply an independent public packet path')
    download_original(args.archive)
    extract_pinned(args.archive,args.root,mode=args.mode)
    if args.mode=='source_owner':
        verified_encoder_only(args.root)
        original=args.root/'locomo.json'
        packet=build(original.read_bytes())
        write_new(args.source,packet)
        original.unlink()
        assert not original.exists()
        print('G6 source-first packet sealed, only original TRAIN evidence retained; HELD gold excluded')
    else:
        assert (args.root/'locomo.json').is_file()
        print('G6 independent reviewer obtained original publisher SHA-pinned source for postseal review')

if __name__=='__main__':
    main()
