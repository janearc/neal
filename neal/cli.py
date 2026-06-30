# The `neal` command -- a thin wrapper over the library.
#
# No logic lives here: each subcommand calls neal.bento / neal.prepass and prints a
# line. The library is the product; the CLI is just a way to drive it.
#
#   neal build [SOURCE...]    ingest -> prepass -> extract -> merge (no SOURCE = inbox)
#   neal run [SOURCE...]      ingest then prepass only (model-free; no SOURCE = inbox)
#   neal ingest [SOURCE...]   new bento from SOURCEs (default: the inbox)
#   neal prepass [BENTO]      run the prepass on a bento (default: most recent)
#   neal extract [BENTO]      type a bento's candidates into nodes (resolves a model)
#   neal merge [BENTO]        fold a bento's nodes into the canonical graph
#   neal ls                   list bentos
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
    resolve_bento,
)
from neal.extract import ExtractionError, run_extraction
from neal.merge import MergeError, run_merge
from neal.model import DiscoveryModel, ModelClient
from neal.prepass import run_prepass


def _ingest(sources: list[Path]) -> Bento:
    if sources:
        bento = create_bento()
        ingest(bento, sources)
    else:
        bento = ingest_inbox()
    count = bento.read_manifest()["raw_data"]["count"]
    print(f"bento {bento.id}  ({count} file(s) in {bento.raw_data})")
    return bento


def _prepass(bento: Bento) -> None:
    out = run_prepass(bento)
    stage = bento.read_manifest()["stages"]["prepass"]
    print(f"prepass {bento.id}: {stage['candidate_terms']} candidate term(s) -> {out}")


def _model() -> ModelClient:
    # the real model seam (mistral via delightd discovery). a factory so tests swap it.
    return DiscoveryModel()


def _extract(bento: Bento) -> None:
    run_extraction(bento, _model())
    stage = bento.read_manifest()["stages"]["extract"]
    print(f"extract {bento.id}: {stage['nodes']} node(s) from {stage['model_calls']} call(s)")


def _merge(bento: Bento) -> None:
    run_merge(bento)
    stage = bento.read_manifest()["stages"]["merge"]
    print(
        f"merge {bento.id}: {stage['entities']} entit(y/ies), "
        f"{stage['open_puzzles']} open-puzzle(s)"
    )


def _cmd_ingest(args: argparse.Namespace) -> None:
    _ingest(args.sources)


def _cmd_prepass(args: argparse.Namespace) -> None:
    _prepass(resolve_bento(args.bento))


def _cmd_run(args: argparse.Namespace) -> None:
    _prepass(_ingest(args.sources))


def _cmd_extract(args: argparse.Namespace) -> None:
    _extract(resolve_bento(args.bento))


def _cmd_merge(args: argparse.Namespace) -> None:
    _merge(resolve_bento(args.bento))


def _cmd_build(args: argparse.Namespace) -> None:
    # the whole pipeline on one bento: narration in, resolved story graph out.
    bento = _ingest(args.sources)
    _prepass(bento)
    _extract(bento)
    _merge(bento)


def _cmd_ls(args: argparse.Namespace) -> None:
    bentos = list_bentos()
    if not bentos:
        print("no bentos yet")
        return
    for bento in bentos:
        manifest = bento.read_manifest()
        stages = ",".join(sorted(manifest.get("stages", {}))) or "-"
        print(
            f"{bento.id}  files={manifest['raw_data']['count']}  "
            f"stages={stages}  {manifest.get('created', '')}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neal", description="narration in, a story graph out"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="ingest -> prepass -> extract -> merge")
    p_build.add_argument("sources", nargs="*", type=Path, help="files/dirs (default: inbox)")
    p_build.set_defaults(func=_cmd_build)

    p_run = sub.add_parser("run", help="ingest then prepass only (model-free)")
    p_run.add_argument("sources", nargs="*", type=Path, help="files/dirs (default: inbox)")
    p_run.set_defaults(func=_cmd_run)

    p_ingest = sub.add_parser("ingest", help="new bento from SOURCEs (default: inbox)")
    p_ingest.add_argument("sources", nargs="*", type=Path, help="files/dirs (default: inbox)")
    p_ingest.set_defaults(func=_cmd_ingest)

    p_prepass = sub.add_parser("prepass", help="run the prepass on a bento")
    p_prepass.add_argument("bento", nargs="?", help="bento id/prefix (default: most recent)")
    p_prepass.set_defaults(func=_cmd_prepass)

    p_extract = sub.add_parser("extract", help="type a bento's candidates into nodes")
    p_extract.add_argument("bento", nargs="?", help="bento id/prefix (default: most recent)")
    p_extract.set_defaults(func=_cmd_extract)

    p_merge = sub.add_parser("merge", help="fold a bento's nodes into the graph")
    p_merge.add_argument("bento", nargs="?", help="bento id/prefix (default: most recent)")
    p_merge.set_defaults(func=_cmd_merge)

    p_ls = sub.add_parser("ls", help="list bentos")
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
