cd "$hepta_final_parent/research"
hepta_python=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python
"$hepta_python" -B -m experiments.analytic_event_neuron.round6.lifecycle verify \
  --run-dir experiments/analytic_event_neuron/round6/evidence/registered_001 \
  --expected-freeze-sha256 1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1
