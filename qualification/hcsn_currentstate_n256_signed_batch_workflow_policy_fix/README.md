# N256 signed-batch workflow policy fix

Status: **METADATA-ONLY / 0 NUMERICAL CALLS / RESOURCE HOLD / all_closed=false**.

The original #6918 head remains immutable at
`ff429657381de751718b46b27a2187cdd88080f7`.  Its original source-freeze
bytes are preserved here with SHA-256
`5f60c371cff340cc3834fd2c236d9be23c0c4a62bb272df74c66ee99b7451ebb`.

The generic contract gate rejected the original workflow because its broad
package path contained the deprecated literal `candidate/**`.  This successor
replaces that broad path with the exact eight one-level files already frozen
by #6918.  The Python batch implementation remains byte-identical at SHA-256
`12285fd01ff8df80d154d65677fe779147e1e95fddaedec6303d53b8755d107f`.
Only the workflow hash in the live successor freeze changes.

This repair executes no provider, recurrence, dynamic kernel, exponential
action, Torch operation, optimizer step, training, HPCA generation, or
production action.  It does not transfer the original #6918 evidence to a new
scientific identity and does not close the authentic N256 resource gate.

#6908 remains `RED_DUPLICATE_KEY`; #6913 remains
`RED_NONCANONICAL_INPUT`; #6901's numerical cause remains `UNKNOWN`; C2 full
replay remains 0/6; HPCA remains NoUpdate; global `all_closed` remains false.
