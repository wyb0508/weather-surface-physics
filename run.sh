#!/bin/sh
set -eu
skill_dir=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
mode=placement
case "${1:-}" in
    placement|simulate|batch|pack_masks) mode=$1; shift ;;
    *)
        for option in "$@"; do
            case "$option" in --review|--old-snow|--temperature|--answers) mode=simulate; break ;; esac
        done ;;
esac
for python in "$skill_dir/.venv/bin/python" "$skill_dir/../../.venv/bin/python" python3; do
    if "$python" -c 'import cv2, numpy, PIL, onnxruntime, pillow_heif' 2>/dev/null; then
        exec "$python" "$skill_dir/scripts/$mode.py" "$@" </dev/null
    fi
done
echo "请使用 Python 3.10–3.13 在技能目录创建 .venv，并安装 requirements.txt 中的依赖。见 SKILL.md。" >&2
exit 1
