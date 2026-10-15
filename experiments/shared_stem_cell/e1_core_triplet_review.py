#!/usr/bin/env python3
"""Independent read-only core-triad CPU score from three original model reports.

Old EmbeddingGemma reports may never masquerade as ModernBERT. English AG News
is retrospective. No signed deployed no-change, future NDU or Stem winner.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from e1_public_triplet_real_cpu import load_panel
from e1_public_triplet_review import CORE_MODELS, Invalid, evaluate, read

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    for name in CORE_MODELS:
        parser.add_argument("--"+name.replace("_","-"),type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    panel,source=load_panel(args.panel)
    if source!="2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4":
        raise Invalid("unexpected original frozen AG News public panel")
    reports={name:read(getattr(args,name)) for name in CORE_MODELS}
    result=evaluate(panel,reports,core=True)
    if (result["registered_core_triad"] is not True or
            set(result["scores"])!=set(CORE_MODELS) or
            result["stem_winner_selected"] is not False or
            result["production_promotion_permitted"] is not False):
        raise Invalid("three real research controls not preserved")
    with args.output.open("x",encoding="utf8") as out:
        json.dump(result,out,sort_keys=True,indent=2,allow_nan=False)
        out.write("\n")

if __name__=="__main__":
    main()
