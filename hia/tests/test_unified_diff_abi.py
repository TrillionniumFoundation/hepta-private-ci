#!/usr/bin/env python3
"""Qualify the canonical unified diff entry with complete original references.

Only the fixed compiler, complete locked upstream crate, actual full build.json
and unchanged final HIA/contract are admitted. Generated references and traces
must live outside source and native artifact directories. Cargo, production
policy binding, whole-owner public APIs and performance remain separate gates.
"""
import sys

sys.dont_write_bytecode = True

from unified_diff_abi.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
