#!/bin/bash
# render_views.sh <run-dir> [scale=4] [ready-expr] [WxH]   (WxH defaults to the frame of the run's final render)
# For a delivered run: writes fractal/scene/final-hires.png (reference camera at <scale>x) and
# fractal/scene/novel-views/view-{L35,R35,orbit,close1,close2}.png. The run's workspace root is <run-dir>/../..
# (the directory that holds runs/ and .render-tools/); pass RCWM_ROOT to override it.
set -uo pipefail
RUN="$(cd "${1:?usage: render_views.sh <run-dir> [scale] [ready-expr] [WxH]}" && pwd)"; SCALE="${2:-4}"; READY="${3:-}"; VP="${4:-}"
CODE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${RCWM_ROOT:-$(cd "$RUN/../.." && pwd)}"
NODE="$ROOT/.render-tools/node/bin/node"; [ -x "$NODE" ] || NODE=node
D="$RUN/fractal/scene"
[ -f "$D/part.json" ] || { echo "no delivered scene at $D/part.json"; exit 1; }
[ -f "$D/index.html" ] || { echo "no viewer page at $D/index.html (open the delivered program's own viewer instead)"; exit 1; }
REL="${RUN#$ROOT/}/fractal/scene/index.html"
# viewport = the frame of the delivered final render (fractal/scene/final.png; else the reference image), unless given
if [ -z "$VP" ]; then
  for f in "$D/outputs/final.png" "$D/final.png" "$D/FINAL.png" "$D/target.png"; do
    [ -f "$f" ] && { VP=$("$ROOT/.venv/bin/python" -c "from PIL import Image;w,h=Image.open('$f').size;print(f'{w}x{h}')" 2>/dev/null); [ -n "$VP" ] && break; }
  done
fi
OUT="$D/work/postprocess"; mkdir -p "$OUT"
echo "viewport: ${VP:-1400x963 (default)}"
echo "hi-res:  $OUT/final-hires.png"
"$NODE" "$CODE/tools/hires_render.mjs" "$ROOT" "$REL" "$OUT/final-hires.png" "$SCALE" "$READY" "$VP" || exit 1
echo "views:   $OUT/novel-views/"
"$NODE" "$CODE/tools/novel_views.mjs" "$ROOT" "$REL" "$OUT/novel-views" "$READY" "$VP"
