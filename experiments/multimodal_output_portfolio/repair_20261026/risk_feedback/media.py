"""Deterministic finite codecs, actual files, and independent byte readback.

These are semantic test signals, not a trained image/speech/video generator.
The readback never receives the requested semantic code or hidden target.
"""
import hashlib
from pathlib import Path
import re
import struct
import wave

import numpy as np
from PIL import Image


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def chunk(tag, payload):
    return tag + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) % 2 else b"")


def frames(code):
    result = []
    for t in range(4):
        pixels = np.full((16, 16, 3), 32 + 64 * code, dtype=np.uint8)
        pixels[0, t * 4:(t + 1) * 4] = 255
        result.append(pixels)
    return result


def write_video(path, code):
    pixels = frames(code)
    nbytes = pixels[0].size
    avih = struct.pack("<14I", 250000, 4 * nbytes, 0, 16, 4, 0, 1, nbytes, 16, 16, 0, 0, 0, 0)
    strh = struct.pack("<4s4sIHH8I4h", b"vids", b"DIB ", 0, 0, 0, 0, 1, 4, 0, 4, nbytes, 0xffffffff, 0, 0, 0, 16, 16)
    strf = struct.pack("<IiiHHIIiiII", 40, 16, 16, 1, 24, 0, nbytes, 0, 0, 0, 0)
    stream = chunk(b"LIST", b"strl" + chunk(b"strh", strh) + chunk(b"strf", strf))
    header = chunk(b"LIST", b"hdrl" + chunk(b"avih", avih) + stream)
    movie, index, offset = b"", b"", 4
    for image in pixels:
        raw = image[::-1, :, ::-1].tobytes()
        encoded = chunk(b"00db", raw)
        movie += encoded
        index += struct.pack("<4sIII", b"00db", 16, offset, len(raw))
        offset += len(encoded)
    body = b"AVI " + header + chunk(b"LIST", b"movi" + movie) + chunk(b"idx1", index)
    Path(path).write_bytes(chunk(b"RIFF", body))


def emit(directory, code, transport_fault=0):
    if code not in range(4) or transport_fault not in range(3):
        raise ValueError("Unregistered semantic code or transport fault")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    paths = {"text": directory / "report.txt", "image": directory / "image.png",
             "audio": directory / "audio.wav", "video": directory / "video.avi"}
    paths["text"].write_text(f"category {code}\n", encoding="utf-8")
    image_code = (code + 1) % 4 if transport_fault == 1 else code
    audio_code = (code + 1) % 4 if transport_fault == 2 else code
    Image.fromarray(frames(image_code)[0]).save(paths["image"])
    samples = np.arange(8000, dtype=np.float64) / 8000
    pcm = np.rint(12000 * np.sin(2 * np.pi * (400 + 200 * audio_code) * samples)).astype("<i2")
    with wave.open(str(paths["audio"]), "wb") as writer:
        writer.setparams((1, 2, 8000, len(pcm), "NONE", "not compressed"))
        writer.writeframes(pcm.tobytes())
    write_video(paths["video"], audio_code)
    return {name: str(path) for name, path in paths.items()}


def chunks(data):
    cursor = 0
    while cursor + 8 <= len(data):
        tag, size = data[cursor:cursor + 4], struct.unpack_from("<I", data, cursor + 4)[0]
        end = cursor + 8 + size
        if end > len(data):
            raise ValueError("Truncated RIFF data")
        yield tag, data[cursor + 8:end]
        cursor = end + size % 2
    if cursor != len(data):
        raise ValueError("Unexpected RIFF trailing bytes")


def readback(paths):
    match = re.fullmatch(r"category ([0-3])\n", Path(paths["text"]).read_text(encoding="utf-8"))
    if match is None:
        raise ValueError("Invalid actual text")
    text = int(match.group(1))
    with Image.open(paths["image"]) as image:
        pixels = np.asarray(image.convert("RGB"))
    image = int(round((float(np.median(pixels[1:])) - 32) / 64))
    with wave.open(paths["audio"], "rb") as reader:
        if reader.getparams()[:4] != (1, 2, 8000, 8000):
            raise ValueError("Unexpected actual audio clock")
        waveform = np.frombuffer(reader.readframes(8000), dtype="<i2")
    frequency = int(np.abs(np.fft.rfft(waveform)).argmax())
    audio = int(round((frequency - 400) / 200))
    raw = Path(paths["video"]).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"AVI ":
        raise ValueError("Actual video header missing")
    videos, markers = [], []
    for tag, payload in chunks(raw[12:]):
        if tag == b"LIST" and payload[:4] == b"movi":
            for identifier, payload in chunks(payload[4:]):
                if identifier != b"00db" or len(payload) != 768:
                    raise ValueError("Unexpected actual video frame")
                frame = np.frombuffer(payload, dtype=np.uint8).reshape(16, 16, 3)[::-1, :, ::-1]
                videos.append(int(round((float(np.median(frame[1:])) - 32) / 64)))
                markers.append(int(np.argmax(frame[0, :, 0])))
    if len(videos) != 4 or markers != [0, 4, 8, 12] or any(v not in range(4) for v in [image, audio, *videos]):
        raise ValueError("Invalid decoded semantic signal or moving video")
    mismatch = int(image != text) + int(audio != text) + int(any(v != text for v in videos))
    fault_class = 0 if mismatch == 0 else 1 if mismatch == 1 else 2
    return {"codes": {"text": text, "image": image, "audio": audio, "video": videos},
        "fault_class": fault_class, "target_supplied": False,
        "clock": {"audio_samples": 8000, "sample_rate": 8000, "video_frames": 4, "video_fps": 4},
        "media_sha256": {name: file_sha(path) for name, path in paths.items()}}
