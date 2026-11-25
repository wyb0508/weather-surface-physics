"""Run every scene-regions manifest in an archive or directory without prompts."""
import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from placement import ALIASES, RULES, build, weather_list
from preview import write_preview

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp"}


def unpack(source, dest):
    if source.is_dir():
        return source
    dest.mkdir()
    with zipfile.ZipFile(source) as archive:
        seen = set()
        for item in archive.infolist():
            name = Path(item.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("压缩包包含无效路径。")
            if "__MACOSX" in name.parts or name.name.startswith("._") or item.is_dir():
                continue
            if name in seen:
                raise ValueError(f"压缩包含重名文件：{name}")
            seen.add(name)
            archive.extract(item, dest)
    return dest


def file_digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def match_photo(manifest, files, cache):
    # Matching names come first; renamed files and same-name collisions use the bytes.
    for path in sorted(files, key=lambda p: p.name != manifest["source"]):
        if path not in cache:
            cache[path] = file_digest(path)
        if cache[path] == manifest["sha256"]:
            return path
    raise ValueError(f"未找到指纹匹配的原图：{manifest['source']}")


def run(args, tmp):
    source = unpack(args.pack.resolve(), tmp / "input")
    manifests = sorted(p for p in source.rglob("manifest.json") if "__MACOSX" not in p.parts)
    if not manifests:
        raise ValueError("未找到分区清单 manifest.json。")
    photos = sorted(p for p in args.photos.rglob("*") if p.suffix.lower() in PHOTO_SUFFIXES and p.is_file())
    package = tmp / "package"
    package.mkdir()
    cache, scenes, index = {}, [], []
    for n, path in enumerate(manifests, 1):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        photo = match_photo(manifest, photos, cache)
        review = args.reviews / (file_digest(path) + ".json") if args.reviews else None
        subdir = f"{n:02d}"
        folder = package / subdir
        folder.mkdir()
        output = build(photo, path, folder, weather_list(args.weather),
                       patches=review if review and review.is_file() else None)
        title = path.parent.name if path.parent != source else photo.stem
        scenes.append((title, subdir, output))
        index.append(dict(name=title, input_manifest=path.relative_to(source).as_posix(),
                          image_sha256=manifest["sha256"], manifest_sha256=output["manifest_sha256"],
                          handoff=subdir + "/handoff.json"))
    write_preview(package, scenes)
    (package / "index.json").write_text(json.dumps(dict(scenes=index), ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    package.rename(args.out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--photos", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, help="按清单 SHA-256 命名的空间修订 JSON 所在目录")
    parser.add_argument("--weather", nargs="+", choices=[*RULES, *ALIASES, "结冰"], default=list(RULES))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise ValueError("请选择新的输出目录。")
        if not args.photos.is_dir() or (args.reviews and not args.reviews.is_dir()):
            raise ValueError("原图或修订目录不存在。")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as tmp:
            run(args, Path(tmp))
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        parser.exit(2, f"批量位置交接失败：{exc}\n")
    print(args.out / "index.json")


if __name__ == "__main__":
    main()
