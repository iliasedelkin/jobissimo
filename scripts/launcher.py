#!/usr/bin/env python3
"""launcher.py — open the local UI without a terminal.

    python3 scripts/launcher.py open           # start the UI if it isn't running, open it
    python3 scripts/launcher.py status         # JSON: running? app installed? starts at login?
    python3 scripts/launcher.py stop           # stop the running UI (and its agent runs)
    python3 scripts/launcher.py install-app    # macOS: ~/Applications/Jobissimo.app
                                               # Linux: an app-menu entry (.desktop)
    python3 scripts/launcher.py uninstall-app
    python3 scripts/launcher.py login on|off   # start the UI quietly when you log in

`open` is what the app runs. It reuses a UI already serving this workspace
(read from `config/local/ui_server.json` in the workspace, which ui.py writes
for its lifetime — owner-only, git-ignored with the rest of `config/local/`), or starts one in
the background that stops by itself after 30 idle minutes, then opens the
browser already signed in.

The app is generated on this machine, so it was never downloaded and macOS
does not quarantine it. It bakes in the Python and PATH of the shell that
installed it, and JOBISSIMO_HOME / JOBISSIMO_CONFIG if that shell set them
(a scratch copy); otherwise the engine's `.jobissimo` pointer finds the
workspace. Re-run `install-app` after moving any of them.

Deliberately on neither agent allowlist: an agent never starts the UI.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
APP_NAME = "Jobissimo"
BUNDLE_ID = "io.github.jobissimo.launcher"
AGENT_LABEL = "io.github.jobissimo.ui"
DEFAULT_PORT = 8765
IDLE_MINUTES = 30


class LaunchError(RuntimeError):
    pass


def system() -> str:
    """'mac' | 'linux' | 'other' — $JOBISSIMO_LAUNCHER_OS overrides (tests)."""
    forced = os.environ.get("JOBISSIMO_LAUNCHER_OS")
    if forced:
        return forced
    s = platform.system()
    return "mac" if s == "Darwin" else "linux" if s == "Linux" else "other"


# ---------------------------------------------------------------- the running server

def state_path() -> Path:
    return paths.local_dir() / "ui_server.json"


def write_state(port: int, token: str) -> None:
    """Called by ui.py when it starts serving. Owner-only: it holds the token."""
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "port": port, "token": token, "workspace": str(paths.home()),
                   "started_at": int(time.time())}, fh)
    os.chmod(p, 0o600)


def clear_state() -> None:
    try:
        st = read_state()
        if st and st.get("pid") == os.getpid():
            state_path().unlink()
    except OSError:
        pass


def read_state() -> dict | None:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def _healthy(port: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health",
                                     headers={"Host": f"127.0.0.1:{port}"})
        with urllib.request.urlopen(req, timeout=2) as res:
            return json.loads(res.read()).get("app") == "jobissimo"
    except (OSError, ValueError):
        return False


def running() -> dict | None:
    st = read_state()
    if st and _alive(st.get("pid")) and _healthy(st.get("port")):
        return st
    return None


def url_for(st: dict) -> str:
    return f"http://127.0.0.1:{st['port']}/?t={st['token']}"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def log_path() -> Path:
    return paths.local_dir() / "ui.log"


def start_background(idle_minutes: float = IDLE_MINUTES, timeout: float = 15) -> dict:
    """Start ui.py detached from this process; wait until it serves."""
    port = DEFAULT_PORT if _port_free(DEFAULT_PORT) else 0
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    before = read_state()
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} starting the UI\n")
        fh.flush()
        proc = subprocess.Popen([sys.executable, str(SCRIPTS / "ui.py"), "--no-open", "--port", str(port),
                                 "--idle-exit", str(idle_minutes)],
                                stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True, cwd=str(paths.REPO_ROOT))
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = read_state()
        if st and st != before and st.get("pid") == proc.pid and _healthy(st["port"]):
            return st
        if proc.poll() is not None:
            break
        time.sleep(0.15)
    raise LaunchError(f"The UI did not start — see {log}.")


def open_ui(browser: bool = True, idle_minutes: float = IDLE_MINUTES) -> dict:
    st = running() or start_background(idle_minutes)
    if browser:
        _open_url(url_for(st))
    return st


def _open_url(url: str) -> None:
    # `open` / `xdg-open` focus an existing browser window; webbrowser is the fallback
    opener = {"mac": "open", "linux": "xdg-open"}.get(system())
    if opener and shutil.which(opener):
        if subprocess.run([opener, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            return
    webbrowser.open(url)


def stop_ui(timeout: float = 10) -> bool:
    st = running()
    if not st:
        return False
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{st['port']}/api/quit-local", method="POST",
                                     headers={"Host": f"127.0.0.1:{st['port']}",
                                              "X-Jobissimo-Token": st["token"]}, data=b"{}")
        urllib.request.urlopen(req, timeout=5).read()
    except OSError:
        pass
    deadline = time.time() + timeout
    while time.time() < deadline and _alive(st["pid"]):
        time.sleep(0.15)
    if _alive(st["pid"]):
        os.kill(st["pid"], 15)
    return True


# ---------------------------------------------------------------- the app

def apps_dir() -> Path:
    override = os.environ.get("JOBISSIMO_APPS_DIR")
    if override:
        return Path(override)
    if system() == "mac":
        return Path.home() / "Applications"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"


def launcher_script(action: str = "open") -> str:
    """The shell stub every entry point runs: the installing shell's Python
    and PATH, and its JOBISSIMO_HOME / JOBISSIMO_CONFIG when they were set
    explicitly (otherwise the engine's .jobissimo pointer decides at run
    time, as for every other command), then launcher.py."""
    env = {k: os.environ[k] for k in ("JOBISSIMO_HOME", "JOBISSIMO_CONFIG") if os.environ.get(k)}
    lines = ["#!/bin/sh", "# Generated by scripts/launcher.py install-app — re-run it after moving things.",
             f"export PATH={shlex.quote(os.environ.get('PATH', ''))}:\"$PATH\""]
    lines += [f"export {k}={shlex.quote(v)}" for k, v in env.items()]
    lines += [f"PY={shlex.quote(sys.executable)}", '[ -x "$PY" ] || PY=python3',
              f'exec "$PY" {shlex.quote(str(SCRIPTS / "launcher.py"))} {action}']
    return "\n".join(lines) + "\n"


def app_path() -> Path:
    if system() == "mac":
        return apps_dir() / f"{APP_NAME}.app"
    return apps_dir() / "jobissimo.desktop"


def _write_exec(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _mac_icon(resources: Path) -> bool:
    """ui/icon.svg -> Jobissimo.icns with the tools macOS ships (best effort)."""
    svg = paths.REPO_ROOT / "ui" / "icon.svg"
    if not (svg.exists() and shutil.which("qlmanage") and shutil.which("sips") and shutil.which("iconutil")):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        r = subprocess.run(["qlmanage", "-t", "-s", "1024", "-o", str(t), str(svg)], capture_output=True)
        png = t / "icon.svg.png"
        if r.returncode != 0 or not png.exists():
            return False
        iconset = t / "Jobissimo.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(px), str(px), str(png), "--out", str(iconset / name)],
                               capture_output=True)
        r = subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(resources / "Jobissimo.icns")],
                           capture_output=True)
        return r.returncode == 0


def install_app() -> dict:
    target = app_path()
    if system() == "mac":
        if target.exists():
            shutil.rmtree(target)
        contents = target / "Contents"
        _write_exec(contents / "MacOS" / APP_NAME, launcher_script("open"))
        resources = contents / "Resources"
        resources.mkdir(parents=True, exist_ok=True)
        icon = _mac_icon(resources)
        info = {"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME, "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleExecutable": APP_NAME, "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
                "CFBundleShortVersionString": "1.0", "LSUIElement": True,
                "NSHumanReadableCopyright": "Runs locally. Your data stays on this machine."}
        if icon:
            info["CFBundleIconFile"] = "Jobissimo"
        with (contents / "Info.plist").open("wb") as fh:
            plistlib.dump(info, fh)
        return {"installed": str(target), "icon": icon, "workspace": str(paths.home())}
    if system() == "linux":
        stub = stub_path()
        _write_exec(stub, launcher_script("open"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join([
            "[Desktop Entry]", "Type=Application", f"Name={APP_NAME}",
            "Comment=Your job search, run by your own agent, on this machine",
            f"Exec={shlex.quote(str(stub))}", f"Icon={paths.REPO_ROOT / 'ui' / 'icon.svg'}",
            "Terminal=false", "Categories=Office;", "StartupNotify=false"]) + "\n", encoding="utf-8")
        target.chmod(0o755)
        if shutil.which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(target.parent)], capture_output=True)
        return {"installed": str(target), "icon": True, "workspace": str(paths.home())}
    raise LaunchError("The app launcher is for macOS and Linux; run `python3 scripts/ui.py` instead.")


def stub_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    if os.environ.get("JOBISSIMO_APPS_DIR"):
        base = Path(os.environ["JOBISSIMO_APPS_DIR"])
    return base / "jobissimo" / "jobissimo-open"


def uninstall_app() -> bool:
    target = app_path()
    if not target.exists():
        return False
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
        if stub_path().exists():
            stub_path().unlink()
    return True


# ---------------------------------------------------------------- at login

def login_dir() -> Path:
    override = os.environ.get("JOBISSIMO_LOGIN_DIR")
    if override:
        return Path(override)
    if system() == "mac":
        return Path.home() / "Library" / "LaunchAgents"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart"


def login_path() -> Path:
    return login_dir() / (f"{AGENT_LABEL}.plist" if system() == "mac" else "jobissimo.desktop")


def login_stub_path() -> Path:
    return paths.local_dir() / "jobissimo-serve"


def set_login(on: bool) -> dict:
    target = login_path()
    if not on:
        if target.exists():
            if system() == "mac" and not os.environ.get("JOBISSIMO_LOGIN_DIR"):
                subprocess.run(["launchctl", "unload", str(target)], capture_output=True)
            target.unlink()
        return {"login": False}
    stub = login_stub_path()
    _write_exec(stub, launcher_script("serve"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if system() == "mac":
        with target.open("wb") as fh:
            plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": ["/bin/sh", str(stub)],
                           "RunAtLoad": True, "AbandonProcessGroup": True,
                           "StandardOutPath": str(log_path()), "StandardErrorPath": str(log_path())}, fh)
    elif system() == "linux":
        target.write_text("\n".join([
            "[Desktop Entry]", "Type=Application", f"Name={APP_NAME} (background)",
            f"Exec=/bin/sh {shlex.quote(str(stub))}", "Terminal=false", "NoDisplay=true",
            "X-GNOME-Autostart-enabled=true"]) + "\n", encoding="utf-8")
    else:
        raise LaunchError("Starting at login is set up for macOS and Linux only.")
    return {"login": True, "file": str(target)}


def status() -> dict:
    st = running()
    return {"os": system(), "running": bool(st), "port": st["port"] if st else None,
            "pid": st["pid"] if st else None,
            "app": {"supported": system() in ("mac", "linux"), "installed": app_path().exists(),
                    "path": str(app_path())},
            "login": {"supported": system() in ("mac", "linux"), "on": login_path().exists(),
                      "path": str(login_path())},
            "workspace": str(paths.home()), "log": str(log_path())}


# ---------------------------------------------------------------- CLI

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open", help="Start the UI if needed and open it in the browser.")
    o.add_argument("--no-browser", action="store_true", help="Print the link instead of opening it.")
    o.add_argument("--idle-exit", type=float, default=IDLE_MINUTES,
                   help=f"Minutes without a browser tab or a run before a started UI stops (default {IDLE_MINUTES}; 0 = never).")
    sub.add_parser("serve", help="Start the UI in the background without opening a browser (at login).")
    sub.add_parser("status", help="Is the UI running; is the app installed; does it start at login.")
    sub.add_parser("stop", help="Stop the running UI.")
    sub.add_parser("install-app", help="Create the Jobissimo app (macOS) or app-menu entry (Linux).")
    sub.add_parser("uninstall-app", help="Remove it.")
    lg = sub.add_parser("login", help="Start the UI in the background when you log in.")
    lg.add_argument("state", choices=["on", "off"])
    args = parser.parse_args()
    try:
        if args.cmd == "open":
            st = open_ui(browser=not args.no_browser, idle_minutes=args.idle_exit)
            print(url_for(st) if args.no_browser else f"Jobissimo is open (port {st['port']}).")
        elif args.cmd == "serve":
            st = running() or start_background(idle_minutes=0)
            print(f"Jobissimo is running (port {st['port']}).")
        elif args.cmd == "status":
            print(json.dumps(status(), indent=2))
        elif args.cmd == "stop":
            print("Stopped." if stop_ui() else "Not running.")
        elif args.cmd == "install-app":
            out = install_app()
            print(f"Installed {out['installed']} for workspace {out['workspace']}.")
        elif args.cmd == "uninstall-app":
            print("Removed." if uninstall_app() else "Not installed.")
        elif args.cmd == "login":
            out = set_login(args.state == "on")
            print("Starts at login." if out["login"] else "No longer starts at login.")
    except LaunchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
