"""Execute authenticated original Python source without reading timestamp-based pyc."""
import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys

from stage_contract import require


class PinnedSourceLoader(importlib.abc.Loader):
    """Only the exact frozen UTF-8/source bytes may define a delegated module."""

    def __init__(self, identity):
        self.identity = identity

    def create_module(self, specification):
        return None

    def exec_module(self, module):
        item = self.identity
        raw = Path(item['path']).read_bytes()
        require(len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'],
                'original module source changed: ' + item['path'])
        module.__file__, module.__cached__ = item['path'], None
        exec(compile(raw, item['path'], 'exec'), module.__dict__)


class PinnedSourceFinder(importlib.abc.MetaPathFinder):
    """Route only this experiment's original modules to their source pins."""

    def __init__(self, original_pins):
        self.pins = {Path(name).stem: identity for name, identity in original_pins.items()
                     if name.endswith('.py')}

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.pins:
            return None
        item = self.pins[fullname]
        return importlib.util.spec_from_loader(fullname, PinnedSourceLoader(item), origin=item['path'])


def load_original(original_pins):
    finder = PinnedSourceFinder(original_pins)
    require(not set(finder.pins).intersection(sys.modules), 'original modules must not be preloaded')
    sys.meta_path.insert(0, finder)
    name = 'hepta_frozen_value_reader'
    require(name not in sys.modules, 'original reader may load only once')
    identity = original_pins['verify_records.py']
    loader = PinnedSourceLoader(identity)
    specification = importlib.util.spec_from_loader(name, loader, origin=identity['path'])
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    loader.exec_module(module)
    return module
