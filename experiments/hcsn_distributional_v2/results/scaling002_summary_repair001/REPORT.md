# SCALING002: reconstructed summary of the original30 timings

All30 original workers succeeded. The original suite returned1 while dividing by a T16 CPU median recorded as0; its failed receipt remains unchanged. This independent read-only summary reruns no model or timing. Every median is checked against all three original per-operation records.

A recorded0 CPU duration is preserved and does not mean computational work was free. Ratios with a zero denominator are unavailable. No epsilon, substituted wall time, or fresh measurement is inserted. Wall measurements remain separate original observations.

| Model | T | Width | Depth | Actual parameters | Forward CPU(s) | Adam CPU(s) | Forward wall(s) | Adam wall(s) | Whole worker CPU(s) | Peak RSS(KiB) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| distribution_free_dual | 16 | 32 | 1 | 20474 | 0.017363179 | 0.058803294 | 0.020571267 | 0.060663217 | 3.117556000 | 278892 |
| two_gates | 16 | 32 | 1 | 20308 | 0.000000000 | 0.006019383 | 0.001367338 | 0.008410984 | 2.581344000 | 272280 |
| transformer | 16 | 32 | 1 | 20930 | 0.000000000 | 0.001183971 | 0.000439939 | 0.003966273 | 2.570255000 | 275664 |
| distribution_free_dual | 32 | 32 | 1 | 20474 | 0.020503989 | 0.068087437 | 0.021129004 | 0.072031931 | 3.076141000 | 285056 |
| two_gates | 32 | 32 | 1 | 20308 | 0.000000000 | 0.004674041 | 0.001514986 | 0.007770669 | 2.386786000 | 272600 |
| transformer | 32 | 32 | 1 | 20930 | 0.000000000 | 0.000000000 | 0.000428592 | 0.002916814 | 2.411918000 | 275988 |
| distribution_free_dual | 64 | 32 | 1 | 20474 | 0.035454361 | 0.123171694 | 0.036757926 | 0.125101513 | 3.283911000 | 295964 |
| two_gates | 64 | 32 | 1 | 20308 | 0.000000000 | 0.012980656 | 0.003018084 | 0.014650451 | 2.284653000 | 273448 |
| transformer | 64 | 32 | 1 | 20930 | 0.000000000 | 0.001606008 | 0.000595619 | 0.003917051 | 2.531097000 | 275752 |
| distribution_free_dual | 128 | 32 | 1 | 20474 | 0.057627329 | 0.243568642 | 0.060000143 | 0.247022458 | 3.843783000 | 318824 |
| two_gates | 128 | 32 | 1 | 20308 | 0.004018026 | 0.023006167 | 0.005953937 | 0.026236831 | 2.763898000 | 275264 |
| transformer | 128 | 32 | 1 | 20930 | 0.000000000 | 0.000393415 | 0.000845157 | 0.004103967 | 2.430430000 | 276516 |
| distribution_free_dual | 256 | 32 | 1 | 20474 | 0.137728223 | 0.582099096 | 0.139249855 | 0.583224936 | 5.559587000 | 364724 |
| two_gates | 256 | 32 | 1 | 20308 | 0.014005111 | 0.062199710 | 0.015476270 | 0.063924367 | 2.974224000 | 279220 |
| transformer | 256 | 32 | 1 | 20930 | 0.001174357 | 0.007427533 | 0.001901296 | 0.007583527 | 2.653743000 | 277368 |
| distribution_free_dual | 512 | 32 | 1 | 20474 | 0.272292032 | 1.514273686 | 0.275973580 | 1.515511031 | 9.935776000 | 452964 |
| two_gates | 512 | 32 | 1 | 20308 | 0.027518768 | 0.139172928 | 0.028092142 | 0.140350522 | 3.484345000 | 286612 |
| transformer | 512 | 32 | 1 | 20930 | 0.002390225 | 0.015814731 | 0.004595844 | 0.018957039 | 2.908011000 | 278544 |
| distribution_free_dual | 64 | 32 | 2 | 38410 | 0.065923599 | 0.278357969 | 0.068137150 | 0.281448548 | 4.003898000 | 318572 |
| two_gates | 64 | 32 | 2 | 38710 | 0.003752902 | 0.028299179 | 0.006650536 | 0.029935432 | 2.807886000 | 275444 |
| transformer | 64 | 32 | 2 | 38793 | 0.000000000 | 0.006306660 | 0.000969260 | 0.007659704 | 2.843354000 | 276548 |
| distribution_free_dual | 64 | 32 | 4 | 74282 | 0.129982214 | 0.530113222 | 0.130840530 | 0.532529197 | 5.289304000 | 363552 |
| two_gates | 64 | 32 | 4 | 74067 | 0.016348786 | 0.084316205 | 0.018084530 | 0.085893557 | 2.958892000 | 279532 |
| transformer | 64 | 32 | 4 | 72611 | 0.000000000 | 0.005717023 | 0.001065442 | 0.008162656 | 2.590824000 | 277336 |
| distribution_free_dual | 64 | 64 | 1 | 55226 | 0.034327866 | 0.122312736 | 0.035424502 | 0.125148702 | 2.996519000 | 296960 |
| two_gates | 64 | 64 | 1 | 55188 | 0.000611610 | 0.012639559 | 0.003013958 | 0.015694543 | 2.411601000 | 274492 |
| transformer | 64 | 64 | 1 | 55280 | 0.000000000 | 0.002862277 | 0.000712822 | 0.005084645 | 2.646076000 | 276720 |
| distribution_free_dual | 64 | 64 | 2 | 105386 | 0.061245131 | 0.267860300 | 0.063318816 | 0.268970326 | 3.673984000 | 320220 |
| two_gates | 64 | 64 | 2 | 105492 | 0.003899240 | 0.037672170 | 0.005886147 | 0.038290392 | 2.956849000 | 277296 |
| transformer | 64 | 64 | 2 | 105034 | 0.000000000 | 0.005269417 | 0.000985435 | 0.007641928 | 3.091160000 | 277920 |

## Fixed width32/depth1: observed changes from T16

| Model | T | Forward CPU ratio | Adam CPU ratio | Forward wall ratio | Adam wall ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| distribution_free_dual | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| distribution_free_dual | 32 | 1.1809 | 1.1579 | 1.0271 | 1.1874 |
| distribution_free_dual | 64 | 2.0419 | 2.0946 | 1.7869 | 2.0622 |
| distribution_free_dual | 128 | 3.3189 | 4.1421 | 2.9167 | 4.0720 |
| distribution_free_dual | 256 | 7.9322 | 9.8991 | 6.7691 | 9.6141 |
| distribution_free_dual | 512 | 15.6822 | 25.7515 | 13.4155 | 24.9824 |
| two_gates | 16 | unavailable: zero denominator | 1.0000 | 1.0000 | 1.0000 |
| two_gates | 32 | unavailable: zero denominator | 0.7765 | 1.1080 | 0.9239 |
| two_gates | 64 | unavailable: zero denominator | 2.1565 | 2.2073 | 1.7418 |
| two_gates | 128 | unavailable: zero denominator | 3.8220 | 4.3544 | 3.1194 |
| two_gates | 256 | unavailable: zero denominator | 10.3332 | 11.3185 | 7.6001 |
| two_gates | 512 | unavailable: zero denominator | 23.1208 | 20.5451 | 16.6866 |
| transformer | 16 | unavailable: zero denominator | 1.0000 | 1.0000 | 1.0000 |
| transformer | 32 | unavailable: zero denominator | 0.0000 | 0.9742 | 0.7354 |
| transformer | 64 | unavailable: zero denominator | 1.3565 | 1.3539 | 0.9876 |
| transformer | 128 | unavailable: zero denominator | 0.3323 | 1.9211 | 1.0347 |
| transformer | 256 | unavailable: zero denominator | 6.2734 | 4.3217 | 1.9120 |
| transformer | 512 | unavailable: zero denominator | 13.3574 | 10.4465 | 4.7796 |

Random weights/labels, batch1, one shared synthetic input sequence, CPU float32, one thread, one forward/Adam warmup and three measured forwards/full Adam steps. All actual parameter counts are reported; no imposed3% parameter matching claim. RSS is whole-process high-water memory, including interpreter, imports, construction and backwards; it is not isolated activation memory.

Original suite CPU and each worker CPU are nested. The separate reconstruction process is measured independently. These30 points provide no evidence about content quality, GPU, energy, distributed execution, equal-quality throughput, foundation models or an asymptotic scaling law.
