#!/usr/bin/env python3
"""Compatibility shim for the superseded first-generation Agentd recovery transform.

The promotion workflow applies ``apply_context_compiler_agentd_recovery_v2.py`` as the
single transform for the authority/preparation-bound durable recovery schema. Keeping
this shim temporarily makes historical workflow references harmless; the promotion
commit removes both migration scripts after direct source has been materialized.
"""

from __future__ import annotations


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
