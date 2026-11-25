import json
from pathlib import Path


def write_preview(folder, scenes):
    records = []
    for name, prefix, hand in scenes:
        records.append(dict(name=name, prefix=prefix, previews=hand["previews"],
                            maps=hand["maps"], reference=hand["reference"], assumptions=hand["assumptions"]))
    template = Path(__file__).resolve().parents[1] / "assets/preview.html"
    data = json.dumps(records, ensure_ascii=False).replace("<", r"\u003c")
    (folder / "模拟结果.html").write_text(template.read_text(encoding="utf-8").replace("__SCENES__", data),
                                      encoding="utf-8")
