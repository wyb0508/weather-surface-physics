# 第三方文件

| 文件 | 来源 | 随附许可 |
| --- | --- | --- |
| `models/depth.onnx` | [Depth Anything V2 Small](https://github.com/DepthAnything/Depth-Anything-V2) 的 [ONNX 量化转换](https://huggingface.co/onnx-community/depth-anything-v2-small/blob/4472b7362082ad9968fee890ca0f1e5aca36b93d/onnx/model_quantized.onnx) | [Apache-2.0](models/LICENSE-DepthAnything.txt) |
| `models/foreground.onnx` | [U²-NetP](https://github.com/xuebinqin/U-2-Net)，通过 [rembg](https://github.com/danielgatis/rembg/releases/tag/v0.0.0) 发布 | [Apache-2.0](models/LICENSE-U2Net.txt) |
| `models/classes.json` | 从 [MMSegmentation v1.2.2 的 ADE20K 类别列表](https://github.com/open-mmlab/mmsegmentation/blob/v1.2.2/mmseg/datasets/ade.py) 按原名称和顺序转换成 JSON，用于匹配上游分区。Copyright (c) OpenMMLab。 | [Apache-2.0](models/LICENSE-MMSegmentation.txt) |

Python 依赖按 requirements.txt 安装，各包适用其自身的许可。
