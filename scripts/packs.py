#!/usr/bin/env python3
"""packs.py — pack loader and config layering.

Resolution order, last wins: engine defaults → pack → config. A layer is only
written by its owner: engine by maintainers, packs by community PR, config by
`/setup` (and `/optimise` with per-item approval), profile by the user and the
pipeline. A pack is never edited in place — a user override lands in config/.

The parser below reads the deliberately small YAML subset the repo's own
config and pack files use (stdlib only — no PyYAML dependency): nested
mappings by indentation, scalars, inline lists `[a, b]`, inline dicts
`{k: v}`, block lists of scalars, and comments. Keep config files inside
that subset.

Run `python3 scripts/packs.py` to print the resolved layers.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import paths

# --------------------------------------------------------------- mini-YAML


def _scalar(raw: str):
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    low = s.lower()
    if low in ("null", "~", ""):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def _inline_list(raw: str) -> list:
    inner = raw.strip()[1:-1].strip()
    return [] if not inner else [_scalar(p) for p in inner.split(",")]


def _inline_dict(raw: str) -> dict:
    d = {}
    for part in raw.strip()[1:-1].split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            d[k.strip()] = _scalar(v)
    return d


class _Node:
    """A container whose kind (mapping vs list) is unknown until its first
    child line arrives. Starts as a dict; swaps to a list on a `- ` child."""

    def __init__(self, parent, key):
        self.parent, self.key, self.value = parent, key, {}
        self._commit()

    def _commit(self):
        if isinstance(self.parent, _Node):
            self.parent.value[self.key] = self.value
        elif isinstance(self.parent, dict):
            self.parent[self.key] = self.value

    def to_list(self):
        if isinstance(self.value, dict) and not self.value:
            self.value = []
            self._commit()


def _join_wrapped(text: str) -> list:
    """Join an inline collection that wraps across lines, so
    `competencies: [a, b,` / `c]` parses as a list rather than a truncated
    string. Only a collection opened on a `key:` line continues, and only
    until its matching close — the subset stays deliberately small."""
    out: list = []
    buf = None
    closer = ""
    for raw in text.splitlines():
        if buf is None:
            stripped = raw.strip()
            m = None
            if stripped and not stripped.startswith("#"):
                m = re.match(r"^(.+?):\s*([\[\{].*)$", stripped)
            if m:
                frag = m.group(2)
                opener = frag[0]
                closer = "]" if opener == "[" else "}"
                if frag.count(opener) > frag.count(closer):
                    buf = raw.rstrip()
                    continue
            out.append(raw)
        else:
            buf += " " + raw.strip()
            opener = "[" if closer == "]" else "{"
            if buf.count(opener) <= buf.count(closer):
                out.append(buf)
                buf = None
    if buf is not None:
        out.append(buf)
    return out


def parse_simple_yaml(text: str) -> dict:
    root: dict = {}
    stack: list = [(-1, root)]  # (indent, dict | _Node)
    for raw in _join_wrapped(text):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        top = stack[-1][1]
        node = top.value if isinstance(top, _Node) else top

        if line.startswith("- "):
            if isinstance(top, _Node):
                top.to_list()
                node = top.value
            if not isinstance(node, list):
                continue  # stray list item under a mapping — tolerate
            item = line[2:].strip()
            if item.startswith("{") and item.endswith("}"):
                node.append(_inline_dict(item))
            else:
                node.append(_scalar(item.split(" #", 1)[0]))
            continue

        m = re.match(r"^(.+?):\s*(.*)$", line)
        if not m or not isinstance(node, dict):
            continue
        key = m.group(1).strip().strip('"')
        value = m.group(2)
        if value and not value.startswith(("[", "{")):
            value = value.split(" #", 1)[0].strip()
        if value == "":
            stack.append((indent, _Node(top if isinstance(top, _Node) else node, key)))
        elif value.startswith("[") and value.endswith("]"):
            node[key] = _inline_list(value)
        elif value.startswith("{") and value.endswith("}"):
            node[key] = _inline_dict(value)
        else:
            node[key] = _scalar(value)
    return root


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return parse_simple_yaml(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------- layering

def load_config(name: str) -> dict:
    """Load <config_dir>/<name>.yaml, falling back to the shipped template
    templates/config/<name>.example.yaml when the install has not configured it
    yet. The real file travels with the workspace (resolved via config_dir());
    the example is engine-committed and stays in templates/."""
    real = paths.config_dir() / f"{name}.yaml"
    example = paths.templates_dir() / "config" / f"{name}.example.yaml"
    return load_yaml(real if real.exists() else example)


def active_pack() -> str:
    return str(load_config("pipeline").get("pack") or "product")


def pack_search_path(name: str | None = None) -> list:
    """Where a pack may live, in resolution order: the install's own packs
    first, then the engine's shipped ones. A workspace pack shadows a shipped
    pack of the same name — that is how an install takes ownership of one."""
    n = name or active_pack()
    return [paths.workspace_packs_dir() / n, paths.packs_dir() / n]


def pack_dir(name: str | None = None) -> Path:
    """The resolved pack directory. Falls back to the engine location when
    neither exists, so error messages name the conventional path."""
    candidates = pack_search_path(name)
    for path in candidates:
        if (path / "pack.yaml").exists():
            return path
    return candidates[-1]


def pack_origin(name: str | None = None) -> str:
    """`workspace`, `engine`, or `missing` — which layer answered."""
    ws, engine = pack_search_path(name)
    if (ws / "pack.yaml").exists():
        return "workspace"
    if (engine / "pack.yaml").exists():
        return "engine"
    return "missing"


def available_packs() -> list:
    """(name, origin) for every resolvable pack, workspace ones first."""
    found: list = []
    seen: set = set()
    for root, origin in ((paths.workspace_packs_dir(), "workspace"),
                         (paths.packs_dir(), "engine")):
        if not root.exists():
            continue
        for entry in sorted(root.iterdir()):
            if entry.name in seen or not (entry / "pack.yaml").exists():
                continue
            seen.add(entry.name)
            found.append((entry.name, origin))
    return found


def pack_yaml() -> dict:
    return load_yaml(pack_dir() / "pack.yaml")


# --------------------------------------------------------------- lookups

def candidate_name() -> str | None:
    identity = load_config("pipeline").get("identity") or {}
    name = identity.get("name")
    return str(name) if name else None


def _merge_terms(*groups) -> list:
    """Union of term lists, order-preserving and case-insensitively deduped.
    The config layer extends the pack rather than replacing it: `last wins`
    applies per term, not per file, so a pack term can never be silently
    dropped by a config file that simply omits it."""
    out: list = []
    seen: set = set()
    for group in groups:
        if isinstance(group, str):
            group = [group]
        for term in group or []:
            t = str(term).strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return out


def _blank_cluster() -> dict:
    return {"title": None, "competencies": [], "adjacent": []}


def _roles_layers() -> list:
    """The pack's roles.yaml, then the config override if the install has one.
    Later layers extend earlier ones."""
    layers = [load_yaml(pack_dir() / "roles.yaml")]
    override = paths.config_dir() / "roles.yaml"
    if override.exists():
        layers.append(load_yaml(override))
    return layers


def roles() -> dict:
    """Resolved cluster definitions: pack ∪ config, with each layer's
    `common:` competencies merged into every cluster. A config layer may
    extend an existing cluster's competency set or define a new cluster."""
    layers = _roles_layers()
    common = _merge_terms(*[(layer.get("common") or {}).get("competencies")
                            for layer in layers
                            if isinstance(layer.get("common"), dict)])
    resolved: dict = {}
    for layer in layers:
        clusters = layer.get("clusters")
        if not isinstance(clusters, dict):
            continue
        for cid, body in clusters.items():
            if not isinstance(body, dict):
                continue
            entry = resolved.setdefault(cid, _blank_cluster())
            if body.get("title"):
                entry["title"] = str(body["title"])
            entry["competencies"] = _merge_terms(entry["competencies"],
                                                 body.get("competencies"))
            entry["adjacent"] = _merge_terms(entry["adjacent"], body.get("adjacent"))
    for cid in (load_config("pipeline").get("extra_role_clusters") or []):
        resolved.setdefault(str(cid), _blank_cluster())
    if common:
        for entry in resolved.values():
            entry["competencies"] = _merge_terms(common, entry["competencies"])
    return resolved


def role_clusters() -> list:
    """Cluster ids the scorer may use: pack roles ∪ config additions."""
    return list(roles().keys())


def cluster_competencies(cluster: str) -> list:
    """The resolved competency set for one cluster (pack + config + common)."""
    entry = roles().get(cluster)
    return list(entry["competencies"]) if entry else []


def location_fit_values() -> list:
    vals = load_config("pipeline").get("location_fit_values")
    if isinstance(vals, list) and vals:
        return [str(v) for v in vals]
    return ["match", "remote_ok", "relocation_eu", "relocation_non_eu", "reject"]


def figure_nouns() -> list:
    nouns = pack_yaml().get("figure_nouns")
    if isinstance(nouns, list) and nouns:
        return [str(n) for n in nouns]
    return ["months", "hours", "weeks", "days", "years", "locations", "stores",
            "people", "teams", "clients", "customers", "users", "markets",
            "countries", "releases"]


def configured_languages() -> list:
    langs = load_config("languages").get("languages")
    if isinstance(langs, dict):
        return list(langs.keys())
    if isinstance(langs, list):
        out = []
        for item in langs:
            if isinstance(item, dict) and "code" in item:
                out.append(str(item["code"]))
            elif isinstance(item, str):
                out.append(item)
        return out
    return []


def synonym_files() -> list:
    """The pack's base synonym table plus one locale file per configured
    language (all locales when none are configured yet, so the fixture
    rehearsal and a fresh checkout behave deterministically)."""
    files = [pack_dir() / "ats_synonyms.yaml"]
    locales = pack_dir() / "locales"
    langs = configured_languages()
    if langs:
        files += [locales / f"{code}.yaml" for code in langs]
    elif locales.exists():
        files += sorted(locales.glob("*.yaml"))
    # Config layer last: an install's own bridges extend the pack's table.
    cfg = paths.config_dir()
    files.append(cfg / "ats_synonyms.yaml")
    files += [cfg / "locales" / f"{code}.yaml" for code in langs]
    return [f for f in files if f.exists()]


def keywords_files() -> list:
    """The pack's hard/soft classifier plus the install's override, in
    resolution order. Later files extend earlier sections."""
    files = [pack_dir() / "ats_keywords.yaml",
             paths.config_dir() / "ats_keywords.yaml"]
    return [f for f in files if f.exists()]


# --------------------------------------------------------------- authoring

REQUIRED_PACK_FILES = ("pack.yaml", "roles.yaml", "evaluation.md",
                       "ats_keywords.yaml", "ats_synonyms.yaml", "boards.yaml")


def validate_pack(name: str) -> tuple:
    """(errors, warnings) for a pack. Errors mean it cannot work; warnings
    mean it will work but is thinner than a contribution should be. A pack
    declaring `scaffold: true` (packs/generic) is intentionally incomplete:
    the checks that only make sense for a finished pack are skipped."""
    errors: list = []
    warnings: list = []
    root = pack_dir(name)
    if not (root / "pack.yaml").exists():
        return ([f"{name}: no pack.yaml at {root}"], [])
    manifest = load_yaml(root / "pack.yaml")
    scaffold = bool(manifest.get("scaffold"))

    for fname in ("roles.yaml", "evaluation.md", "ats_keywords.yaml",
                  "ats_synonyms.yaml"):
        if not (root / fname).exists():
            errors.append(f"missing {fname}")
    if not manifest.get("name"):
        errors.append("pack.yaml: no name")
    if not manifest.get("figure_nouns"):
        errors.append("pack.yaml: no figure_nouns")

    clusters = load_yaml(root / "roles.yaml").get("clusters")
    if not isinstance(clusters, dict) or not clusters:
        errors.append("roles.yaml: no clusters")
    elif not scaffold:
        for cid, body in clusters.items():
            comps = body.get("competencies") if isinstance(body, dict) else None
            if not isinstance(comps, list) or not comps:
                errors.append(f"roles.yaml: cluster {cid} has no competencies")

    if not scaffold:
        if not (root / "boards.yaml").exists():
            warnings.append("no boards.yaml — /hunt falls back to the shipped catalogue")
        if not (root / "locales").is_dir():
            warnings.append("no locales/ — market conventions fall back to neutral")
    return (errors, warnings)


def fork_pack(source: str, new_name: str | None = None) -> Path:
    """Copy a pack into the workspace so the install can edit it freely.
    Returns the new directory. Refuses to clobber an existing workspace pack."""
    src = pack_dir(source)
    if not (src / "pack.yaml").exists():
        raise SystemExit(f"packs: no pack named {source!r} (looked in "
                         f"{', '.join(str(p) for p in pack_search_path(source))})")
    name = new_name or source
    dest = paths.workspace_packs_dir() / name
    if dest.exists():
        raise SystemExit(f"packs: {dest} already exists — pick another name "
                         f"with --as, or edit the pack in place")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    manifest = dest / "pack.yaml"
    if manifest.exists():
        text = manifest.read_text(encoding="utf-8")
        if name != source:
            text = re.sub(r"^name:.*$", f"name: {name}", text, count=1, flags=re.M)
        # A fork is the install's own pack, never a scaffold: drop the flag
        # and the comment block that explains it, so the pack can be finished
        # and exported under its own name.
        kept: list = []
        for line in text.splitlines():
            if line.startswith("scaffold:"):
                while kept and kept[-1].startswith("#"):
                    kept.pop()
                while kept and not kept[-1].strip():
                    kept.pop()
                continue
            kept.append(line)
        manifest.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return dest


def export_pack(name: str, force: bool = False) -> Path:
    """Copy a workspace pack into the engine checkout so it can be reviewed
    and opened as a PR. Scrub-gated: a pack carries competency wording and
    board notes drawn from real applications, so it is checked for personal
    data before it is allowed anywhere near the public repo."""
    src = paths.workspace_packs_dir() / name
    if not (src / "pack.yaml").exists():
        raise SystemExit(f"packs: no workspace pack named {name!r} at {src}")
    if load_yaml(src / "pack.yaml").get("scaffold"):
        raise SystemExit(f"packs: {name} is a scaffold, not a finished pack. Fork it "
                         f"under your own domain name first:\n"
                         f"  python3 scripts/packs.py --fork {name} --as <yourdomain>")
    errors, warnings = validate_pack(name)
    if errors:
        raise SystemExit("packs: pack is not well-formed, fix before exporting:\n  - "
                         + "\n  - ".join(errors))
    for w in warnings:
        print(f"warning: {w}")
    # Scrub a staging copy outside the workspace, never the pack in place:
    # scrub_check skips any directory named `profile` (SKIP_DIRS), which is
    # the default workspace name, so scanning the source would silently pass
    # on a default install. Staging also scans exactly the bytes that land.
    scrub = Path(__file__).resolve().parent / "scrub_check.py"
    with tempfile.TemporaryDirectory() as staging:
        staged = Path(staging) / name
        shutil.copytree(src, staged)
        result = subprocess.run([sys.executable, str(scrub), str(staged)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stdout or result.stderr).replace(str(staged), str(src))
            raise SystemExit("packs: scrub gate found personal data in the pack — "
                             "nothing was copied.\n" + detail.strip())
    dest = paths.packs_dir() / name
    if dest.exists() and not force:
        raise SystemExit(f"packs: {dest} already exists — pass --force to overwrite")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true",
                    help="List every resolvable pack and where it came from.")
    ap.add_argument("--fork", metavar="NAME",
                    help="Copy a pack into the workspace so you can edit it.")
    ap.add_argument("--as", dest="as_name", metavar="NEW",
                    help="Name for the forked pack (default: same name).")
    ap.add_argument("--export", metavar="NAME",
                    help="Copy a workspace pack into the engine checkout for a PR "
                         "(scrub-gated and validated first).")
    ap.add_argument("--validate", metavar="NAME",
                    help="Report structural problems with a pack.")
    ap.add_argument("--force", action="store_true",
                    help="With --export, overwrite an existing shipped pack.")
    args = ap.parse_args()

    if args.list:
        for name, origin in available_packs():
            marker = " *" if name == active_pack() else "  "
            print(f"{marker} {name:<16} {origin}")
        return 0

    if args.validate:
        errors, warnings = validate_pack(args.validate)
        origin = pack_origin(args.validate)
        if not errors and not warnings:
            print(f"{args.validate}: well-formed ({origin})")
            return 0
        print(f"{args.validate}: {len(errors)} error(s), {len(warnings)} warning(s)"
              f"  ({origin})")
        for e in errors:
            print(f"  error:   {e}")
        for w in warnings:
            print(f"  warning: {w}")
        return 1 if errors else 0

    if args.fork:
        dest = fork_pack(args.fork, args.as_name)
        name = args.as_name or args.fork
        print(f"Forked {args.fork} -> {dest}")
        print(f"It now shadows any shipped pack of the same name.")
        print(f"Next: set `pack: {name}` in config/pipeline.yaml, then edit away.")
        print("It travels with /sync, so it reaches your other machines.")
        return 0

    if args.export:
        dest = export_pack(args.export, force=args.force)
        print(f"Exported {args.export} -> {dest}  (scrub gate passed)")
        print("Next, in the engine repo:")
        print(f"  git checkout -b pack/{args.export}")
        print(f"  git add packs/{args.export} && git commit")
        print("  open a PR — see CONTRIBUTING.md for the fixture and test it asks for")
        return 0

    print(f"active pack:      {active_pack()}  ({pack_dir()})")
    print(f"candidate name:   {candidate_name() or '(not configured)'}")
    print(f"role clusters:    {', '.join(role_clusters()) or '(none)'}")
    print(f"location fits:    {', '.join(location_fit_values())}")
    print(f"languages:        {', '.join(configured_languages()) or '(not configured)'}")
    print(f"synonym files:    {', '.join(str(f) for f in synonym_files())}")
    print(f"keyword files:    {', '.join(str(f) for f in keywords_files())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
