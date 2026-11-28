"""Open the sealed native task and its immutable quote cache without training."""
import hashlib
from pathlib import Path
import sys
from textwrap import dedent


def inputs():
    here=Path(__file__).resolve().parent
    raw=(here/'native.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='36528d227c32d35acbda64a22812061c8050f3a64fb88fc16faf4447163a284a'
    src=raw.decode()
    env={'__name__':'study_payload'}
    loader=src.split('\nrun(work,Path.cwd())\n')
    assert len(loader)==2 and not loader[1].strip()
    exec(compile(loader[0],'<sealed-native>','exec'),env)
    sys.path.insert(0,str(env['work']/'hcsn_recurrent_boundary_20261128'/'trimodal_decoder'))
    start=src.index('    import types, io, base64')
    end=src.index("    report['precomputed_contract_tables']",start)
    exec(compile(dedent(src[start:end]),'<sealed-cache>','exec'),env)
    from data import streams
    return streams()
