"""Load only the published, checksum-pinned MMSA arrays and literal CMU folds."""
import ast
import hashlib
import pickle
from pathlib import Path
import numpy as np

MMSA_SHA='d3994fd25681f9c7ad6e9c6596a6fe9b4beb85ff7d478ba978b124139002e5f9'
SDK_COMMIT='4f2eadcd7e7b9e20e83b868cdad385b41830285c'


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as fp:
        for b in iter(lambda:fp.read(2**20),b''):h.update(b)
    return h.hexdigest()


class NumpyArrays(pickle.Unpickler):
    def find_class(self,module,name):
        if module in ('numpy.core.multiarray','numpy._core.multiarray') and name in ('_reconstruct','scalar'):return getattr(np._core.multiarray,name)
        if module=='numpy' and name in ('ndarray','dtype'):return getattr(np,name)
        if module in ('numpy.core.numeric','numpy._core.numeric') and name=='_frombuffer':return np._core.numeric._frombuffer
        raise ValueError(f'Unexpected pickle callable {module}.{name}')


def load(p):
    if sha(p)!=MMSA_SHA:raise ValueError('MMSA feature bytes differ from published hash')
    with Path(p).open('rb') as f:return NumpyArrays(f).load()


def official(p):
    keep={}
    for n in ast.parse(Path(p).read_text()).body:
        if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name):
            key=n.targets[0].id
            if key in ('standard_train_fold','standard_valid_fold','standard_test_fold'):keep[key.split('_')[1]]=set(ast.literal_eval(n.value))
    assert set(keep)=={'train','valid','test'}
    return keep
