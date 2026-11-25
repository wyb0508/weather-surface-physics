---
name: weather-surface-physics
description: 读取已分区照片或上游分区 ZIP，自主按可见部位估计积雪、积水、霜、露、挂冰、再冻结和冰雹，向下游特效技能交付原尺寸位置蒙版与逐区块清单。
---

# 天气积留位置

使用者给出原图或原图目录、上游分区素材和可选天气。本技能自行定位素材、推断、复核和交接，全程无问答。指定天气时只交付该情景；省略时计算全部七种。每个结论回答某处是否会积留。

## 运行

单图用 placement，分区 ZIP 或含多份 manifest.json 的目录用 batch。SKILL_DIR 指本文件所在目录。原图可以在包外；批量入口用文件指纹匹配，包括已改名的原图。输出使用一个新目录。

```sh
"$SKILL_DIR/run.sh" placement "$PHOTO" --manifest "$REGIONS/manifest.json" --weather 大雪 --out "$OUT"
"$SKILL_DIR/run.sh" batch "$PACK" --photos "$PHOTO_DIR" --out "$OUT"
```

已有独立二值蒙版时，先按[导入格式](references/review.md#独立蒙版导入)保留原边界。仅有原图且可用 scene-regions 时，先由该技能生成清单。继续使用上游区块和分组，在每个区块内部细分响应不同的部位。

## 自主复核

打开「模拟结果.html」对照原图检查。单图估计的深度、朝向和遮挡只能提供几何线索。按图中的具体部位复核；如需修正，agent 自行编制绑定该清单的多边形文件，再用 placement 的 --patches 或 batch 的 --reviews 重新导出。格式见[空间修订与各天气规则](references/placement.md)。

- 普通降雪检查树冠外层、横枝上沿、直立树干、枝间天空；再检查桌板与桌腿、栏杆顶与立柱。被棚、桌板或停放车辆直接盖住的地面独立处理。投影范围可能大于真实遮挡范围。
- 车辆分开看车顶、前盖、风挡、近直立侧窗、轮侧与车底。照片中的树冠倒影沿用玻璃表面属性。风挡温度、坡度或运动导致留雪结论不清时保守略过。需引用已有的主体动静、地面状态和来水信息。
- 雨后水洼需同时有来水和可蓄住明水的凹面。夜景反光、阴影和单目深度上的局部低点不足以确认水洼。霜、露、冻雨与再冻结分别按相应温湿情景判断。沿海短时情景保留开阔水面。题字、拍摄信息栏和角标全部排除。
- 「雨中积雪」默认解释为雨落在已有雪面，新雪与旧雪分别记录。「结冰」自动展开为冻雨挂冰和积水再冻结。无法定位或缺少决定性条件时出具「保守略过」，下游直接跳过该处。

## 下游交付

交付整个输出目录。单图以 handoff.json 为入口，批量以 index.json 为入口。「模拟结果.html」可离线切换照片和天气。locations.map 的原始整数对应 locations.parts 和原 region_id；maps 中的 PNG 尺寸与应用 EXIF 旋转后的原图一致，最近邻采样。灰度 **255 表示会积，0 表示不会积，127 表示保守略过**。渲染端仅在值等于 255 的像素绘制。蓝绿及琥珀色叠图供目检。

仅在另行要求过程、时间或流量时运行[详细仿真](references/simulation.md)。需要复用早期纯文字部位清单时采用 --parts，输出文字型 handoff.json。

## 首次安装

将本仓库克隆到 Codex 技能目录下的 weather-surface-physics 子目录（通常为 ~/.codex/skills/weather-surface-physics）。复用已有 Python 环境即可；新机器由 agent 在技能目录执行以下步骤。使用 Python 3.10–3.13，安装 Python 依赖时需要网络。模型、标签表及许可文件随包提供，推断在本机运行。

```sh
python3 -m venv "$SKILL_DIR/.venv"
"$SKILL_DIR/.venv/bin/python" -m pip install -r "$SKILL_DIR/requirements.txt"
```
