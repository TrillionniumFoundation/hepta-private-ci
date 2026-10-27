"""Independent byte delivery, caption parsing and frozen-image utility scoring."""

import hashlib
import io
import zipfile

import numpy as np
from PIL import Image
import torch
from torch import nn


VOCABULARY = ('<pad>', '<bos>', '<eos>', 'left', 'right', 'relation', 'less', 'equal',
              'greater', 'keep', 'swap', 'unknown', 'hint_left', 'hint_right')+tuple(map(str, range(10)))


def observer(path):
    network = nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                            nn.Flatten(), nn.Linear(32*7*7, 64), nn.ReLU(), nn.Linear(64, 10))
    stored = torch.load(path, weights_only=True, map_location='cpu')
    network.load_state_dict({key.removeprefix('net.'): value for key, value in stored.items()})
    return network.eval().requires_grad_(False)


def decode_caption(token_ids):
    words = []
    for token in token_ids.tolist():
        if token == 2:
            break
        if token in (0, 1):
            continue
        words.append(VOCABULARY[token] if 0 <= token < len(VOCABULARY) else '<invalid>')
    return ' '.join(words)


def deliver_and_score(path, output, target_pixels, target_labels, recognizer):
    quantized = np.rint(output.image_logits.sigmoid().detach().cpu().numpy()*255).astype(np.uint8)
    captions = [decode_caption(tokens) for tokens in output.token_ids]
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as stream:
        for index, (pixels, text) in enumerate(zip(quantized, captions)):
            memory = io.BytesIO()
            Image.fromarray(pixels[0]).save(memory, format='PNG')
            stream.writestr(f'{index}/image.png', memory.getvalue())
            stream.writestr(f'{index}/caption.txt', text.encode('utf-8'))
    restored, texts, hashes = [], [], []
    with zipfile.ZipFile(path) as stream:
        expected = {f'{i}/{name}' for i in range(len(captions)) for name in ('image.png', 'caption.txt')}
        if set(stream.namelist()) != expected or len(stream.namelist()) != len(expected) or stream.testzip() is not None:
            raise AssertionError('Probe delivery archive differs from its complete media grid')
        for index in range(len(captions)):
            picture, text = stream.read(f'{index}/image.png'), stream.read(f'{index}/caption.txt')
            with Image.open(io.BytesIO(picture)) as image:
                if image.format != 'PNG' or image.mode != 'L' or image.size != (56, 28):
                    raise AssertionError('Probe image contract differs')
                restored.append(torch.tensor(np.array(image, copy=True)).float()[None]/255)
            texts.append(text.decode('utf-8'))
            hashes.append({'image': hashlib.sha256(picture).hexdigest(), 'text': hashlib.sha256(text).hexdigest()})
    pixels = torch.stack(restored)
    with torch.inference_mode():
        image_labels = torch.stack((recognizer(pixels[:, :, :, :28]).argmax(1),
                                    recognizer(pixels[:, :, :, 28:]).argmax(1)), dim=1).tolist()
    truth = target_labels.tolist()
    mse = np.mean((pixels.numpy().astype(np.float64)-target_pixels.numpy())**2, axis=(1, 2, 3))
    records, utilities = [], []
    for index, (text, actual, expected) in enumerate(zip(texts, image_labels, truth)):
        words = text.strip().split(' ')
        valid = (len(words) == 6 and words[0] == 'left' and words[2] == 'right'
                 and words[4] == 'relation' and words[1] in tuple(map(str, range(10)))
                 and words[3] in tuple(map(str, range(10))) and words[5] in ('less', 'equal', 'greater'))
        digits = [int(words[1]), int(words[3])] if valid else None
        relation = 'less' if expected[0] < expected[1] else 'greater' if expected[0] > expected[1] else 'equal'
        text_error = sum(a != b for a, b in zip(digits, expected))/2 if valid else 1.
        relation_error = float(words[5] != relation) if valid else 1.
        image_error = sum(a != b for a, b in zip(actual, expected))/2
        disagreement = sum(a != b for a, b in zip(actual, digits))/2 if valid else 1.
        utility = 1.-2.*(.30*text_error+.15*relation_error+.35*image_error+.10*disagreement+.10*mse[index])
        utilities.append(utility)
        records.append({'index': index, 'caption': text, 'hashes': hashes[index],
                        'image_labels': actual, 'target_labels': expected, 'pixel_mse': float(mse[index]),
                        'utility': float(utility), 'parsed_caption': digits, 'caption_valid': valid})
    return np.array(utilities), records
