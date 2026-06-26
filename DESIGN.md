# neal: narration in, a story graph out

> RESEARCH. A birb named for the right reverend Stephenson, his holiness of verbosity.
> neal reads a pile of raw dictated narration held as **one big scope** and breaks it out
> into a durable, provenance-tracked **story graph** -- characters, places, beats, themes,
> facts, dates -- so a writer can compose from notes instead of re-synthesizing dozens of
> hours of rambling by hand every time. neal is the note-taker and the synthesizer-of-
> record. It does **not** write. The writer writes.

## What it does

A run is a bento. Audio is already text by the time neal sees it (transcribed upstream by
magpie/turtledove and/or on-device voice memos); neal's inbox takes **raw text**:

```
~/var/neal/inbox/                      drop transcripts here
~/var/neal/bentos/<uuid>/
  raw_data/                            the source narration, copied in (never moved)
  outputs/
    graph/                             the durable artifact: nodes.jsonl, edges.jsonl
    cards/                             the projection: character/place/beat/... markdown
    render/                            the story-bible PDF + its source .dot/.mmd/.typ
  manifest.json                        what ran, which backend, per-stage stats
```

You submit intent (a corpus of narration treated as continuous); neal owns the
extraction. The corpus is **incremental** -- add ten more hours next month, re-run, merge
into the same scope. That is the thing the hand-built vim+git rig could never do: it made
you redo the whole synthesis by hand every time.

### The node taxonomy

The graph's node kinds mirror a hand-built screenplay notes tree (a `characters/` dir, an
`outlines/` dir, a `FACTS.md`), because that schema was already correct -- neal just
populates it from the corpus instead of from a tired human at midnight:

- `character`, `place`, `beat`, `theme`, `fact`, `date` (timeline-event)
- `quote` -- verbatim gold; carried exactly, never paraphrased (the lines are load-bearing)
- `open-puzzle` -- a surfaced unknown (a fuzzy date, an unresolved location). neal
  **surfaces** these; it does not resolve them by guessing.

Every node and edge carries **provenance** (which transcript, which span), a
**confidence**, an explicit `UNKNOWN` when the corpus is silent, and **which backend
produced it**. This is the load-bearing import from the corpus's own canon discipline: if
a claim is not in a transcript, it is UNKNOWN -- flag it, do not invent it. Invented
details laundered into canon is the exact failure this guards against.

## The engine: small-window-native, iterate to convergence

The constraint and the innovation are one object. Apple's on-device stack is phenomenal
but has an itty-bitty context window; mistral-24b has a bigger one but gets dumber and
more hallucinatory the further you stuff it. So neal never asks a model to "read 35k words
and give me the characters." It is built around small windows from the first line:

1. **Deterministic prepass, no model (reuse `wonderlib`).** `wonderlib.markdown_xml`
   converts narration to structured XML and unwraps it; `wonderlib.profiling` computes
   Zipf + POS rarity and extracts **rare terms**, which become the **node vocabulary**.
   The model never starts from a blob -- it starts from a sparse candidate graph derived
   from corpus signal, not a hardcoded lexicon. (See "wonderlib" below.)

2. **Bounded extraction over one small window at a time.** The model only confirms, types,
   attributes, and merges candidates the prepass already proposed. That job fits in a
   thimble, so the *same engine* runs whether the backend is mistral or a tiny-tummy Apple
   model. Build for the small tummy and the chonky girl benefits too.

3. **Iterate to convergence, not one-shot** (the principle re-derived from paling's
   flan-era loop, not cloned). Run a pass, fold results into the corpus graph, re-visit
   windows whose neighborhood changed; stop when a full pass adds nothing new. Convergence
   is the stopping condition. No single call holds the scope -- the *graph* holds it, and
   it is durable between iterations. That is how a small window reasons about one big
   scope.

4. **Merge into the whole.** Entity resolution folds co-mentions into one node
   (e.g. a misheard place-name and its correct spelling become one place). Late synthesis
   may use the bigger model over more context to write the card prose, grounded strictly
   by the graph.

## Backends: honestly gated, per-chunk (the empirical part)

neal reaches models the good-citizen way (below), and bakes off two text backends exactly
like turtledove's cleanup stage:

- **Apple on-device (AFM) -- the fast path.** Tiny tummy, ~free, private, fast.
- **mistral-24b dolphin (uncensored) -- the chonky fallback.** Eats anything, won't flinch.

The gate is **measured, not assumed.** Running real corpus windows through AFM
(2026-06-25): suicidal-ideation narration, florid psychosis, profanity, and gory *fiction*
all processed fine. The hard wall is specifically **sexual content (and likely graphic
gore)**, and it is not a soft "I'm sorry, I can't" -- it is a thrown
`GuardrailViolationError`. That is the cleanest possible signal: an exception, not brittle
string-matching. So the gate is **per-chunk, not per-corpus** -- the bulk of windows ride
AFM's fast path; only the chunks that actually trip the guardrail gate down to
mistral-dolphin, and the manifest records which ones and why. Apple's speed on ~90% of the
corpus; the uncensored model only where she is genuinely needed.

## Mesh-native (not standalone)

Unlike turtledove (deliberately off-mesh, mistral the old-fashioned way), neal is a proper
**good-citizen birb**. By the time neal moves to production the mesh is green and there are
no old-timey pipelines, so neal is built for that world: it emits the bento lifecycle to
the bus, resolves models via **delightd discovery**, and reaches both mistral and the
Apple capability via the **good-citizen model client** -- it never links Swift and never
imports a provider's internals. The host-local Apple capability provider (one calm bouncer
per chip; see `apple-silicon-capability-provider.md`) is exactly the backend neal consumes
for the AFM fast path, and neal honors its retryable-busy signal (yield to the bus, never
fake a result). During research neal may call mistral directly as a bootstrap, but that is
scaffolding, not the design.

## wonderlib (dependency, not a clone)

paling has two layers with different reuse verdicts. **wonderlib** -- the decoupled,
corpus-agnostic library (`markdown_xml`, `profiling` = Zipf/POS rarity -> rare-terms,
`git_stats`) -- is neal's deterministic prepass. neal **depends on it**; re-deriving it
would be the actual sin. It is a *library*, not a pipeline, so leaning on it does not touch
the no-pipeline-calls-another rule. paling's `bento.py` orchestration (it mints
training-data Q/A pairs) is the part that is "different stuff" -- neal builds a story graph,
not a training set -- so neal takes only the *convergence principle* and writes its own
orchestration fresh. **Open decision:** pin wonderlib as a dependency vs. vendor a slice.

## Rendered views: the story-bible PDF

A thing the writer can print, spread on a table, and mark up -- the load-off-your-head
payoff made physical. The graph (`nodes.jsonl`/`edges.jsonl`) stays the source of truth;
**render is a projection**, a `render` stage that is a sibling of `cards`, gated behind the
graph, adding no new core. The "lovely" comes from **curated views, each answering one
question -- never one mega-graph** (a full graph in auto-layout is an unreadable hairball
past ~30 nodes). Right tool per view:

- **Relationship map** (who's tied to whom, who's where) -- a genuinely dense graph, so
  **Graphviz/DOT** (`dot -Tpdf`): better dense layout than Mermaid, color/shape by
  node-kind, edge style by confidence, `UNKNOWN` flagged visually.
- **Chronology** -- a **Mermaid `timeline`** (or `gantt` for intercut tracks) from the
  `date` nodes; Mermaid is good here because timelines are linear, not tangled.
- **Themes** -- an optional Mermaid `mindmap`.
- **Cards** -- the character/beat/fact prose, as above.

**Assemble** cards + diagrams into one bound PDF via **Typst** (no LaTeX yak-shave) or
pandoc. Render deps are dev tooling -- they stay out of git, same as the venvs. Each view
carries provenance, and `UNKNOWN` / `open-puzzle` nodes render *as* open questions: the map
shows you what you don't yet know. **Open:** which assembler (Typst vs pandoc), and whether
render is its own bento stage or a separate `neal render <bento>` command.

**The renderer is corpus-agnostic -- it belongs in `wonderlib`, not neal.** It takes
`nodes.jsonl` + `edges.jsonl` -> DOT/Mermaid and does not care whether the nodes are
characters or concepts. So it lives next to `profiling` as shared substrate, and **paling
reuses it too** -- there, the same map is a *diagnostic* surface (eyeball the graph it
already builds: orphan nodes, bad rare-term promotions, clusters that should have merged)
rather than a deliverable. Build the renderer once; neal projects a story bible, paling
debugs its extraction. (paling is outside this repo -- propose, don't touch, without a go.)

## Compartmentalization & the canon boundary

- neal calls **no other pipeline**. wonderlib is a library dependency (allowed).
- neal writes a **candidate** extraction bento under `~/var/neal`. It does **not** write
  into the live screenplay canon (`FACTS.md`, `characters/`). The writer curates what gets
  promoted. This keeps the machine from laundering an invented detail into ground truth --
  the precise thing the canon file exists to stop -- and respects the rule: neal
  synthesizes, the writer writes.

## What is DONE

- Nothing built yet. This is the design, settled across one session: the inbox/bento
  contract, the node taxonomy, the small-window + iterate-to-convergence engine, the
  wonderlib-reuse seam, the measured AFM guardrail gate, the mesh-native good-citizen
  posture, and the candidate-bento-never-canon boundary.
- **Recon banked:** paling's technique and the wonderlib seam (read-only, not cloned); the
  AFM guardrail bake-off above (the sex/gore wall is a real `GuardrailViolationError`).

## What is NOT wired / open (honest)

- **The convergence heuristics** -- exact stopping condition, re-visit policy, and the
  per-window prompt shape -- want building and measuring (the flan loop is the starting
  point, not the final tuning).
- **Entity resolution / merge** across a long corpus (misheard names, aliases, one person
  under three spellings) is the hard correctness work; get it wrong and the graph lies.
- **Date anchoring.** Dates want pinning to external receipts (calendar/weather/press), not
  just the narration, which misremembers. neal should *surface* the conflict as an
  `open-puzzle`, never silently pick one.
- **wonderlib pin vs. vendor** (above).
- **Mesh wiring** -- bus lifecycle + delightd discovery + the capability-provider client
  path -- is the same pending step every birb carries; bootstrapped directly during
  research.
- **The promotion workflow** -- how a curated card graduates from neal's candidate bento
  into the writer's canon -- is human-in-the-loop by design and not neal's job to automate.
