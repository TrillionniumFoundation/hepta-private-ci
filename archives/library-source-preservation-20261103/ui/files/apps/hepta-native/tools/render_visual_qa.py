#!/usr/bin/env python3
"""Rasterize exported real egui primitives, including their actual font atlas.

This is headless render evidence, not a native compositor screenshot. Geometry,
widget state, clipping, UVs, colors, text shaping, and font pixels are produced
by the production App::ui callback. Rasterization follows egui_glow's gamma-space
premultiplied-alpha shader without optional dithering. It does not test a window
manager, GPU driver, screen reader, native picker, IME, or physical mixed DPI.

Requires the existing Python numpy and Pillow packages; no new Rust dependency.
Usage: python tools/render_visual_qa.py /path/to/export-directory
"""

import argparse
import base64
import json
from pathlib import Path

import numpy as np
from PIL import Image


def texture_images(patches):
    textures = {}
    for patch in patches:
        width, height = patch["size"]
        pixels = np.frombuffer(base64.b64decode(patch["rgba_base64"]), dtype=np.uint8)
        pixels = pixels.reshape(height, width, 4).copy()
        if patch["position"] is None:
            textures[patch["id"]] = (pixels, patch["filter"])
        else:
            x, y = patch["position"]
            textures[patch["id"]][0][y : y + height, x : x + width] = pixels
    return textures


def sample_texture(texture, uv, filtering):
    height, width, _ = texture.shape
    if filtering == "Nearest":
        x = np.clip((uv[:, 0] * width).astype(int), 0, width - 1)
        y = np.clip((uv[:, 1] * height).astype(int), 0, height - 1)
        return texture[y, x].astype(np.float64) / 255.0
    coords = uv * np.array([width, height]) - 0.5
    lower = np.floor(coords).astype(int)
    blend = coords - lower
    x0, y0 = lower[:, 0], lower[:, 1]
    x1, y1 = x0 + 1, y0 + 1
    x0, x1 = np.clip(x0, 0, width - 1), np.clip(x1, 0, width - 1)
    y0, y1 = np.clip(y0, 0, height - 1), np.clip(y1, 0, height - 1)
    tx, ty = blend[:, 0, None], blend[:, 1, None]
    top = texture[y0, x0] * (1 - tx) + texture[y0, x1] * tx
    bottom = texture[y1, x0] * (1 - tx) + texture[y1, x1] * tx
    return (top * (1 - ty) + bottom * ty) / 255.0


def edge(a, b, x, y):
    return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])


def top_left(a, b):
    return b[1] < a[1] or (b[1] == a[1] and b[0] > a[0])


def rasterize(document):
    scale = document["pixels_per_point"]
    width, height = np.rint(np.array(document["logical_size"]) * scale).astype(int)
    canvas = np.empty((height, width, 4), dtype=np.float64)
    canvas[:] = document["clear_color"]
    textures = texture_images(document["textures"])
    triangle_count = 0
    for mesh in document["meshes"]:
        clip = np.rint(np.array(mesh["clip"]) * scale).astype(int)
        clip = np.clip(clip, [0, 0, 0, 0], [width, height, width, height])
        vertices = mesh["vertices"]
        positions = np.array([vertex["position"] for vertex in vertices]) * scale
        uv = np.array([vertex["uv"] for vertex in vertices])
        colors = np.array([vertex["color"] for vertex in vertices], dtype=np.float64) / 255.0
        texture, filtering = textures[mesh["texture"]]
        for indexes in np.array(mesh["indices"]).reshape(-1, 3):
            triangle_count += 1
            p = positions[indexes]
            area = edge(p[0], p[1], p[2, 0], p[2, 1])
            if abs(area) < 1e-12:
                continue
            if area < 0:
                indexes = indexes[[0, 2, 1]]
                p = positions[indexes]
                area = -area
            x0, y0 = np.maximum(np.floor(p.min(axis=0)).astype(int), clip[:2])
            x1, y1 = np.minimum(np.ceil(p.max(axis=0)).astype(int), clip[2:])
            if x0 >= x1 or y0 >= y1:
                continue
            grid_y, grid_x = np.mgrid[y0:y1, x0:x1]
            x, y = grid_x + 0.5, grid_y + 0.5
            edges = [edge(p[1], p[2], x, y), edge(p[2], p[0], x, y), edge(p[0], p[1], x, y)]
            mask = np.ones(x.shape, dtype=bool)
            for value, (a, b) in zip(edges, [(p[1], p[2]), (p[2], p[0]), (p[0], p[1])]):
                mask &= (value > 1e-8) | ((np.abs(value) <= 1e-8) & top_left(a, b))
            if not mask.any():
                continue
            weights = np.stack([value[mask] / area for value in edges], axis=1)
            sampled = sample_texture(texture, weights @ uv[indexes], filtering)
            source = sampled * (weights @ colors[indexes])
            destination = canvas[grid_y[mask], grid_x[mask]]
            canvas[grid_y[mask], grid_x[mask]] = source + destination * (1.0 - source[:, 3, None])
    # Native nontransparent windows present an opaque framebuffer. All app
    # panels are opaque; retain RGB rather than exposing clear-color alpha.
    rgb = np.rint(np.clip(canvas[:, :, :3], 0, 1) * 255.0).astype(np.uint8)
    return Image.fromarray(rgb), triangle_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    summary = []
    for source in sorted(args.directory.glob("native_*.json")):
        document = json.loads(source.read_text())
        if document.get("schema") != "hepta.native-headless-visual-qa.v1":
            continue
        image, triangles = rasterize(document)
        destination = source.with_suffix(".png")
        image.save(destination)
        report = {"file": destination.name, "dimensions": image.size, "triangles": triangles}
        summary.append(report)
        print(json.dumps(report), flush=True)
    (args.directory / "render-summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
