# First artifact fixture capture

After protocol/generator registration at
`6b4c68c7deabe2c201f20156ba451e96ad86f1db`, the existing
`test_paired_source.capture` helper was called once for failure answer 0 and
once for correction answer 1. Both create-only writes and original readbacks
completed. The single invocation exited 0 in 0.16464384099526796 seconds;
helper work was 0.004880102991592139 seconds. No native Rust gate or model
training executed during this capture. Human participants: zero.

| Original file | Bytes | Exact raw SHA256 | Full Python record_digest |
| --- | ---: | --- | --- |
| failure.json | 1319 | e1bf2515221b599cb1ec30681df7b77908891e52259bf35e8f865960603023ac | a7e5d55b674d728752a302f1f40b2eb7af02f284f50ff641123cc049368b48c2 |
| correction.json | 1324 | eae445c5e6ceeaeeb8a390509109d2f48b6d7270e96bef715e9e1e09188e47ed | 77506dc0d93a2032429b1d3b8797f3b5cc4d42aab26ee2be796f8eb4b6874f48 |

The fixture source base is `abcb9b20385d0588d0342529906af658b3012711`.
The capture's source hashes were checked before and after. The records retain
the existing engineering fixture's declarations, including its zero-human
scope; those declarations and placeholder policy identifiers do not prove a
model run, human consent or source authentication. The standalone Python
canonical conformance file has raw SHA256
`ac628e442e34732d9c4293e16485fea865bd4bcc90b0b56bc9762ec0addca739`.

The exact generated record files are copied into Agentd's compile-time fixtures.
No contents were normalized, cropped or repaired. Native identity tests remain
a separately frozen eight-control gate under the existing exclusive engineering
owner and cumulative budget. This capture is not a native pass or training result.

Raw capture archive: 6178 bytes; SHA256
`b19a9f05f8a72201873298d8bbcba3773bc9ceb494980805599c6bd178c18ef8`.
