"""Runs only generic slope-reference tests; HX backend is not in this bundle."""
from .matched_slope_cases import GenericLocalSlopeTests
import unittest

def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(GenericLocalSlopeTests)
