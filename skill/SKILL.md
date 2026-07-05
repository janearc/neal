---
name: neal
description: Build durable, provenance-tracked story graphs from piles of raw dictated narration. Use when asked to do neal work -- mint a bento from narration sources, build it into a graph (prepass -> extract -> merge), inspect bentos, or continue a lineage with new hours of material. Drives the neal CLI only; the writer curates, neal synthesizes.
---

# neal

neal reads raw dictated narration as one continuous scope and produces a story
graph: typed nodes (character, place, beat, theme, fact, date, quote,
open-puzzle) with provenance back to the exact window of source text. It is
CLI-shaped by design -- there is no daemon; every operation is a subcommand,
and stdout is the product.

The `neal` command is on PATH via delightd's exports (`~/var/bin/neal`, a
symlink to this repo's `bin/neal` shim). If it is missing, delightd's export
sync has not run or the roster row is gone -- that is a finding, not something
to work around by hand.

## Subcommands

| Command | What it does |
|---------|--------------|
| `neal new [--from PARENT] [SOURCE...]` | mint a bento; `--from` continues a lineage with new material |
| `neal build [BENTO]` | run the full pipeline end-to-end (prepass -> extract -> merge) |
| `neal prepass` | deterministic candidate extraction only (wonderlib profiling, no model) |
| `neal extract` | model-confirmed typing of candidates over bounded windows |
| `neal merge` | entity resolution: fold windows into the canonical graph, surface uncertain merges as open-puzzles |
| `neal ls` | list bentos and their state |

## Rules of the road

- The model resolves via delightd discovery and FAILS CLOSED (`ModelUnavailable`)
  -- if delightd is down or nothing healthy serves the model, neal says so and
  stops. Do not retry-loop around it; surface it.
- A build writes a CANDIDATE bento only, never live canon. Promotion into the
  writer's canon is human-in-the-loop and is not this skill's business.
- Corpus content is the operator's private material. Outputs live under the
  bento on disk; nothing is pushed anywhere by this skill.
