# Bento: neal's per-run container on disk.
#
# A bento is one extraction run, laid out under NEAL_HOME (default ~/var/neal):
#
#   inbox/                     drop transcripts here
#   bentos/<uuid>/
#       raw_data/              the source narration, copied in (never moved)
#       outputs/
#           graph/             the durable artifact: nodes.jsonl, edges.jsonl
#           cards/             the projection: character/place/... markdown
#           render/            the story-bible PDF and its sources
#       manifest.json          what ran, which backend, per-stage stats
#
# neal writes only candidate bentos here; it never writes into the live screenplay
# canon. The writer curates what gets promoted.

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HOME = Path.home() / "var" / "neal"

# The source kinds neal ingests; audio is text by the time neal sees it.
TEXT_SUFFIXES = (".md", ".txt")


def neal_home(home: Path | str | None = None) -> Path:
    # resolve NEAL_HOME: explicit arg wins, then the env var, then the default.
    if home is not None:
        return Path(home)
    env = os.environ.get("NEAL_HOME")
    return Path(env) if env else DEFAULT_HOME


def inbox(home: Path | str | None = None) -> Path:
    return neal_home(home) / "inbox"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# a handle to one bento on disk. Paths are derived; nothing is cached.
@dataclass(frozen=True)
class Bento:
    id: str
    root: Path

    @property
    def raw_data(self) -> Path:
        return self.root / "raw_data"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def graph(self) -> Path:
        return self.outputs / "graph"

    @property
    def cards(self) -> Path:
        return self.outputs / "cards"

    @property
    def render(self) -> Path:
        return self.outputs / "render"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def read_manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text())

    def write_manifest(self, manifest: dict) -> None:
        # sort_keys keeps the on-disk manifest stable for clean diffs.
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )


def create_bento(home: Path | str | None = None, *, bento_id: str | None = None) -> Bento:
    # mint a new bento: a fresh uuid, the directory tree, and an initial manifest.
    bid = bento_id or str(uuid.uuid4())
    root = neal_home(home) / "bentos" / bid
    bento = Bento(id=bid, root=root)
    for d in (bento.raw_data, bento.graph, bento.cards, bento.render):
        d.mkdir(parents=True, exist_ok=True)
    bento.write_manifest(
        {
            "bento_id": bid,
            "created": _utcnow(),
            "raw_data": {"files": [], "count": 0},
            "stages": {},
        }
    )
    return bento


def _same_bytes(a: Path, b: Path) -> bool:
    return a.read_bytes() == b.read_bytes()


def ingest(
    bento: Bento,
    sources: Iterable[Path | str],
    *,
    suffixes: tuple[str, ...] = TEXT_SUFFIXES,
) -> list[str]:
    # copy source narration into the bento's raw_data -- never moves the source.
    # `sources` may be files or directories; directories are walked for `suffixes`.
    # A name collision between distinct sources is disambiguated rather than
    # clobbered. Returns the raw_data filenames copied this call; updates the manifest.
    candidates: list[Path] = []
    for s in sources:
        p = Path(s)
        if p.is_dir():
            candidates.extend(
                sorted(
                    f
                    for f in p.rglob("*")
                    if f.is_file() and f.suffix.lower() in suffixes
                )
            )
        elif p.is_file():
            candidates.append(p)

    copied: list[str] = []
    for f in candidates:
        dest = bento.raw_data / f.name
        if dest.exists() and not _same_bytes(f, dest):
            dest = bento.raw_data / f"{f.stem}.{uuid.uuid4().hex[:8]}{f.suffix}"
        shutil.copy2(f, dest)  # copy, never move
        copied.append(dest.name)

    manifest = bento.read_manifest()
    listed = manifest.setdefault("raw_data", {}).setdefault("files", [])
    seen = set(listed)
    for name in copied:
        if name not in seen:
            listed.append(name)
            seen.add(name)
    manifest["raw_data"]["count"] = len(listed)
    bento.write_manifest(manifest)
    return copied


def record_stage(bento: Bento, stage: str, info: dict) -> None:
    # fold a stage's results into the manifest under stages.<stage>.
    manifest = bento.read_manifest()
    manifest.setdefault("stages", {})[stage] = {"ran_at": _utcnow(), **info}
    bento.write_manifest(manifest)


def ingest_inbox(home: Path | str | None = None) -> Bento:
    # convenience: a fresh bento seeded from everything currently in the inbox.
    bento = create_bento(home)
    box = inbox(home)
    if box.is_dir():
        ingest(bento, [box])
    return bento


def _created(bento: Bento) -> str:
    try:
        return bento.read_manifest().get("created", "")
    except (OSError, ValueError):
        return ""


def list_bentos(home: Path | str | None = None) -> list[Bento]:
    # all bentos under NEAL_HOME, oldest first by creation time.
    base = neal_home(home) / "bentos"
    if not base.is_dir():
        return []
    bentos = [
        Bento(id=d.name, root=d)
        for d in base.iterdir()
        if d.is_dir() and (d / "manifest.json").is_file()
    ]
    return sorted(bentos, key=_created)


def resolve_bento(ref: str | None = None, home: Path | str | None = None) -> Bento:
    # resolve a bento by full id, unique id prefix, or (None/"latest") most recent.
    # raises LookupError if there are no bentos, no match, or an ambiguous prefix.
    bentos = list_bentos(home)
    if not bentos:
        raise LookupError("no bentos yet")
    if ref is None or ref == "latest":
        return bentos[-1]
    exact = [b for b in bentos if b.id == ref]
    if exact:
        return exact[0]
    matches = [b for b in bentos if b.id.startswith(ref)]
    if not matches:
        raise LookupError(f"no bento matching {ref!r}")
    if len(matches) > 1:
        raise LookupError(f"ambiguous bento ref {ref!r} ({len(matches)} matches)")
    return matches[0]
