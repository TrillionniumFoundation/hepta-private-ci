# Public provider placement: original peer constraints

This is a static source finding, not an observed runtime or test failure.
The current source ref remains cc57. No guard, UID, deadline or request limit
was changed or executed by this review.

The original `original_owner_command_channel_v1` in
`f42d9f385ecafa17e02d993677ca261e02926beb` rejects a peer whose UID equals the
caller's real or effective UID, and independently rejects its own PID.
`OriginalCellQ24TrainingReadbackConnectionV1::from_original_stream` in
`028a4ceba0738db604bcaf3bc1bf548f8c5dd832` uses that function. B/E's actual
original Trainer evidence capability therefore cannot be admitted with its
Trainer in the same UID. Version's original T and E command clients have the
same constraint. Root's initial Version capability also uses the same helper.

This yields a necessary three-nonRoot-UID lower bound for the currently chosen
remote T/E inputs. Root has accepted the following proposed placement:

| Fixed fixture UID | Original roles | Existing cross-UID inputs |
| --- | --- | --- |
| 60001 | A, Material, Version, S, C | T from 60002; E from 60003 |
| 60002 | Trainer and Model | Material from 60001; E from 60003 |
| 60003 | independent B/retention and E | original T readback from 60002 |
| 0 | resident Root and explicit fixture issuer | role endpoints above |

The numbers describe the planned test placement, not observed PIDs or proof of
independent external outcomes. The original trust also checks controllers and
signatures; distinct UIDs do not replace those checks.

## Additional unresolved same-host inputs

Three UIDs alone do not close the graph. In the proposed 60001 placement,
S and C still need their live Version/Source reads, and C still needs original
S evidence. `OriginalCircuitLearningReadClientV1::from_original_profile` in
`4db1399444a01432f056f71e7322990750f3ce0f` calls the same original peer helper.
The Version read service and `Selector::serve_evidence_readback` in
`46ea741fc91046f9e6c7407949e630d45ca2ca3b` do too. Thus public socket assembly
cannot admit these internal 60001-to-60001 edges.

The existing shared T/E bundle is only an in-process Arc capability. Moving S
or C into yet another process would lose that sharing and restore the original
public T connection-budget problem. The already frozen Fresh publication test
uses explicit same-process test adapters for these edges; it must remain a
mechanism test and cannot be cited as public placement success.

The required engineering direction is an explicit sealed same-host read-only
capability: Version must retain its original Published/current checks and same
C/Source owners; each actual read must still revalidate complete T/E/current
state. C's local S predecessor must read the same original S owner through the
already implemented opaque readonly conversion, not a supplied receipt. Such
new interfaces must preserve fixed purpose/full signatures, original deadlines
and request limits, cancellation uncertainty and refusal on concurrency. They
must expose no owner, raw Client/FD, Execute, rebind, new signature or callback.
Old remote and by-value entries remain unchanged. This report is not approval
or implementation of those additional interfaces.

The separate harness stack increment only explicitly passes the old 8388608
byte contract. It does not establish an actual child stack observation or any
completed role. No full ten-owner, same-C daemon or Root recovery run is claimed.
