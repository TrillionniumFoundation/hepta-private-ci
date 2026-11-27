#!/usr/bin/env python3
"""Complete fixed original crate versus actual admitted owner; 3,974 inputs per policy."""
import sys
sys.dont_write_bytecode = True

import traceback

from unified_diff_oracle.common import Context, arguments, create
from unified_diff_oracle.public import verify


def main():
    args = arguments(__doc__, public=True)
    context = None
    try:
        context = Context(args, "codex.hia.unified-diff-canonical-public.v2")
        verify(context)
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
