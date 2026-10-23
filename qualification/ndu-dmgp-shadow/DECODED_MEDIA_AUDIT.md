# NDU-DMGP original-byte decoded-media qualification (research-only)

This additive package contains `decoded_media_audit.py` and `test_decoded_media_audit.py` for the existing `qualification/ndu-dmgp-shadow` tree.

The previous NDU-DMGP reference checked signed claims and content-addressed perceptual references, but did not independently open, hash, and decode the referenced output assets. This V1 read-only external audit checks four real files per run (UTF-8 text, PNG image, PCM WAV audio, MP4 video), validates original SHA-256 digests, probes/decodes each relevant physical stream, binds objective/input/generation/declared timeline, rejects unmeasured extra streams, and checks bounded modality and time dimensions. It rejects unsafe paths, symlinks, corrupt hashes, nondecodable media and time/entity mismatches. Input files are copied into isolated snapshots before invoking ffmpeg with a restricted local protocol whitelist.

Test fixtures are generated with Python and FFmpeg signal generators, **not a trained multimodal model**. This tests a real codec path, *not* actual model quality or perceptual semantics; event/entity labels are untrusted declarations. `verified_original_bytes_and_real_media_decode` must never be interpreted as signed independently recognized content. The result expressly marks model generation, semantic observation, lip-sync, signer identity, calibrated host energy and all production blockers as false. No inference worker, NDU source owner, authority or artifact selector changes.

## Format admission regression

The V1 contract above requires PNG, PCM WAV and MP4, not arbitrary playable
files bearing those extensions. FFmpeg's automatic sniffing previously admitted
rehashed JPEG-as-PNG, compressed ADPCM WAV, Matroska-as-MP4 and QuickTime-as-MP4.
Real codec-generated substitutions reproduce all four failures on parent
`0de1a3e22ef5da843145e32dcf13b950afb714f2` (#3509).

Admission now checks original signatures and the independently probed container
and codec. PNG must have a PNG signature/codec; WAV may use RIFF/RIFX/RF64 and a
`pcm_*` codec, including companded A-law/mu-law PCM. This is PCM-family
admission, not a claim that every WAV is linear, lossless or uncompressed;
ADPCM and MP3 codecs are not admitted. The bounded MP4 profile requires a leading `ftyp` box of at most
4096 bytes, a known MP4/ISO-compatible brand, and a probed MP4-compatible
container; QuickTime major branding is not admitted. Unrecognized container
profiles are unsupported, not silently certified. PCM 8/24-bit, float and
A-law/mu-law WAV, RF64 PCM, plus fast-start and fragmented MP4 have real
positive controls.
The receipt additionally reports the observed codec and format. Existing
content digests and scientific no-promotion flags are unchanged.

Run the regression with `python3 -m unittest discover -s
qualification/ndu-dmgp-shadow -p 'test_media_type_admission.py' -v`. The dedicated
media workflow includes the new test in its trigger, compilation and discovery.
This repairs structural evidence admission only; it provides no evidence of
neural output quality, independent perceptual truth or hardware efficiency.

Run: `python3 -m unittest discover -s qualification/ndu-dmgp-shadow -p 'test_decoded_media_audit.py' -v` (requires ffmpeg and ffprobe). The dedicated GitHub Actions workflow runs on ubuntu-24.04, fails if decoder tools are absent, and binds the tested commit to the submitted PR head. The original A0-A5 exact source and its 80 passed tests are unchanged by the addition.

Next evidence before production qualification: a real Encoder+Decoder sends trace-bound original outputs to a separately trusted physical host and independent perceptual observer, with documented external key custody and calibration; prospective matched A0-A5 across original source clusters; spectrum-verified real conditional covariance; equal-quality energy/latency/peak memory; frozen Critic/Actor and future retention; causal Cell credits in the actual owner. All remain OPEN.
