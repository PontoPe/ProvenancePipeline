#!/usr/bin/env bash
#
# Record a terminal demo to a GIF, and refuse to hand it over if it leaks.
#
# Portable across the portfolio repos on purpose — everything is an environment
# variable and nothing below mentions this project. To reuse it elsewhere, copy
# this file and set DEMO_SCRIPT and TITLE. The reasoning behind every default is
# in docs/demo-recording.md; this is that document made executable.
#
#   DEMO_SCRIPT=./scripts/demo.sh \
#   TITLE="a cluster refusing an unsigned image" \
#   OUT_DIR=docs/img \
#     ./scripts/demo-record.sh
#
# Stages: deps -> record -> render -> inspect -> leak audit. The audit is a gate:
# a match means a non-zero exit and no artifact promoted to OUT_DIR.
#
# Must run on Linux or WSL. asciinema records a pty; there is no Windows build.
set -euo pipefail

# --- what to record ---------------------------------------------------------
DEMO_SCRIPT="${DEMO_SCRIPT:?set DEMO_SCRIPT to the script you want recorded}"
TITLE="${TITLE:-terminal demo}"
OUT_DIR="${OUT_DIR:-docs/img}"
NAME="${NAME:-demo}"

# --- geometry ---------------------------------------------------------------
# COLS: wide enough for your longest line, or accept wrapping. A container
# reference with a full sha256 digest is ~110-120 chars before indentation, so
# 104 does NOT fit one — raising it means shrinking the font to keep the image
# embeddable. There is no value that wins; pick which compromise you prefer.
# ROWS: tall enough that the run does not scroll, if you can manage it.
COLS="${COLS:-104}"
ROWS="${ROWS:-46}"

# --- rendering --------------------------------------------------------------
FONT_FAMILY="${FONT_FAMILY:-DejaVu Sans Mono}"   # agg errors out without this
FONT_SIZE="${FONT_SIZE:-15}"                     # main file-size lever
THEME="${THEME:-asciinema}"
SPEED="${SPEED:-0.6}"                            # <1 slows down; best readability knob
RENDER_IDLE_LIMIT="${RENDER_IDLE_LIMIT:-5}"      # cap dead air at RENDER time only
LAST_FRAME_DURATION="${LAST_FRAME_DURATION:-6}"  # hold the conclusion, or it loops off it

AGG_VERSION="${AGG_VERSION:-v1.9.0}"

# --- leak audit -------------------------------------------------------------
# Patterns that must NOT appear in the recording. Extend per repo — an AWS repo
# wants account IDs and ARNs, a cluster repo wants its LAN prefix. Case-insensitive
# ERE, matched against the .cast, which is plain JSON and therefore greppable.
# This is why the .cast is worth committing: a GIF cannot be audited.
DENY_PATTERNS="${DENY_PATTERNS:-BEGIN( RSA| EC)? PRIVATE KEY|client-certificate-data|client-key-data|BEGIN CERTIFICATE|Bearer [A-Za-z0-9._-]{16,}|password[[:space:]=:]|passwd[[:space:]=:]|secret[_-]?(key|access)|aws_secret_access_key|AKIA[0-9A-Z]{16}|[^0-9][0-9]{12}[^0-9]|arn:aws[a-z-]*:|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{20,}[.][A-Za-z0-9_-]{20,}}"

# Patterns that are allowed but should be looked at by a human before committing.
WARN_PATTERNS="${WARN_PATTERNS:-([0-9]{1,3}\.){3}[0-9]{1,3}|kubeconfig|[A-Za-z0-9-]+\.(internal|local|lan)}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31m!! %s\033[0m\n' "$*" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
CAST="$WORK/$NAME.cast"
GIF="$WORK/$NAME.gif"

# --------------------------------------------------------------------------
say "checking dependencies"

command -v asciinema >/dev/null || die "asciinema not installed. Debian/Ubuntu: sudo apt-get install -y asciinema"

if ! command -v agg >/dev/null; then
  say "agg not found, installing $AGG_VERSION to ~/bin"
  mkdir -p "$HOME/bin"
  curl -fsSL -o "$HOME/bin/agg" \
    "https://github.com/asciinema/agg/releases/download/$AGG_VERSION/agg-x86_64-unknown-linux-musl"
  chmod +x "$HOME/bin/agg"
  export PATH="$HOME/bin:$PATH"
fi

# agg fails with "no faces matching font family options" if no font is installed.
#
# Do not check with fc-list alone. A headless server often has the font files but
# not fontconfig, and then fc-list is simply absent — which is also the reason agg
# prints "[WARN fontdb] Fallback to loading from known font dir paths": it tries
# fontconfig, finds none, and scans /usr/share/fonts directly. That warning is
# harmless and expected on such a box; rendering still works.
font_present() {
  if command -v fc-list >/dev/null 2>&1; then
    fc-list 2>/dev/null | grep -qi "$1" && return 0
  fi
  # Fall back to filenames: "DejaVu Sans Mono" -> DejaVuSansMono.ttf
  local compact="${1// /}"
  find /usr/share/fonts /usr/local/share/fonts "$HOME/.local/share/fonts" "$HOME/.fonts" \
       -iname "*${compact}*" -print -quit 2>/dev/null | grep -q .
}
if ! font_present "$FONT_FAMILY"; then
  die "font '$FONT_FAMILY' not found. Debian/Ubuntu: sudo apt-get install -y fonts-dejavu-core"
fi

# A password prompt inside a recorded command hangs forever with nowhere to
# appear, and the recording never starts. Fail here instead, with a reason.
if ! sudo -n true 2>/dev/null; then
  echo "   note: passwordless sudo is unavailable."
  echo "   If '$DEMO_SCRIPT' uses sudo, this WILL hang. Never put 'sudo -v' in a recorded command."
fi

[ -x "$DEMO_SCRIPT" ] || die "$DEMO_SCRIPT is not executable"

# --------------------------------------------------------------------------
say "warm-up run (discarded)"
# Cold starts — a first image pull, a TUF root refresh, an empty DNS cache —
# make the first step of a demo several seconds slower than the rest, which
# reads as the demo being broken. Burn that cost here so the recording shows
# steady-state timing. Failure is tolerated: some demos are not idempotent.
"$DEMO_SCRIPT" >/dev/null 2>&1 || echo "   warm-up returned non-zero, continuing"

# --------------------------------------------------------------------------
say "recording"
# --command, not an interactive shell: no shell means no PS1, and PS1 is what
# normally leaks user@hostname, the cwd, and any kube-context or cloud profile
# a themed prompt displays. This is a privacy control, not a convenience.
#
# NOTE the absence of --idle-time-limit. That flag caps pauses *in the stored
# cast*, destroying the real timings permanently. Pacing belongs at render time
# where it stays reversible. This is the single biggest lesson from the first
# recording — see docs/demo-recording.md §2.
asciinema rec \
  --overwrite \
  --cols "$COLS" \
  --rows "$ROWS" \
  --title "$TITLE" \
  --command "$DEMO_SCRIPT" \
  "$CAST" </dev/null

[ -s "$CAST" ] || die "no cast produced"

# --------------------------------------------------------------------------
say "leak audit"
# Run against the cast BEFORE anything is promoted, so a leak never reaches a
# tracked file. Header first: asciinema 2.x should record only SHELL and TERM.
echo "--- cast header env ---"
head -1 "$CAST" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("env",{}),indent=1))' 2>/dev/null || true

if grep -nEi "$DENY_PATTERNS" "$CAST" >"$WORK/hits.txt" 2>/dev/null; then
  echo "--- matches ---"; head -20 "$WORK/hits.txt"
  die "recording matched a forbidden pattern. Nothing was written to $OUT_DIR."
fi
echo "   no forbidden patterns"

if grep -oEi "$WARN_PATTERNS" "$CAST" 2>/dev/null | sort -u >"$WORK/warn.txt" && [ -s "$WORK/warn.txt" ]; then
  echo "   review these before committing (allowed, but look):"
  sed 's/^/     /' "$WORK/warn.txt" | head -20
fi

# A prompt in the output means --command did not take effect.
if grep -qE '\$ $|@[a-z0-9-]+:~' "$CAST"; then
  echo "   WARNING: something that looks like a shell prompt is present."
fi

# --------------------------------------------------------------------------
say "rendering"
agg --font-family "$FONT_FAMILY" \
    --font-size "$FONT_SIZE" \
    --theme "$THEME" \
    --speed "$SPEED" \
    --idle-time-limit "$RENDER_IDLE_LIMIT" \
    --last-frame-duration "$LAST_FRAME_DURATION" \
    "$CAST" "$GIF"

# --------------------------------------------------------------------------
say "inspecting the result"
# Frame COUNT is meaningless — agg emits one frame per screen update, not on a
# clock. Per-frame DURATION is the thing to judge. Frames a viewer has to read
# want roughly a second per two lines; frames that are just scrolling can be
# ~100ms. If total_s is small and the list is full of 60-90ms entries, the GIF
# is unreadable no matter how good the content is.
python3 - "$GIF" <<'PY' || echo "   (install python3-pil for frame timing detail)"
import sys
try:
    from PIL import Image
except ImportError:
    raise SystemExit(1)
im = Image.open(sys.argv[1])
d = []
for i in range(im.n_frames):
    im.seek(i); d.append(im.info.get("duration"))
print("   size      : %dx%d" % im.size)
print("   frames    : %d" % im.n_frames)
print("   duration  : %.1f s" % (sum(x or 0 for x in d)/1000.0))
print("   per-frame : %s" % d)
short = sum(1 for x in d if (x or 0) < 200)
if short > im.n_frames / 2:
    print("   WARNING: most frames are under 200ms. Lower --speed.")
# Extract a middle frame so the font and colours can be checked as pixels, not
# assumed. A cast grep cannot tell you the render came out blank.
im.seek(min(len(d)-1, len(d)//2 + 3))
im.convert("RGB").save(sys.argv[1].replace(".gif", "-frame.png"))
print("   sample frame written next to the gif — open it before committing")
PY

echo "   bytes     : $(stat -c%s "$GIF")"

# --------------------------------------------------------------------------
mkdir -p "$OUT_DIR"
cp "$GIF" "$OUT_DIR/$NAME.gif"
cp "$CAST" "$OUT_DIR/$NAME.cast"
[ -f "${GIF%.gif}-frame.png" ] && cp "${GIF%.gif}-frame.png" "$OUT_DIR/$NAME-frame.png"

say "done"
echo "   $OUT_DIR/$NAME.gif"
echo "   $OUT_DIR/$NAME.cast   <- commit this too; it is the auditable form"
echo "   $OUT_DIR/$NAME-frame.png  <- sample frame, delete once checked"
echo
echo "Before committing: watch the GIF once at full size. The audit above reads"
echo "the cast as text and cannot see anything that exists only as pixels."
