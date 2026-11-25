# 天气积留位置 · Weather Surface Physics

一个在本机运行的 Codex 技能。输入照片和已经对齐的分区蒙版，输出每种天气在哪些具体部位会积留。例如，树枝上沿可以积雪，树干迎雨侧可以挂冰。它为下游特效程序提供原尺寸位置蒙版、逐部位 JSON 和离线预览。

支持积雪、积水、结霜、凝露、冻雨挂冰、积水再冻结和冰雹堆积。单张照片提供相对几何线索，温度、受雨方向和表面状态由情景假设给出。清单会记录这些假设。

## 安装

使用 Python 3.10–3.13。将本仓库克隆到 Codex 技能目录后安装依赖：

```sh
git clone https://github.com/wyb0508/weather-surface-physics.git ~/.codex/skills/weather-surface-physics
cd ~/.codex/skills/weather-surface-physics
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 运行

原图和清单须来自同一次分区。支持 `scene-regions/v1` 清单；已有独立蒙版也可以按[导入说明](references/review.md)整理。

```sh
./run.sh placement photo.jpg --manifest regions/manifest.json --weather 大雪 --out result
./run.sh batch regions.zip --photos photos --out batch-result
```

打开输出目录的 `模拟结果.html` 查看照片与模拟对照。单图从 `handoff.json` 取逐天气蒙版，批量从 `index.json` 查找每张图。灰度值 255 表示会积留，0 表示不会，127 表示证据不足、渲染时跳过。需要细分车顶与玻璃、桌板与桌腿时，按[部位修订格式](references/placement.md)补充局部判断。

## 许可

本目录的原创代码和文档采用 [MIT 许可证](LICENSE)。随附的模型权重和第三方配置各自保留原许可。详见[第三方文件清单](THIRD_PARTY.md)。
