"""Import the existing frozen SmallHCSN implementation from verified source bytes."""
import importlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

from profile_io import canonical, digest, fields, parse, read_pin, read_relative, require, sha

CAPSULE_SHA256 = "7ebe8aed55ce2e209f8be5dd016b4b13a8bb3fe6243b918d9648dd9a7114fe96"
PROVENANCE_SHA256 = "72194249d27b8af51cf95f89f5db494fa525e44c156eaf11b56e417ccc8c3b55"
SCIENTIFIC_SHA256 = {
    "common.py": "b14f1d47e3a8635aa781b5b983e84eca7634f9d1e26cbf7674fb697645d7759a",
    "optimized.py": "c481cc23fe3953bcbb6a5e82dff28344d7cb4c0c4703cb74d14500b5b33c60d3",
}
RUNTIME = {"python": "3.14.4", "numpy": "2.5.5", "torch": "2.15.0+cpu",
           "device": "cpu", "threads": 1, "interop_threads": 1}


class FrozenSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """No bytecode cache or unpinned qualification module supplies physical code."""
    def __init__(self, root, manifest):
        self.root = Path(root).absolute()
        capsule = manifest["capsule"]
        fields(capsule, ("root", "archive_sha256", "provenance"), "capsule")
        require(capsule["archive_sha256"] == CAPSULE_SHA256, "unsupported physical capsule")
        require(capsule["provenance"]["path"] == capsule["root"] + "/source_provenance.json",
                "capsule provenance path differs")
        raw = read_pin(root, capsule["provenance"], 1024 * 1024)
        require(sha(raw) == PROVENANCE_SHA256, "unsupported physical provenance")
        provenance = parse(raw)
        physical = provenance["research_source_hashes"]
        require(isinstance(physical, dict) and 1 <= len(physical) <= 64, "physical source roster")
        self.sources = {}
        for name, expected in physical.items():
            path = capsule["root"] + "/src/" + name
            raw = read_relative(root, path, 1024 * 1024)
            require(sha(raw) == digest(expected), "frozen physical source differs")
            self._add(name, path, raw)
        supplied = manifest["scientific_sources"]
        fields(supplied, SCIENTIFIC_SHA256, "scientific sources")
        for name, expected in SCIENTIFIC_SHA256.items():
            raw = read_pin(root, supplied[name], 1024 * 1024)
            require(sha(raw) == expected, "frozen scientific source differs")
            self._add(name, supplied[name]["path"], raw)
        self.identity = sha(canonical({"physical_provenance": PROVENANCE_SHA256,
                                       "physical": physical, "scientific": SCIENTIFIC_SHA256}))
        self.capsule = self.root / capsule["root"]

    def _add(self, name, path, raw):
        require(name.endswith(".py"), "source must be Python")
        package = name.endswith("/__init__.py")
        module = name[:-12].replace("/", ".") if package else name[:-3].replace("/", ".")
        require(module not in self.sources, "duplicate module identity")
        self.sources[module] = (str(self.root / path), raw, package)

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.sources:
            return importlib.util.spec_from_loader(fullname, self,
                                                   is_package=self.sources[fullname][2])
        if fullname == "qualification" or fullname.startswith("qualification."):
            raise ImportError("physical import outside frozen source roster")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, raw, package = self.sources[module.__name__]
        module.__file__ = path
        module.__frozen_source_sha256__ = sha(raw)
        if package:
            module.__path__ = [str(Path(path).parent)]
        exec(compile(raw, path, "exec"), module.__dict__)

    def load(self):
        for name, module in tuple(sys.modules.items()):
            if name in self.sources or name == "qualification" or name.startswith("qualification."):
                require(name in self.sources, "foreign physical module already loaded")
                path, raw, _ = self.sources[name]
                require(getattr(module, "__frozen_source_sha256__", None) == sha(raw)
                        and getattr(module, "__file__", None) == path,
                        "fresh process or identical verified source binding required")
        previous = os.environ.get("PFT_HCSN_CAPSULE")
        os.environ["PFT_HCSN_CAPSULE"] = str(self.capsule)
        sys.meta_path.insert(0, self)
        try:
            common = importlib.import_module("common")
            optimized = importlib.import_module("optimized")
            physical = importlib.import_module("qualification.hcsn_smallnet_20261124.model")
        finally:
            sys.meta_path.remove(self)
            if previous is None:
                os.environ.pop("PFT_HCSN_CAPSULE", None)
            else:
                os.environ["PFT_HCSN_CAPSULE"] = previous
        actual = common.runtime()
        require({key: actual[key] for key in RUNTIME} == RUNTIME, "frozen numerical runtime differs")
        return common, optimized, physical
