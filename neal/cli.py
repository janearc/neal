# The `neal` command -- a thin wrapper over the library.
#
# Two-phase, like the other services: `new` mints a bento (a template you fill), you
# drop files in its inbox, then `build` runs the pipeline on it. A bento can name a
# parent (`--from`), and builds compose onto that lineage rather than flattening.
#
#   neal new [--from PARENT] [SOURCE...]   mint a bento (optionally onto PARENT)
#   neal build [BENTO]                     ingest inbox -> prepass -> extract -> merge
#   neal prepass [BENTO]                   run the prepass on a bento
#   neal extract [BENTO]                   type a bento's candidates into nodes
#   neal merge [BENTO]                     fold a bento's nodes into the graph
#   neal ls                                list bentos (with lineage)
#
# extract/build reach a model through delightd discovery (the good-citizen client),
# fail-closed: if nothing healthy serves it, the command says so and exits non-zero.

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from neal.bento import (
    Bento,
    create_bento,
    ingest,
    ingest_inbox,
    list_bentos,
    parent_of,
    resolve_bento,
)
from neal.extract import ExtractionError, run_extraction
from neal.merge import MergeError, run_merge
from neal.model import DiscoveryModel, ModelClient
from neal.prepass import run_prepass


def _model() -> ModelClient:
    # the real model seam (mistral via delightd discovery). a factory so tests swap it.
    return DiscoveryModel()


def _prepass(bento: Bento) -> None:
    run_prepass(bento)
    stage = bento.read_manifest()["stages"]["prepass"]
    print(f"  prepass: {stage['candidate_terms']} candidate term(s)")


def _extract(bento: Bento) -> None:
    run_extraction(bento, _model())
    stage = bento.read_manifest()["stages"]["extract"]
    print(f"  extract: {stage['nodes']} node(s) from {stage['model_calls']} call(s)")


def _merge(bento: Bento) -> None:
    run_merge(bento)
    stage = bento.read_manifest()["stages"]["merge"]
    print(f"  merge: {stage['entities']} entit(y/ies), {stage['open_puzzles']} open-puzzle(s)")


def _cmd_new(args: argparse.Namespace) -> None:
    parent = resolve_bento(args.from_bento).id if args.from_bento else None
    bento = create_bento(parent=parent)
    if args.sources:
        ingest(bento, args.sources)
    lineage = f" (onto {parent})" if parent else ""
    count = bento.read_manifest()["raw_data"]["count"]
    print(f"bento {bento.id}{lineage}")
    print(f"  drop files in: {bento.inbox}")
    if count:
        print(f"  pre-filled with {count} file(s)")


def _cmd_build(args: argparse.Namespace) -> None:
    bento = resolve_bento(args.bento)
    ingested = ingest_inbox(bento)
    parent = parent_of(bento)
    lineage = f" (onto {parent})" if parent else ""
    print(f"build {bento.id}{lineage}: {len(ingested)} new file(s) from inbox")
    _prepass(bento)
    _extract(bento)
    _merge(bento)


def _cmd_prepass(args: argparse.Namespace) -> None:
    _prepass(resolve_bento(args.bento))


def _cmd_extract(args: argparse.Namespace) -> None:
    _extract(resolve_bento(args.bento))


def _cmd_merge(args: argparse.Namespace) -> None:
    _merge(resolve_bento(args.bento))


def _cmd_ls(args: argparse.Namespace) -> None:
    bentos = list_bentos()
    if not bentos:
        print("no bentos yet")
        return
    for bento in bentos:
        manifest = bento.read_manifest()
        stages = ",".join(sorted(manifest.get("stages", {}))) or "-"
        parent = manifest.get("parent")
        lineage = f" <- {parent}" if parent else ""
        print(
            f"{bento.id}{lineage}  files={manifest['raw_data']['count']}  "
            f"stages={stages}  {manifest.get('created', '')}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neal", description="narration in, a story graph out"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="mint a bento (optionally onto a parent)")
    p_new.add_argument("--from", dest="from_bento", metavar="PARENT", help="parent bento id/prefix")
    p_new.add_argument("sources", nargs="*", type=Path, help="optional files/dirs to pre-fill")
    p_new.set_defaults(func=_cmd_new)

    p_build = sub.add_parser("build", help="ingest inbox -> prepass -> extract -> merge")
    p_build.add_argument("bento", nargs="?", help="bento id/prefix (default: most recent)")
    p_build.set_defaults(func=_cmd_build)

    p_prepass = sub.add_parser("prepass", help="run the prepass on a bento")
    p_prepass.add_argument("bento", nargs="?", help="bento id/prefix (default: most recent)")
    p_prepass.set_defaults(func=_cmd_prepass)

    p_extract = sub.add_parser("extract", help="type a bento's candidates into nodes")
    p_extract.add_argument("bento", nargs="?", help="bento id/prefix (default: most recent)")
    p_extract.set_defaults(func=_cmd_extract)

    p_merge = sub.add_parser("merge", help="fold a bento's nodes into the graph")
    p_merge.add_argument("bento", nargs="?", help="bento id/prefix (default: most recent)")
    p_merge.set_defaults(func=_cmd_merge)

    p_ls = sub.add_parser("ls", help="list bentos (with lineage)")
    p_ls.set_defaults(func=_cmd_ls)

    return parser


def _operational_errors() -> tuple[type[BaseException], ...]:
    # failures we report as a clean one-line error, not a traceback: a missing bento,
    # a stage run out of order, or the model being unavailable (fail-closed).
    errs: list[type[BaseException]] = [LookupError, ExtractionError, MergeError]
    try:
        from good_citizen.model import ModelUnavailable

        errs.append(ModelUnavailable)
    except Exception:
        # good_citizen not importable here just means there's nothing extra to catch.
        pass
    return tuple(errs)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except _operational_errors() as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
