# nf-pmc-vl-curator

An **educational example** of a reproducible biomedical *vision-language*
dataset curation pipeline, built the way a coding agent might decompose the
task: a chain of small, single-responsibility "agent" modules, each with a
typed input and output.

The concrete goal: given a topic (here, **neurofibromatosis type 1 / type 2**),
search **PMC Open Access**, download article XML + figure assets, extract
**figure-caption pairs**, attach **weak annotations** (NF relevance, imaging
modality, figure type, lesion/entity keywords), run **quality checks**, and
export a **figure-level image-caption dataset as JSONL** — with **license and
provenance preserved for every image**.

> This repo is a teaching artifact. The bundled sample articles under
> [data/sample/](data/sample/) are **synthetic** (fabricated `PMC9000xxx`
> IDs), so the pipeline runs fully offline with zero network access.

---

## Why "agent" modules?

The pipeline is deliberately split into seven inspectable stages. Each is a
class with one job, no knowledge of its neighbors, and its own unit tests —
the same decomposition a coding agent uses to make a fuzzy task tractable.

```
SearchAgent ─▶ OAAvailabilityAgent ─▶ DownloadAgent ─▶ FigureExtractionAgent
       └────────────▶ AnnotationAgent ─▶ QualityAgent ─▶ ExportAgent ─▶ dataset.jsonl
```

| Stage | Module | Responsibility |
|------|--------|----------------|
| 1 | [search.py](src/nf_pmc_vl_curator/agents/search.py) | Find candidate articles via PMC E-utilities `esearch`/`esummary` |
| 2 | [oa_checker.py](src/nf_pmc_vl_curator/agents/oa_checker.py) | Confirm Open Access; capture license + package URL (`oa.fcgi`) |
| 3 | [downloader.py](src/nf_pmc_vl_curator/agents/downloader.py) | Fetch article XML (`efetch`) + figure images (OA `.tar.gz`) |
| 4 | [extractor.py](src/nf_pmc_vl_curator/agents/extractor.py) | Parse JATS XML into figure/caption pairs |
| 5 | [annotator.py](src/nf_pmc_vl_curator/agents/annotator.py) | Weak labels: NF relevance, modality, figure type, entities |
| 6 | [quality.py](src/nf_pmc_vl_curator/agents/quality.py) | Quality flags + keep/drop policy |
| 7 | [exporter.py](src/nf_pmc_vl_curator/agents/exporter.py) | Write JSONL + summary stats |

The [pipeline.py](src/nf_pmc_vl_curator/pipeline.py) orchestrator wires them
together. See [docs/architecture.md](docs/architecture.md) for the detailed walk-through.

---

## Quickstart (uses `uv`)

```bash
# 1. install (creates .venv, resolves deps from pyproject.toml)
uv sync --extra dev

# 2. run fully offline on the bundled synthetic sample data — no network
uv run nf-curator run --dry-run --output output

# 3. inspect what you produced
uv run nf-curator inspect output/dataset.jsonl
cat output/summary.json
```

Run the **real** pipeline against live PMC (be a good citizen — supply your
email; NCBI asks every client to identify itself):

```bash
uv run nf-curator run --retmax 20 --assets --email you@example.com --output output
# add --api-key XXXX to raise the rate limit from 3 to 10 req/s
```

**No login or API key is required** — the PMC Open Access subset is public.
To confirm your machine can actually reach PMC and download figure images,
run the built-in diagnostic (it exercises search → OA → XML → image download):

```bash
uv run nf-curator doctor --email you@example.com
```

See [docs/network_access.md](docs/network_access.md) for what access info to
provide, proxy/firewall notes, and the 2026 NCBI dataset-migration caveat.

### CLI commands

```bash
uv run nf-curator run        # run the pipeline (networked, or --dry-run / --xml for offline)
uv run nf-curator doctor     # diagnose live connectivity incl. image download
uv run nf-curator materialize  # package dataset.jsonl into an imagefolder (images/ + metadata.jsonl)
uv run nf-curator app        # launch the interactive curation web app (see below)
uv run nf-curator inspect    # summarise an exported dataset.jsonl
uv run nf-curator extract    # parse one JATS XML file and list its figures
uv run nf-curator annotate   # weak-annotate an ad-hoc caption (great for tuning keywords)
```

### Interactive curation app (for researchers, no terminal beyond launch)

The pipeline emits *weak* labels; a human turns them into a trustworthy
dataset. The web app makes that point-and-click:

```bash
uv sync --extra app          # one-time: install the app dependency
uv run nf-curator app        # opens http://localhost:8501
```

In the browser you can load a dataset (or run the pipeline from the sidebar),
**browse each figure with its image beside the caption**, fix wrong labels,
**accept/reject** figures, and export the approved subset to JSONL + CSV.
Decisions persist to `decisions.json` so review is **resumable** and survives
re-running the pipeline. Full guide: [docs/curation_app.md](docs/curation_app.md).

Example — tune annotation keywords interactively:

```bash
uv run nf-curator annotate "T1-weighted MRI of a plexiform neurofibroma in NF1"
```

---

## MVP constraints (and where they're enforced)

- **PMC Open Access only** — `OAAvailabilityAgent` drops non-OA articles;
  search query includes `open access[filter]`.
- **No scraping of PubMed / publisher HTML** — only the documented E-utilities
  and PMC OA service are called (`HTTPClient` is the single network choke point).
- **Provenance + license for every image** — each `FigureRecord` carries a
  `license` block and a `provenance` block (source XML, package URL, query,
  timestamps, tool version).
- **Figure-level image-caption pairs** — the export unit is one figure.
- **Weak annotations** — NF1/NF2 relevance, modality, figure type, entities.
- **Quality flags** — see [quality.py](src/nf_pmc_vl_curator/agents/quality.py).
- **CLI** — `nf-curator`.
- **Dry-run mode** — `--dry-run` makes network calls raise immediately and
  curates local XML instead.

---

## Tests

```bash
uv run pytest
```

All tests run **offline** against the synthetic sample data and inline
fixtures, so the suite is deterministic and network-free.

---

## Adapt this to a different topic

The code hard-codes **no disease terms**. Retargeting to, say, *melanoma
dermoscopy* is mostly editing the search query and the keyword YAML — see
[docs/adapting.md](docs/adapting.md).

## Documentation

- [docs/architecture.md](docs/architecture.md) — how each agent module works
- [docs/network_access.md](docs/network_access.md) — access info + how to test live image retrieval
- [docs/curation_app.md](docs/curation_app.md) — the interactive human-in-the-loop curation app
- [docs/building_image_dataset.md](docs/building_image_dataset.md) — turn `dataset.jsonl` into an imagefolder of actual images + annotations
- [docs/data_schema.md](docs/data_schema.md) — the JSONL record schema
- [docs/adapting.md](docs/adapting.md) — adapt to a new biomedical topic

## Project layout

```
src/nf_pmc_vl_curator/
  agents/          # the seven pipeline stages
  resources/       # annotation_keywords.yaml (the tunable vocabulary)
  models.py        # typed Pydantic data models (the inter-stage contract)
  config.py        # typed, file-backed configuration
  http_client.py   # rate-limited, retrying, dry-run-aware HTTP wrapper
  pipeline.py      # orchestrator (networked + offline entry points)
  curation.py      # human-in-the-loop layer (DecisionStore, persisted reviews)
  materialize.py   # package dataset.jsonl into a HF imagefolder (images + metadata)
  app.py           # Streamlit curation web app (UI shell over curation.py)
  cli.py           # the nf-curator command-line interface
data/sample/       # SYNTHETIC sample JATS XML (offline runs + tests)
config/            # example YAML config
docs/              # architecture, schema, adaptation guide
tests/             # pytest suite (runs offline)
```
