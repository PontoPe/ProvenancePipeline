# Recording a terminal demo

Written 2026-07-30, from recording `docs/img/demo.gif`. Meant to be reusable by
the sibling portfolio repos ([KateClusters](../../KateClusters),
[AwLZ](../../AwLZ), [PontoAntiCrack](../../PontoAntiCrack)) without rediscovering
any of it. `scripts/demo-record.sh` is this document as a runnable script.

Assumes you have never recorded a terminal before.

---

## 1. The short version

```bash
# on a Linux box — asciinema records a pty, so this is not a Windows job
sudo apt-get install -y asciinema fonts-dejavu-core
curl -fsSL -o ~/bin/agg https://github.com/asciinema/agg/releases/download/v1.9.0/agg-x86_64-unknown-linux-musl
chmod +x ~/bin/agg

# record — note there is NO --idle-time-limit here, on purpose
asciinema rec --overwrite --cols 104 --rows 46 \
  --title "what this demo shows" \
  --command "/path/to/demo.sh" \
  demo.cast

# render — all pacing decisions happen here, where they are reversible
agg --font-family "DejaVu Sans Mono" --font-size 15 --theme asciinema \
    --speed 0.6 --idle-time-limit 5 --last-frame-duration 6 \
    demo.cast demo.gif
```

Versions this was done with: `asciinema 2.4.0` (Debian 13 package), `agg 1.9.0`,
Debian 13 (trixie).

**Commit the `.cast` next to the `.gif`.** It is ~6 KB of plain JSON, it lets
anyone re-render without touching a cluster, and — see §7 — it is the only form
of the recording a reviewer can actually audit.

## 2. The one mistake to not repeat

I passed `--idle-time-limit 2` to `asciinema rec`. **Do not do that.**

That flag caps how long a pause is *stored in the cast file*. Any real wait
longer than 2 s was rounded down to 2 s and the information was gone
permanently. When I then found the first GIF was too fast, I could only stretch
what had survived — I could not restore the real 5-second wait while Kyverno
called out to the registry and Rekor, which is exactly the beat that makes the
demo feel like something is genuinely being checked.

Record raw. Cap idle at **render** time with `agg --idle-time-limit`, which is a
decision you can change as many times as you like from the same cast.

The committed `docs/img/demo.cast` was re-recorded without the flag, and the
difference is measurable from identical render settings:

| cast | per-frame durations (ms) | total |
|---|---|---|
| recorded with `--idle-time-limit 2` | `[2000, 110, 100, 170, 8330, 110, 1890, 3660, 150, 8340, 90, 6000]` | 31.0 s |
| recorded raw | `[2070, 100, 120, 210, 8330, 90, 1240, 7600, 160, 7370, 100, 6000]` | 33.4 s |

Look at frame 8: **3.66 s against 7.60 s**. That is the pause while Kyverno
verifies the Kyverno-signed image against Rekor before refusing it — the single
most interesting beat in the demo. The capped recording had thrown half of it
away before any render setting could get at it, and no amount of `--speed`
brings it back, because `--speed` stretches every frame equally and would have
slowed the parts that are already long enough.

Confirm the header has no cap before you render:

```bash
head -1 demo.cast | python3 -c 'import json,sys; print(json.load(sys.stdin).get("idle_time_limit","absent — good"))'
```

## 3. Flags, and what each one is for

### `asciinema rec`

| Flag | Why |
|---|---|
| `--command "<script>"` | Runs one program instead of dropping into a shell. **This is also the privacy control** — with no interactive shell there is no `PS1`, so `user@hostname:~/path$` never appears anywhere in the recording. See §7. |
| `--overwrite` | Re-recording is normal. Without it, the second attempt refuses to start. |
| `--cols` / `--rows` | Fixes the terminal geometry, so the output does not depend on whatever window happened to be open. |
| `--title` | Stored in the cast header. Free documentation. |
| `--idle-time-limit` | **Leave it off.** §2. |

Two operational traps:

- Run it over SSH with `ssh -tt`. asciinema needs a pty; a plain `ssh` gives it
  no terminal and it will not start.
- **Never put `sudo -v` inside the recorded command.** It hangs forever waiting
  for a password prompt that has nowhere to appear, and the recording never
  starts. This cost me one wedged 10-minute run. If the box needs sudo, make it
  NOPASSWD beforehand and check with `sudo -n true`.

### `agg`

| Flag | Why |
|---|---|
| `--font-family "DejaVu Sans Mono"` | Required. Without it: `Error: no faces matching font family options`. |
| `--font-size 15` | Readable at full width without making the file enormous. Main size lever. |
| `--theme asciinema` | Dark background, sane ANSI palette. |
| `--speed 0.6` | Slows everything to 1/0.6. The single most effective readability knob. |
| `--idle-time-limit 5` | Caps dead air at 5 s while leaving real pauses long enough to read. |
| `--last-frame-duration 6` | Holds the final frame. Without it the GIF loops instantly off the conclusion, which is the one frame people actually want to read. |

On a headless VM `agg` prints `[WARN fontdb] Fallback to loading from known font
dir paths.` even after `fonts-dejavu-core` is installed and even when it renders
correctly. **The cause is that fontconfig is not installed** — a minimal server
image ships the font *files* without `fc-list`, so agg's font database cannot
query fontconfig and scans `/usr/share/fonts` directly instead. Harmless, and
expected on that kind of box.

The practical consequence is a trap: **do not test for the font with `fc-list`.**
On this VM `fc-list` does not exist at all, so a `fc-list | grep` check reports
"font missing" for a font that is installed and working. Check for the file
instead — `/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf`. `scripts/demo-record.sh`
tries `fc-list` first and falls back to a filename search, because the family
name `DejaVu Sans Mono` is `DejaVuSansMono.ttf` on disk.

## 4. Geometry, theme, font — and what was wrong first

**104 cols × 46 rows.** Both are compromises and one of them I got wrong.

- 104 cols was chosen to fit lines like
  `ghcr.io/pontope/provenancepipeline@sha256:5d4b03ea…` on one line. **It does
  not.** A registry reference with a full 64-character digest is ~110–120
  characters before any indentation, and Kyverno's denial messages indent them
  further. They still wrap. I could have gone to ~130 cols, but then the font
  has to shrink to keep the image a sane width, and the text stops being
  readable in a GitHub README at typical widths. There is no setting that wins
  here — either the digest wraps or the type is small.
  - The alternative I did not take: print truncated digests in the demo script.
    Rejected, because in a supply-chain demo the digest *is* the evidence and
    abbreviating it invites "which image was that, really".
- 46 rows was picked to hold the whole run without scrolling. It nearly does.
  The final frames scroll slightly.

**Theme.** `asciinema` (the built-in). Tried nothing else — it was legible on
the first attempt, so this is not a considered choice, just one that worked.

**Font.** DejaVu Sans Mono, chosen because `fonts-dejavu-core` is one apt
package on Debian and monospace rendering is what matters. No comparison against
JetBrains Mono or Fira Code was done. If you already have a font you like,
install it and pass `--font-family`; nothing here depends on DejaVu.

## 5. Pacing

The finished GIF is 33.4 s over 12 frames. **A "frame" in `agg` is one screen
update, not a fixed tick** — 12 frames does not mean 12 fps, it means the script
produced 12 distinct bursts of output. So per-frame duration is the thing to
inspect, never the frame count:

```bash
python3 -c "
from PIL import Image
im = Image.open('demo.gif')
d = []
for i in range(im.n_frames):
    im.seek(i); d.append(im.info.get('duration'))
print('frames', im.n_frames, 'total_s', sum(d)/1000.0)
print(d)
"
```

First render, before tuning:

```
frames 12 total_s 10.28
[1200, 70, 60, 100, 1500, 60, 1140, 1500, 90, 1500, 60, 3000]
```

10 seconds, with 60–100 ms frames. Unreadable — whole denial messages flashed
past. After `--speed 0.6 --idle-time-limit 5 --last-frame-duration 6`, on the
raw re-recording:

```
frames 12 total_s 33.4
[2070, 100, 120, 210, 8330, 90, 1240, 7600, 160, 7370, 100, 6000]
```

The 7–8 s frames are where a denial message sits on screen, the 6 s is the
final state, and the 90–210 ms ones are text scrolling past. That is the shape
to aim for: **long holds on the frames that carry the point, short ones on
scrolling.**

Rough rule: a frame the viewer must *read* needs ~1 s per two lines of text. A
frame that is just output scrolling past can be 100 ms.

### Where I used `sleep`, and where I did not

Exactly one, in `scripts/demo.sh`:

```bash
try signed "$SIGNED"
sleep 6            # let the pod actually reach Running before showing it
run "kubectl get pod signed -n $NS -o wide"
```

Six seconds because the pod has to be scheduled, the image pulled, and the
process started, and showing `ContainerCreating` would undercut the point. I
picked 6 by trying it; 3 was sometimes too short. A poll loop
(`kubectl wait --for=condition=Ready`) would be more robust and is what I would
use next time — `sleep` is a guess that fails on a slow day.

**I added no sleeps anywhere else, deliberately.** Every other pause in the
recording is real work: see §6.

## 6. Real latency is the asset, not the problem

The instinct is to hide waiting. Here it was the opposite.

Each denied pod takes a genuine 1–3 s, because Kyverno resolves the image,
fetches the Sigstore bundle over the network, and verifies it against the
transparency log before answering. That pause is *the demo*. Cutting it to zero
would make admission look like a local string comparison rather than a
cryptographic check against a remote log.

So: **do not pad, and do not compress.** Let real latency be the pacing, cap
only genuinely dead air with `agg --idle-time-limit`, and add `sleep` solely
where you are waiting for an asynchronous state you are about to display.

The one thing worth cutting is startup cost that is not part of the story — a
first-ever image pull, a TUF root refresh on Kyverno's first verification. Do
one warm-up run before recording so the demo shows steady-state timing rather
than cold-start timing. I did this by accident (I had run the script several
times while debugging); do it on purpose.

## 7. Not leaking anything — and how a reviewer checks

**The `.cast` file is plain-text JSON. That is the whole trick.** A GIF cannot be
grepped; a cast can. This is the main reason to commit both.

Two structural choices do most of the work:

1. **`--command` instead of an interactive shell.** No shell means no prompt,
   and the prompt is what normally leaks `user@hostname`, the working directory,
   and often a kube-context or cloud-profile name from a fancy `PS1`.
2. **asciinema 2.x records only `SHELL` and `TERM` into the header `env`.** Not
   the whole environment. Verify rather than trust — see below.

What actually ended up in this recording, audited rather than assumed:

```console
$ grep -c "192\.168\.100" demo.cast                     # host / LAN address
0
$ grep -ciE "BEGIN (RSA |EC )?PRIVATE KEY|client-certificate-data|token:" demo.cast
0
$ grep -oE "pedro@[a-z0-9-]+" demo.cast                 # user@host from a prompt
(no output)
$ grep -o "kubeconfig=[^ ]*" demo.cast | sort -u
kubeconfig=/etc/kubernetes/admin.conf                   # a path, not its contents
$ grep -o "kate-node-01" demo.cast | head -1
kate-node-01                                            # node name, from -o wide
$ grep -oE "10\.244\.[0-9]+\.[0-9]+" demo.cast | sort -u
10.244.220.160                                          # pod IP, RFC1918, ephemeral
$ head -1 demo.cast | python3 -m json.tool | head -12   # header env
"env": { "SHELL": "/bin/bash", "TERM": "xterm-256color" }
```

Two things do appear and were judged acceptable: the node's hostname
`kate-node-01` and one ephemeral RFC1918 pod IP, both from `kubectl get -o wide`.
Neither is a credential and neither is reachable from outside the LAN. If your
demo runs on cloud infrastructure that calculus changes — an AWS account ID, an
EKS cluster ARN, or a public node IP are all things to scrub, and `-o wide` is
the usual way they get in.

**Checklist before committing a recording:**

- [ ] Grep the cast for: your public IP, internal hostnames, account IDs
      (`\b[0-9]{12}\b` for AWS), ARNs, bearer tokens, `BEGIN.*PRIVATE KEY`,
      `client-certificate-data`, `password`, `secret`, `Bearer `.
- [ ] Check the header `env` — `head -1 demo.cast | python3 -m json.tool`.
- [ ] Confirm no shell prompt appears at all (that means `--command` worked).
- [ ] Watch the GIF once, at full size. A cast grep will not catch something
      rendered only as pixels, e.g. a token displayed inside a TUI.
- [ ] Prefer `kubectl get pods` over `-o wide` unless the node column is
      actually part of the point.

`scripts/demo-record.sh` runs the greps automatically and refuses to finish if
it matches anything, so this is a gate rather than a good intention.

## 8. File size, and the trade

**495 KB**, 957 × 987 px, 12 frames, 33.4 s. That is comfortably inside GitHub's
limits and renders inline in a README without anyone waiting. Note that adding
2.4 s of pause cost about 1 KB — holding a frame longer changes one duration
field, it does not add pixels. **Pacing is nearly free; resolution is not.**

What drives GIF size, in order: pixel area × number of frames × how much changes
between frames. Terminal recordings are cheap on the third factor, which is why
a 31-second GIF is under half a megabyte — most of the screen is a flat
background that compresses away.

I did not have to trade anything to hit 494 KB; it landed there. Had it been too
big, in the order I would have reached for them:

1. `--font-size` 15 → 13. Area scales roughly quadratically, so this is the
   biggest lever by far.
2. Fewer `--rows`. Same effect, and forces a tighter script.
3. Split into two GIFs, admit and deny.
4. `--speed` up. **Last resort** — it buys little and costs the readability that
   §5 was spent earning.

Do not reach for a lower frame rate. `agg` emits a frame per screen update, not
on a clock, so there is no fps to lower.

## 9. What I would do differently

1. ~~**Record without `--idle-time-limit`.**~~ Done — the committed cast is raw,
   and §2 has the before/after. Kept at the top of this list because it is the
   thing most likely to be got wrong again in another repo, and because it is
   unrecoverable after the fact.
2. **`kubectl wait` instead of `sleep 6`.** Deterministic, and it self-adjusts on
   a slow machine instead of showing `ContainerCreating`.
3. **`clear` between sections.** The demo scrolls, so late frames are a wall of
   mixed text and the reader has to find the new part. Clearing before each case
   would make every frame self-contained and let each hold be shorter — probably
   a shorter *and* more readable GIF.
4. **Decide the digest question up front.** Either widen to ~130 cols and accept
   small type, or design the script so long references appear on their own line
   where wrapping is harmless. Discovering this at render time is too late.
5. **A warm-up run on purpose**, so the first case is not slower than the rest.
6. **Test one frame early.** Extract frame 5 to PNG and look at it after the
   first render, before tuning anything. I tuned pacing before confirming the
   text even rendered, which would have been wasted work had the font been wrong.

## 10. Colour

`scripts/demo.sh` uses four, applied by meaning rather than decoration:

```bash
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; D=$'\033[2m'; Z=$'\033[0m'
else B=""; G=""; R=""; D=""; Z=""; fi
```

The `[ -t 1 ]` guard matters for a second reason: the same script generates
`docs/evidence/admission-enforcement.md`, and without the guard that file would
fill with escape sequences. Under asciinema stdout *is* a tty, so the recording
gets colour and the evidence file does not, from one script.

- **Bold** for commands — separates "what was typed" from "what came back". The
  single most useful one.
- **Dim** for `#` narration — makes it read as commentary, not output.
- **Green** for an admitted pod, **red** for a denial.

Where colour helped: green/red is instantly legible and carries the entire story
at a glance, even to someone not reading the text.

Where it polluted: a Kyverno denial is 6–8 lines including the full image
reference and the policy path, and rendering all of it red is a large block of
saturated colour that dominates the frame and makes the actual reason
(`no matching signatures found`) no easier to find than the boilerplate around
it. Colouring only the *first* line of the error, or only the reason, would be
better. I would not colour whole multi-line error blocks again.

`kubectl`'s own output is left uncoloured, which turned out fine — it gives the
eye somewhere neutral to rest between the coloured blocks.

## 11. Reusing this in another repo

`scripts/demo-record.sh` was run end to end to produce the committed GIF, so it
is tested rather than illustrative. To use it elsewhere, copy it plus this
document and set two variables:

```bash
DEMO_SCRIPT=./scripts/demo.sh \
TITLE="what the demo shows" \
OUT_DIR=docs/img \
  ./scripts/demo-record.sh
```

Everything else is an environment variable with a default: `COLS`, `ROWS`,
`FONT_FAMILY`, `FONT_SIZE`, `THEME`, `SPEED`, `RENDER_IDLE_LIMIT`,
`LAST_FRAME_DURATION`, `NAME`, `AGG_VERSION`.

**The one thing to change per repo is `DENY_PATTERNS`.** The default covers
private keys, bearer tokens, JWTs, AWS access keys, 12-digit account IDs and
ARNs. Add what is sensitive in *your* context — for a cloud repo that is
probably real resource names and public IPs; for a cluster repo, the LAN prefix.
A leak audit that never fires is not evidence of a clean recording, it is
evidence of a weak pattern list, so test it deliberately: add a pattern you know
matches, confirm the script exits non-zero and writes nothing to `OUT_DIR`, then
remove it.

The script is deliberately a gate, not a report. It refuses to promote anything
into `OUT_DIR` on a `DENY_PATTERNS` match. `WARN_PATTERNS` (IP addresses,
`kubeconfig`, `.internal`/`.local` hostnames) prints for a human to look at and
does not block — on this recording it prints `kubeconfig`, which is the
`--kubeconfig=/etc/kubernetes/admin.conf` **path** in the visible command line
and not its contents.

What it does **not** do, and no script can: read pixels. A token rendered inside
a TUI, or anything drawn by a program that redraws the screen, exists only in
the GIF. Watch the recording once at full size before committing. The script
writes `<name>-frame.png` from the middle of the animation as a cheap first
look — check that the font rendered and the colours are right before you spend
time tuning pacing, which is the order I did it in the wrong way round.
