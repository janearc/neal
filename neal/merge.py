# Merge / entity resolution: fold the per-window nodes into a canonical graph.
#
# Two jobs, and the line between them is canon discipline:
#  - CERTAIN folds are applied. The same term seen across windows is one entity, its
#    provenance and confidence aggregated, its surface variants kept as aliases, and a
#    disagreement over its kind surfaced (not silently resolved away).
#  - UNCERTAIN folds are surfaced, never applied. A near-miss pair (a misheard name and
#    a plausible correct spelling) becomes an open-puzzle for the writer to judge. neal
#    does not silently merge two names into one -- that would be inventing a fact.
#
# Deterministic: no model. The model typed the nodes; resolution is bookkeeping.

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

from neal.bento import Bento, parent_of, record_stage

UNKNOWN = "UNKNOWN"
# SequenceMatcher ratio above which two same-kind labels are *suggested* as the same
# entity. Tuned to catch single-edit misheard short names (e.g. "Mara"/"Mira" ~= 0.75)
# while staying clear of genuinely distinct terms. These are only suggestions -- the
# writer judges -- so a stray suggestion is cheap, but a missed split leaves the graph
# lying. neal never applies them; it asks.
NEAR_DUPLICATE_THRESHOLD = 0.72

_WS = re.compile(r"\s+")


class MergeError(RuntimeError):
    # the input was not raw extract output (e.g. nodes.jsonl was already merged).
    pass


def _norm(term: str) -> str:
    return _WS.sub(" ", term.strip()).casefold()


def _slug(label: str) -> str:
    return _WS.sub("-", label.strip().casefold())


@dataclass(frozen=True)
class Entity:
    id: str  # stable: "<kind>:<slug(label)>"
    label: str  # canonical surface form
    kind: str
    aliases: list[str]  # the distinct surface forms folded in
    confidence: float  # max over the chosen kind
    support: int  # how many raw nodes corroborate this entity
    backends: list[str]  # which backend(s) typed it
    kind_alternatives: list[str]  # other kinds the model assigned -- conflict, surfaced
    provenance: list[dict]  # every window the entity was seen in

    def to_dict(self) -> dict:
        return asdict(self)


def merge_nodes(raw_nodes: list[dict]) -> list[Entity]:
    # group raw extract nodes by normalized term and fold each group into one Entity.
    groups: dict[str, list[dict]] = defaultdict(list)
    for node in raw_nodes:
        if "term" not in node:
            raise MergeError("node record has no 'term' -- expected raw extract output")
        groups[_norm(node["term"])].append(node)

    entities: list[Entity] = []
    for group in groups.values():
        surfaces = Counter(n["term"].strip() for n in group)
        # canonical label: the most common surface form, ties broken alphabetically.
        label = sorted(surfaces.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        summed: dict[str, float] = defaultdict(float)
        for n in group:
            summed[n.get("kind", UNKNOWN)] += float(n.get("confidence", 0.0))
        # chosen kind: highest summed confidence, but UNKNOWN only if nothing else won.
        chosen = sorted(summed.items(), key=lambda kv: (kv[0] == UNKNOWN, -kv[1], kv[0]))[0][0]
        alternatives = sorted(k for k in summed if k != chosen)

        confidence = max(
            (float(n.get("confidence", 0.0)) for n in group if n.get("kind") == chosen),
            default=0.0,
        )
        backends = sorted({n["backend"] for n in group if n.get("backend")})
        provenance = [n["provenance"] for n in group if "provenance" in n]

        entities.append(
            Entity(
                id=f"{chosen}:{_slug(label)}",
                label=label,
                kind=chosen,
                aliases=sorted(surfaces),
                confidence=confidence,
                support=len(group),
                backends=backends,
                kind_alternatives=alternatives,
                provenance=provenance,
            )
        )
    return sorted(entities, key=lambda e: e.id)


def propose_merges(
    entities: list[Entity], *, threshold: float = NEAR_DUPLICATE_THRESHOLD
) -> list[dict]:
    # surface near-duplicate, same-kind entities as open-puzzles. neal never applies
    # these -- it asks. label-similarity only, conservative threshold.
    puzzles: list[dict] = []
    for i in range(len(entities)):
        for j in range(i + 1, len(entities)):
            a, b = entities[i], entities[j]
            if a.kind != b.kind or _norm(a.label) == _norm(b.label):
                continue
            ratio = SequenceMatcher(None, a.label.casefold(), b.label.casefold()).ratio()
            if ratio >= threshold:
                puzzles.append(
                    {
                        "kind": "open-puzzle",
                        "question": f"Are {a.label!r} and {b.label!r} the same {a.kind}?",
                        "a": a.id,
                        "b": b.id,
                        "similarity": round(ratio, 3),
                        "backend": "neal-merge",
                    }
                )
    return puzzles


def run_merge(bento: Bento) -> Path:
    # resolve the raw nodes into the canonical graph, and surface near-duplicate
    # suggestions. records a `merge` stage. returns the canonical nodes path.
    nodes_path = bento.graph / "nodes.jsonl"
    if not nodes_path.is_file():
        raise MergeError("no nodes.jsonl -- run extraction first")
    raw = [json.loads(line) for line in nodes_path.read_text().splitlines() if line.strip()]

    entities = merge_nodes(raw)
    # stamp which bento each mention came from, so a later synthesis across a lineage
    # keeps every entity's provenance traceable to its originating bento.
    for entity in entities:
        for prov in entity.provenance:
            prov["bento"] = bento.id
    puzzles = propose_merges(entities)

    nodes_path.write_text(
        "".join(json.dumps(e.to_dict(), sort_keys=True) + "\n" for e in entities)
    )
    puzzles_path = bento.graph / "open_puzzles.jsonl"
    puzzles_path.write_text("".join(json.dumps(p, sort_keys=True) + "\n" for p in puzzles))

    record_stage(
        bento,
        "merge",
        {
            "backend": "neal-merge",
            "raw_nodes": len(raw),
            "entities": len(entities),
            "open_puzzles": len(puzzles),
            "output": str(nodes_path.relative_to(bento.root)),
        },
    )
    return nodes_path


def _aliases(entity: dict) -> list[str]:
    return entity.get("aliases") or [entity["label"]]


def synthesize(parent_entities: list[dict], child_entities: list[dict]) -> list[Entity]:
    # fold a parent's resolved entities with a child's into one composed graph. a label
    # present in both lineages becomes a single entity carrying both sets of provenance;
    # support sums, kinds reconcile (the loser surfaced in kind_alternatives), aliases and
    # backends union. neither input is mutated -- the parent's graph is left intact.
    groups: dict[str, list[dict]] = defaultdict(list)
    for entity in [*parent_entities, *child_entities]:
        groups[_norm(entity["label"])].append(entity)

    composed: list[Entity] = []
    for group in groups.values():
        # canonical label: the best-supported entity's surface form, ties alphabetical.
        label = sorted(group, key=lambda e: (-e.get("support", 1), e["label"]))[0]["label"]

        by_kind: dict[str, float] = defaultdict(float)
        for e in group:
            by_kind[e["kind"]] += e.get("support", 1)
        chosen = sorted(by_kind.items(), key=lambda kv: (kv[0] == UNKNOWN, -kv[1], kv[0]))[0][0]
        alternatives = sorted(
            {
                k
                for e in group
                for k in [e["kind"], *e.get("kind_alternatives", [])]
                if k != chosen
            }
        )
        confidence = max(
            (e.get("confidence", 0.0) for e in group if e["kind"] == chosen), default=0.0
        )
        aliases = sorted({a for e in group for a in _aliases(e)})
        backends = sorted({b for e in group for b in e.get("backends", [])})
        # dedupe provenance so re-running synthesis is idempotent; support is the count
        # of distinct corroborating mentions, derived from provenance rather than summed.
        provenance: list[dict] = []
        seen: set[tuple] = set()
        for e in group:
            for p in e.get("provenance", []):
                key = (p.get("bento"), p.get("document"), p.get("window"), p.get("start"))
                if key not in seen:
                    seen.add(key)
                    provenance.append(p)

        composed.append(
            Entity(
                id=f"{chosen}:{_slug(label)}",
                label=label,
                kind=chosen,
                aliases=aliases,
                confidence=confidence,
                support=len(provenance),
                backends=backends,
                kind_alternatives=alternatives,
                provenance=provenance,
            )
        )
    return sorted(composed, key=lambda e: e.id)


def _read_entities(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_synthesis(bento: Bento) -> Path | None:
    # if the bento has a parent, compose this bento's resolved graph onto the parent's:
    # 456.output = synthesize(123.output, 456.output). overwrites this bento's nodes.jsonl
    # with the composition, re-surfaces near-duplicates, records a `synthesize` stage. the
    # parent is read-only. no parent -> no-op (the bento stands alone). lineage chains
    # transitively, since the parent's output already encodes its own parent.
    parent_id = parent_of(bento)
    if not parent_id:
        return None

    parent = Bento(id=parent_id, root=bento.root.parent / parent_id)
    parent_entities = _read_entities(parent.graph / "nodes.jsonl")
    if not parent_entities:
        raise MergeError(f"parent bento {parent_id!r} has no resolved graph -- build it first")

    child_path = bento.graph / "nodes.jsonl"
    composed = synthesize(parent_entities, _read_entities(child_path))
    child_path.write_text(
        "".join(json.dumps(e.to_dict(), sort_keys=True) + "\n" for e in composed)
    )
    puzzles = propose_merges(composed)
    (bento.graph / "open_puzzles.jsonl").write_text(
        "".join(json.dumps(p, sort_keys=True) + "\n" for p in puzzles)
    )

    record_stage(
        bento,
        "synthesize",
        {
            "backend": "neal-merge",
            "parent": parent_id,
            "parent_entities": len(parent_entities),
            "entities": len(composed),
            "open_puzzles": len(puzzles),
            "output": str(child_path.relative_to(bento.root)),
        },
    )
    return child_path
