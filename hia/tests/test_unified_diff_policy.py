#!/usr/bin/env python3
"""Build both admitted owner policies and execute the eight real rejection commands."""
import sys
sys.dont_write_bytecode = True

import json
from pathlib import Path
import traceback

from unified_diff_oracle.common import Context, arguments, bind, create
from unified_diff_oracle.policies import build, negatives, profiles


def main():
    args = arguments(__doc__)
    context = None
    try:
        context = Context(args, "codex.hia.unified-diff-canonical-policy.v1")
        context.report["profiles"] = {name: bind(path) for name, path in profiles(context).items()}
        checked = build(context, 0)
        context.report["policies"] = {"0": checked}
        wrapping = build(context, 1)
        context.report["policies"]["1"] = wrapping
        context.report["negatives"] = negatives(context, checked, wrapping)
        for phase in (checked, wrapping):
            for dependency in phase["actual_owner_extern_inputs"].values():
                for field in ("selected", "link_library"):
                    assert bind(dependency[field]["path"]) == dependency[field]
            receipt = json.loads(Path(phase["actual_owner_receipt"]["path"]).read_bytes())
            for item in receipt["artifacts"]:
                actual, verified = context.helper.select_receipt(context.helper_cfg, item["path"], "consumer")
                assert actual == item and verified["policy_mode"] == phase["mode"]
        context.report["public_semantics_executed_by_this_gate"] = False
        return context.finish()
    except Exception:
        failure = traceback.format_exc()
        if context is not None:
            return context.finish(failure)
        if not args.report.exists():
            args.report.parent.mkdir(parents=True, exist_ok=True)
            create(args.report, {"passed": False, "exception": failure, "phase": "admission"})
        print(failure, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
