# 详细雨雪仿真

需要逐时刻水膜、融雪、径流或滴落时使用显式 simulate 命令。未提供天气方案时按静止、自然地面计算；--answers 仅传入已有的、与这张原图匹配的完整方案。优先利用照片线索自行指定 --review，使用[局部多边形](review.md)修正受遮挡表面、初始积雪和可见滴落路径。主体、温度、坡向均采用已有信息或声明的假设，全程无交互。

```sh
"$SKILL_DIR/run.sh" simulate "$PHOTO" --manifest "$REGIONS/manifest.json" \
  --weather 大雨 --temperature 4 --out "$OUT"
```

四档雪使用固定的事件负荷。雨中的旧雪可用 --old-snow 或局部修正指定。核对三帧结果、表面边界、水量收支后，按照[时序图层协议](renderer.md)交付。

随包相对深度模型是 Depth Anything V2 Small；详细仿真使用 salient 主体时会调用 U²-NetP。权重与对应的许可文件位于 models 下。[Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) · [U²-Net](https://github.com/xuebinqin/U-2-Net)
