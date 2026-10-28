# Semantic observer dependencies

The compact audio architecture in `semantic_backbones.py` follows the official [PANN implementation](https://github.com/qiuqiangkong/audioset_tagging_cnn), with strict loading of the original checkpoint and Fourier/mel kernels.

The MIT License
  
Copyright (c) 2018-2020 Qiuqiang Kong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.


The PANN checkpoint is published under CC BY 4.0 in [Zenodo record 3987831](https://zenodo.org/records/3987831). Attribution: Qiuqiang Kong et al., *PANNs: Large-Scale Pretrained Audio Neural Networks for Audio Pattern Recognition*, IEEE/ACM TASLP, 2020.

S3D is loaded from the official pinned CPU torchvision 0.23.0 package and official `s3d-d76dad2f.pth` weight URL. The torchvision BSD license is preserved with the acquisition files. The S3D model documentation states Kinetics-400 training; the new study does not claim Perception Test training from that checkpoint.

## Fine-grained TSM action backbone

The temporal shift implementation follows the official [MIT HAN Lab TSM release](https://github.com/mit-han-lab/temporal-shift-module). Attribution: Ji Lin, Chuang Gan and Song Han, *TSM: Temporal Shift Module for Efficient Video Understanding*, ICCV 2019. The exact released Something-Something V2 checkpoint, source and README hashes are retained.

MIT License

Copyright (c) 2021 MIT HAN Lab

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
