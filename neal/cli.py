# The `neal` command -- a thin wrapper over the library.
#
# No logic lives here: each subcommand calls neal.bento / neal.prepass and prints a
# line. The library is the product; the CLI is just a way to drive it.
#
#   neal run [SOURCE...]      ingest then prepass (no SOURCE = the inbox)
#   neal ingest [SOURCE...]   new bento from SOURCEs (default: the inbox)
#   neal prepass [BENTO]      run the prepass on a bento (default: most recent)
#   neal ls                   list bentos

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


def _cmd_ingest(args: argparse.Namespace) -> None:
    _ingest(args.sources)


def _cmd_prepass(args: argparse.Namespace) -> None:
    _prepass(resolve_bento(args.bento))


def _cmd_run(args: argparse.Namespace) -> None:
    _prepass(_ingest(args.sources))


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

    p_run = sub.add_parser("run", help="ingest then prepass in one shot")
    p_run.add_argument("sources", nargs="*", type=Path, help="files/dirs (default: inbox)")
    p_run.set_defaults(func=_cmd_run)

    p_ingest = sub.add_parser("ingest", help="new bento from SOURCEs (default: inbox)")
    p_ingest.add_argument("sources", nargs="*", type=Path, help="files/dirs (default: inbox)")
    p_ingest.set_defaults(func=_cmd_ingest)

    p_prepass = sub.add_parser("prepass", help="run the prepass on a bento")
    p_prepass.add_argument("bento", nargs="?", help="bento id/prefix (default: most recent)")
    p_prepass.set_defaults(func=_cmd_prepass)

    p_ls = sub.add_parser("ls", help="list bentos")
    p_ls.set_defaults(func=_cmd_ls)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except LookupError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
