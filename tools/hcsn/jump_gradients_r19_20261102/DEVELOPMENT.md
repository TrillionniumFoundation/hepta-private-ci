# Before the registered source freeze

Only development probes at dx=.25/dt=.04, baseline risk1, were run. That mesh is
outside the two registered verification meshes. The captured actual-primal
shape was31×2×33; both engines had zero critical ties. Selected raw coordinates
0/5/6/10/14 had centered finite-difference maximum scaled differences below
5.60e-11. An independently assembled all-time sparse system (2442equations)
agreed with the forward Jacobian to1.11e-16; a generic regular direction agreed
with its Jacobian product to6.94e-17. These helped implementation review and are
not independent scientific confirmation. Exact total development CPU was not
measured and is unknown, not zero.

No registered3risk×2mesh×15coordinate campaign, constructed critical cases,
fixed-target training sequence or case output has been opened before this
source/protocol freeze. The work is deterministic implementation qualification,
not an architecture/general-learning experiment.
