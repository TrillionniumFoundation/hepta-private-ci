# Restore the study002 figures

From the repository root, run this command to open any original SVG or PNG
named by either figure manifest at its recorded path.

```sh
study=experiments/continuous_spiking_followup/results/study002
python3 "$study/analysis/restore_audit_archives.py" \
  --study-root "$study" --manifest "$study/analysis/audit_archives/MANIFEST_002.json"
```

The second archive manifest includes all sixteen paths in the first manifest
and ten additional SVGs. The existing reader checks every original SHA-256
and creates missing files. Use `--verify-only` to check the archive without
writing outputs. A second restore skips files with identical bytes.

The report's two embedded SVGs and its PNG are directly viewable after
checkout. The restored figure paths support vector display and verification
against `analysis/figures/FIGURE_MANIFEST.json` and
`analysis/figures_v2/FIGURE_MANIFEST.json`.
