# Restore the NDU workflow step boundary

The initial S1 workflow insertion omitted the original tool-install step name.
Its `uses` and `with` fields therefore attached to the preceding S1 `run` step.
This correction restores exactly one line: `- name: Install pinned repository test tools`.
The S1 commands and environment remain unchanged.

Strict YAML parsing and independent review cover the entire workflow: one job,
15 steps, exactly one `run` or `uses` in each step, no duplicate keys and no
`with` attached to a run step. Removing the new S1 step from the corrected
parsed document gives the exact original parent workflow structure.

Native `just fmt` and `git diff --check` run in an isolated correction projection.
The corrected YAML hash remains identical before and after formatting. Python
component source is unchanged; the earlier combined 17 normal and 17 optimized
passes retain their original source identity. No component tests are repeated.

These receipts establish static configuration and formatting checks. They do
not assert remote workflow execution or overall CI success. Scientific HOLD
and production NoUpdate remain. The original faulty commits and their evidence
are preserved, followed by a small fast-forward correction on each S1 CTRL PR.
