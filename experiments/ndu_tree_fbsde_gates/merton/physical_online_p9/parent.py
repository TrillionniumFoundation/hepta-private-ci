"""P9 read-only exact checkout imports: P8 model and P5 source, no rewrites."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path


def load_p8(name:str):
    if name not in ('online','source','review'):
        raise ValueError('unregistered original P8 owner module')
    location=Path(__file__).resolve().parents[1]/'physical_online_p8'/f'{name}.py'
    if not location.is_file():
        raise ValueError('required exact upstream P8 original source unavailable')
    root=str(location.parent)
    if root not in sys.path:sys.path.insert(0,root)
    tag=f'hepta_p8_original_{name}'
    if tag in sys.modules:return sys.modules[tag]
    spec=importlib.util.spec_from_file_location(tag,location)
    if spec is None or spec.loader is None:raise ValueError('original parent import unavailable')
    module=importlib.util.module_from_spec(spec)
    sys.modules[tag]=module
    try:spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[tag]
        raise
    return module
