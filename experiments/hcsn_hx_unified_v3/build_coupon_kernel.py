"""Explicit local build; never imported by HX pricing or ordinary tests.

Run from the repository root with a Cython-equipped research environment:
CC=gcc LDSHARED='gcc -shared' python experiments/hcsn_hx_unified_v3/build_coupon_kernel.py build_ext --inplace
"""
from pathlib import Path
import os
from setuptools import Extension,setup
from Cython.Build import cythonize

if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]
    os.chdir(root)
    setup(name='hcsn-coupon-research-local',ext_modules=cythonize([
        Extension('experiments.hcsn_hx_unified_v3._coupon_kernel',
                  ['experiments/hcsn_hx_unified_v3/_coupon_kernel.pyx'],
                  extra_compile_args=['-O2','-fno-fast-math','-ffp-contract=off'],
                  extra_link_args=['-fno-fast-math','-ffp-contract=off'])
    ],compiler_directives={'language_level':3}))
