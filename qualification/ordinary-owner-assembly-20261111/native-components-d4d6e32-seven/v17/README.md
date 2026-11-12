# V42 original formatting failure

The complete original v17 terminal ended with exit 1 at source `d4d6e32b1e8c1f976c035c0f9581d903622d9e77`. `just fmt` returned 0 but changed two long `owners.factory` call layouts. The unchanged executor correctly rejected the dirty source with exit 1. Seven launch logs, two original execution records, exact stdout recovered from those complete tees, the real formatter patch and full formatter output source are retained.

The final physical-source cleanup failed because that actual Rust file was dirty; the other four cleanup steps passed. No fix, compilation, QA, full caller, ordinary native or Root17 test was reached. V43 adopts only the two actual emitted layouts and matching protection spellings. No test pass is inherited, and no failure is classified as NoUpdate. All business acceptance counts remain 0/0/0.
