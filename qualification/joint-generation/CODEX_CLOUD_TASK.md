# Execute the first joint-generation prototype goal in Codex Cloud

Repository: `TrillionniumFoundation/hepta-private-ci`.
Use its existing configured Codex Cloud environment. Do not substitute a ChatGPT
scratch runtime, a LAN production host, or GitHub Actions for the requested run.

Start from `codex/joint-generation-prototype-20261023`; inspect the actual commit
and repository instructions. This branch contains three reviewable source stages:
tensor/recursive-utility kernel; controlled task/training/controller; executable
evaluation/serving/runner. No production service or authority is activated.

1. Read `qualification/joint-generation/README.md` and `plan.json`. Check installed
   Python/dependencies and record the actual Codex task/environment identity.
2. In that directory install `requirements.txt` if needed, then run
   `python cloud_run.py --out runs/codex-cloud-20261023-r1`.
3. Inspect unit logs and the complete retained training/selection/test receipts.
   A test-result failure is a real failure, even if compilation and training pass.
4. Demonstrate serving from an exported bundle using an external normalized RGB
   input and instruction, plus a sampled output, cost record and checkpoint.
   Verify model/bundle reload, cancellation, output append-only behavior and hard
   budgets using the affected tests. Never use target labels at deployment.
5. Resolve actual source/runtime failures with targeted tests and retained evidence.
   If a code bug invalidates an experiment, retain its receipt and state why it is
   invalid. Do not tune a model or acceptance threshold against held-out results.
6. Persist exact source commit, environment, commands, all seed results, selected
   bundles, source/data hashes, costs, decoder negative control and confidence
   intervals to the branch. Keep generated arrays and logs bounded. Update README
   status from real receipts only, and keep failures visible.

Completion requires actual trainable parameter updates, joint decoded-output
benefit under the predeclared matched budget, and dynamic control benefit over
matched-compute random routing. If a statistical gate fails, report it and keep
that blocker open. This is finite-scene evidence, not a full multimodal foundation
model or a generic NDU theorem. Only after first-goal evidence supports it should
synchronous audio/video and longer interactions be proposed and separately tested.
