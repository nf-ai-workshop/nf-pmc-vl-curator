# Architecture

The pipeline is a linear chain of seven "agent" modules plus an orchestrator.
Each agent is a plain Python class with one public method, a typed input and a
typed output. Nothing in an agent knows about the agent before or after it —
the [orchestrator](../src/nf_pmc_vl_curator/pipeline.py) is the only component
that knows the order. This makes every stage independently testable and easy
to reason about, which is exactly the property you want when an automated
agent assembles or modifies the pipeline.

```
                 ┌─────────────┐
   topic query ─▶│ SearchAgent │─▶ [ArticleRef]            (E-utilities esearch/esummary)
                 └─────────────┘
                        │
                        ▼
              ┌──────────────────────┐
              │ OAAvailabilityAgent  │─▶ {pmcid: OARecord} (oa.fcgi; drops non-OA)
              └──────────────────────┘
                        │
                        ▼
                ┌───────────────┐
                │ DownloadAgent │─▶ XML path + image assets (efetch + OA .tar.gz)
                └───────────────┘
                        │
                        ▼
            ┌────────────────────────┐
            │ FigureExtractionAgent  │─▶ [Figure]          (JATS XML parsing)
            └────────────────────────┘
                        │
                        ▼
               ┌─────────────────┐
               │ AnnotationAgent │─▶ WeakAnnotations       (keyword heuristics)
               └─────────────────┘
                        │
                        ▼
                ┌──────────────┐
                │ QualityAgent │─▶ QualityReport per record (+ keep/drop)
                └──────────────┘
                        │
                        ▼
                ┌─────────────┐
                │ ExportAgent │─▶ dataset.jsonl + summary.json
                └─────────────┘
```

## The data contract

Stages communicate exclusively through the Pydantic models in
[models.py](../src/nf_pmc_vl_curator/models.py). The export unit is
`FigureRecord`, which bundles everything known about one figure:

```
FigureRecord
├── record_id            "<pmcid>:<fig_id>"
├── article: ArticleRef  pmid / pmcid / doi / title / journal / year
├── figure: Figure       fig_id / label / caption / graphic_href / local_image_path
├── license: LicenseInfo code / url / requires_attribution / raw
├── annotations: WeakAnnotations
│   ├── nf_relevance (+ score), modality, figure_type
│   ├── entities[]       matched lesion/entity keywords
│   └── matched_terms{}  audit trail: which terms fired which label
├── quality: QualityReport   flags[] + passed
└── provenance{}         search_query, source_xml, package_url, timestamps, tool_version
```

Because both the networked and offline paths build the *same* `FigureRecord`,
their outputs are schema-identical (a test asserts this).

## Stage notes

### 1. SearchAgent
Queries the **pmc** E-utilities database (not `pubmed`) so hits are already
PMC records, and folds `open access[filter]` into the query. `esearch` returns
PMC UIDs; `esummary` enriches them into `ArticleRef`s (title, journal, DOI,
PMID, year). We never touch PubMed or publisher HTML.

### 2. OAAvailabilityAgent
Calls the PMC **OA Web Service** (`oa.fcgi`) per article. A `<record>` means
the article is in the OA subset and yields its `license` attribute and the
`.tar.gz` package URL; an `<error>` means it is not OA and the article is
dropped. License strings are normalised to canonical CC codes + URLs.

### 3. DownloadAgent
Two cached fetches: the full-text XML via `efetch` (the parse source), and the
figure images by downloading + extracting the OA `.tar.gz` package (the only
sanctioned bulk source for OA figure files). Each `Figure.graphic_href` is
matched to an extracted image by basename. Everything is cached on disk keyed
by PMCID so re-runs are cheap and reproducible.

### 4. FigureExtractionAgent
Parses JATS/NLM XML. PMC serves slightly different DTD versions and uses XML
namespaces (`xlink` for `<graphic xlink:href>`), so the parser matches on
*local* element names and any attribute whose local name is `href`. Also
extracts a fallback license from `<permissions><license>` so offline-curated
records still carry license metadata.

### 5. AnnotationAgent
Keyword/regex heuristics over the caption (and article title for NF-relevance
context). All vocabulary lives in
[resources/annotation_keywords.yaml](../src/nf_pmc_vl_curator/resources/annotation_keywords.yaml).
Labels are deliberately **weak** — a starting point for filtering or
active-learning, not ground truth — and every label records which terms fired
it in `matched_terms`.

### 6. QualityAgent
Raises flags (`MISSING_CAPTION`, `SHORT_CAPTION`, `MISSING_IMAGE`,
`MISSING_LICENSE`, `NOT_NF_RELEVANT`, `NO_MODALITY`, `DUPLICATE_CAPTION`) and
decides `passed` per the configured policy. Duplicate detection needs the whole
batch, so this agent operates on the full record list.

### 7. ExportAgent
Writes `dataset.jsonl` (passing records), optionally `rejected.jsonl`, and a
`summary.json` with distributions by NF relevance / modality / figure type /
license plus a flag histogram.

## The network choke point
Every outbound request goes through
[http_client.py](../src/nf_pmc_vl_curator/http_client.py), which enforces
client-side rate limiting, retries transient failures with backoff, attaches
the NCBI `tool`/`email`/`api_key` identity, and — when `dry_run=True` — raises
`DryRunError` on any network attempt. One choke point makes the pipeline easy
to mock in tests and easy to audit for the "no scraping" constraint.
