# Explicit hosted regression coverage correction

The first isolated r12 head, 8e6eaa218383997f872385184a1f6a2b9db96b12, had hosted HCSN CPU fixture SUCCESS (run 43089154413, job 130761322738, artifact 13887788230). A direct read of its raw job log showed that it ran the previously declared recovery, successor-wiring, source closure, program manifest and execution decision test patterns, but did NOT run the newly added test_controller_strict_terminal_json.py.

Therefore this first exact-head hosted CI result does NOT establish the new seven tests passed in hosted Python 3.12.3. Local native GREEN 39/39 remains true but has a different Python patch release. This follow-up adds the explicit discovery command in the existing c2-recovery step of .github/workflows/hcsn-differentiable.yml, retaining stdout in c2-controller-strict-terminal-json-tests.log and the workflow artifact. The newly resulting head requires its own fresh hosted CI and artifact check. Historical CI/RED/failed preflight are not overwritten.

Full science P0–P5 remains HOLD_NO_GO; this is a controller JSON integrity regression, not six-fit C2 replay or benefit.
