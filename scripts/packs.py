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


def pack_dir(name: str | None = None) -> Path:
    return paths.packs_dir() / (name or active_pack())


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


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
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
