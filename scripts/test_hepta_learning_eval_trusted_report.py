#!/usr/bin/env python3
"""Aggregate the complete deterministic trusted-reporter regression suite."""

import unittest

from test_hepta_learning_eval_local_verify import *  # noqa: F403
from test_hepta_learning_eval_trusted_entry import *  # noqa: F403
from test_hepta_learning_eval_trusted_report_base import *  # noqa: F403


if __name__ == "__main__":
    unittest.main()
