#!/bin/sh
# Jobissimo installer — macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/iliasedelkin/jobissimo/main/install.sh | sh
#
# What it does, and nothing else:
#   1. checks for Python 3.9+
#   2. puts the engine in ~/Jobissimo/engine (git clone, or a tarball without git)
#   3. makes your private workspace, ~/Jobissimo/workspace, and points the engine at it
#   4. adds a Jobissimo app (macOS: ~/Applications; Linux: your app menu)
#   5. opens it — the page walks you through the rest (agent, tools, documents, setup)
#
# It installs no other software and needs no sudo. Running it again updates the
# engine and leaves your workspace alone.
#
# Options: --no-open (don't open the page), --no-app (don't add the app).
# Environment: JOBISSIMO_DIR (default ~/Jobissimo), JOBISSIMO_WORKSPACE
# (default $JOBISSIMO_DIR/workspace), JOBISSIMO_REPO, JOBISSIMO_BRANCH.
# JOBISSIMO_SOURCE_DIR copies a local checkout instead of downloading (development).
set -eu

REPO_URL="${JOBISSIMO_REPO:-https://github.com/iliasedelkin/jobissimo.git}"
BRANCH="${JOBISSIMO_BRANCH:-main}"
ROOT="${JOBISSIMO_DIR:-$HOME/Jobissimo}"
ENGINE="$ROOT/engine"
WORKSPACE="${JOBISSIMO_WORKSPACE:-$ROOT/workspace}"
OPEN=1
APP=1

say() { printf '%s\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

for arg in "$@"; do
  case "$arg" in
    --no-open) OPEN=0 ;;
    --no-app) APP=0 ;;
    -h|--help) sed -n '2,22p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $arg (try --help)" ;;
  esac
done

case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux) OS=linux ;;
  *) die "Jobissimo installs on macOS and Linux. On Windows, run this inside WSL." ;;
esac

# ---------------------------------------------------------------- 1. Python
step "Checking Python"
PY="$(command -v python3 || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
  if [ "$OS" = mac ]; then
    die "Python 3.9 or newer is needed. Install Apple's command-line tools (a dialog may already be open, or run: xcode-select --install), then run this installer again."
  fi
  die "Python 3.9 or newer is needed: sudo apt install python3 (or your distribution's equivalent), then run this installer again."
fi
say "$("$PY" --version) at $PY"

# ---------------------------------------------------------------- 2. engine
step "Getting the engine → $ENGINE"
mkdir -p "$ROOT"
if [ -n "${JOBISSIMO_SOURCE_DIR:-}" ]; then
  mkdir -p "$ENGINE"
  (cd "$JOBISSIMO_SOURCE_DIR" && tar -cf - --exclude ./.git --exclude ./profile --exclude ./.jobissimo \
     --exclude ./.claude/settings.local.json --exclude '*.pyc' --exclude __pycache__ .) | (cd "$ENGINE" && tar -xf -)
  say "Copied from $JOBISSIMO_SOURCE_DIR."
elif [ -d "$ENGINE/.git" ]; then
  if git -C "$ENGINE" pull --ff-only --quiet; then
    say "Updated to $(git -C "$ENGINE" log -1 --format='%h %s')."
  else
    say "Could not fast-forward (local changes?). Keeping the engine as it is."
  fi
elif command -v git >/dev/null 2>&1 && [ ! -e "$ENGINE" ]; then
  git clone --quiet --depth 1 --branch "$BRANCH" "$REPO_URL" "$ENGINE"
  say "Cloned $REPO_URL ($BRANCH)."
else
  command -v curl >/dev/null 2>&1 || die "Need git or curl to download the engine."
  TARBALL="$(printf '%s' "$REPO_URL" | sed 's/\.git$//')/archive/refs/heads/$BRANCH.tar.gz"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "$TARBALL" | tar -xzf - -C "$TMP"
  mkdir -p "$ENGINE"
  cp -R "$TMP"/*/. "$ENGINE"/
  say "Downloaded $TARBALL."
fi
[ -f "$ENGINE/scripts/ui.py" ] || die "The engine at $ENGINE looks incomplete (no scripts/ui.py)."

# ---------------------------------------------------------------- 3. workspace
step "Your private workspace → $WORKSPACE"
if [ -f "$ENGINE/.jobissimo" ]; then
  CURRENT="$(head -n 1 "$ENGINE/.jobissimo")"
  if [ "$CURRENT" != "$WORKSPACE" ]; then
    say "The engine already points at $CURRENT — keeping that."
    WORKSPACE="$CURRENT"
  fi
fi
mkdir -p "$WORKSPACE"
printf '%s\n' "$WORKSPACE" > "$ENGINE/.jobissimo"
if [ ! -d "$WORKSPACE/.git" ] && command -v git >/dev/null 2>&1; then
  [ -f "$WORKSPACE/.gitignore" ] || cp "$ENGINE/templates/workspace.gitignore" "$WORKSPACE/.gitignore"
  git -C "$WORKSPACE" init --quiet
  say "Made it a git repository of its own, so /sync can back it up to a private remote later."
fi
say "Your career data lives here, never in the engine folder."

# ---------------------------------------------------------------- what's on this machine
step "Looking around"
found_agent=0
for a in claude codex; do
  for d in "" /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin" "$HOME/.npm-global/bin"; do
    if { [ -z "$d" ] && command -v "$a" >/dev/null 2>&1; } || { [ -n "$d" ] && [ -x "$d/$a" ]; }; then
      say "Found $a."
      found_agent=1
      break
    fi
  done
done
if [ "$found_agent" = 0 ]; then
  say "No agent yet. Jobissimo's work is done by your own Claude Code (or Codex). Install one:"
  say "    curl -fsSL https://claude.ai/install.sh | bash     # then run: claude   (sign in once)"
fi
command -v pandoc >/dev/null 2>&1 && say "Found pandoc." || say "No pandoc yet — the page offers to install it (needed to export Word files)."

# ---------------------------------------------------------------- 4. app
if [ "$APP" = 1 ]; then
  step "Adding the Jobissimo app"
  "$PY" "$ENGINE/scripts/launcher.py" install-app
fi

# ---------------------------------------------------------------- 5. open
if [ "$OPEN" = 1 ]; then
  if [ "$OS" = linux ] && [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    say ""
    say "No display found, so not opening a browser. Start it with:"
    say "    $PY $ENGINE/scripts/launcher.py open --no-browser"
  else
    step "Opening Jobissimo"
    "$PY" "$ENGINE/scripts/launcher.py" open
  fi
fi

step "Done"
if [ "$APP" = 1 ]; then
  if [ "$OS" = mac ]; then
    say "Open Jobissimo any time from ~/Applications (drag it to the Dock to keep it handy)."
  else
    say "Open Jobissimo any time from your app menu."
  fi
fi
say "Or: $PY $ENGINE/scripts/launcher.py open"
say "Update later by running this installer again."
