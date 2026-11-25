# 图像绑定的表面复核

用原始 manifest.json 文件字节的 SHA-256（macOS 可用 shasum -a 256）绑定本次区块编号和分组，并复制 analysis_size。下例中的编号和坐标仅作格式说明。多边形采用分析图左上原点的整数坐标，脚本与指定 region_id 取交集。省略 polygon 即作用于整个区块，后写入的同名属性优先。来自天气方案的完全遮挡始终生效。

```json
{
  "manifest_sha256": "替换为清单文件摘要",
  "analysis_size": [1024, 576],
  "note": "桌沿右侧可见地面，按轻微向右倾斜的桌板估算。",
  "patches": [
    {"region_id": 5, "up": 0, "material": "hard", "note": "桌体以直立面为底，再单独标出桌板"},
    {"region_id": 5, "polygon": [[180,210],[500,213],[530,250],[155,248]], "up": 0.96, "flow": "right", "old_snow": 0.4, "note": "仅桌面有旧雪"},
    {"region_id": 6, "polygon": [[220,268],[455,268],[470,420],[204,420]], "exposure": 0, "note": "桌下避开直接降雨"}
  ],
  "drains": [
    {"from": {"region_id": 5, "polygon": [[505,224],[529,248],[518,248]]},
     "to": {"region_id": 6, "polygon": [[518,424],[530,424],[526,431]]},
     "note": "可见桌沿与下方地面，估算垂直滴落"}
  ]
}
```

up 和 exposure 都是 0–1 比例。material 可取 air、water、smooth、hard、porous、foliage。flow 取图像平面的 left、right、up、down 或 still；设置方向代表可辨认的表面坡向，近水平且坡向未知时保留默认。old_snow 为初始参考负荷，实际存量还会乘承托能力。出口和落点需在各自区域内选取窄小的实际接触范围。drains 可留空，此时水只在同区内流动。对未知材料，先按硬表面估算并记录需要核实之处。

## 独立蒙版导入

如果上游只有原图和逐块 PNG，在蒙版目录写一份 JSON，包含原图字节 sha256 及 regions 数组。每项例如 `{"key":"table-top","label":"table","group":"table","mask":"top.png"}`。key 唯一，label 选择项目 models/classes.json 中相符的语义；一件物体的多个面可共享 label 和 group。蒙版按应用 EXIF 旋转后的原尺寸对齐，L 模式用白色表示区内，有 Alpha 的素材用不透明像素表示区内。提供覆盖全图、互斥的二值可见区块，包括背景。若原始图层有前后重叠，先按已知的可见顺序扣除前景，并核对半透明边缘。

执行下列命令，随后把输出清单传给 run.sh。

```sh
"$SKILL_DIR/run.sh" pack_masks "$PHOTO" "$MASKS/spec.json" --out "$REGIONS"
```
