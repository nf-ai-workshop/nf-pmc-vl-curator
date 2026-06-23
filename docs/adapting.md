# Adapting the pipeline to a different biomedical topic

The pipeline hard-codes **no disease terms in the code**. Everything
topic-specific lives in two places:

1. the **search query** (config), and
2. the **annotation keyword vocabulary**
   ([resources/annotation_keywords.yaml](../src/nf_pmc_vl_curator/resources/annotation_keywords.yaml)).

Below is the full recipe, using *melanoma dermoscopy* as a worked example.

## Step 1 — Change the search query

Point the search at your topic, keeping `open access[filter]` so you stay
inside the OA subset. In your config YAML:

```yaml
search:
  query: >-
    (melanoma[Title/Abstract] OR dermoscopy[Title/Abstract])
    AND open access[filter]
  retmax: 50
  mindate: "2015"
```

Tips for a good query:
- search field tags like `[Title/Abstract]`, `[MeSH Terms]` sharpen recall;
- always keep `AND open access[filter]`;
- test it first in the [PMC search UI](https://www.ncbi.nlm.nih.gov/pmc/) — the
  same query string works there.

## Step 2 — Retarget the annotation keywords

Copy the bundled YAML and edit the four sections. Pass it via
`keywords_path` in config or `nf-curator annotate --keywords <file>`.

```yaml
# 2a. Topic relevance. Rename/replace the two buckets. The code reads whatever
#     keys live under nf_relevance: the first bucket -> first label, etc.
#     (To rename the *labels* themselves, edit the NFRelevance enum in models.py.)
nf_relevance:
  nf1:                      # reinterpret as e.g. "primary melanoma"
    - melanoma
    - malignant melanoma
  nf2:                      # reinterpret as e.g. "metastatic"
    - metastatic melanoma

# 2b. Imaging modality. Add/remove modalities relevant to your domain.
modality:
  dermoscopy:
    - dermoscopy
    - dermoscopic
    - polarized light
  histology:
    - h&e
    - micrograph

# 2c. Modality -> coarse figure-type grouping.
figure_type_map:
  dermoscopy: clinical_photo
  histology: histopathology

# 2d. Entities of interest (free-form).
entities:
  - asymmetric pigment network
  - blue-white veil
  - regression structures
```

Add any new modality/figure-type values to the `Modality` / `FigureType`
enums in [models.py](../src/nf_pmc_vl_curator/models.py) — Pydantic validates
against them, so an unmapped string would raise. (Keeping the label space in
an enum is the price of catching typos early.)

## Step 3 — Tune quality thresholds (optional)

```yaml
quality:
  min_caption_length: 40
  drop_not_nf_relevant: true   # keep only on-topic figures
  require_image_file: true     # require a downloaded image
```

## Step 4 — Iterate on the keywords offline

Use the `annotate` command to tune vocabulary against real captions without
re-running the whole pipeline:

```bash
uv run nf-curator annotate \
  --keywords my_keywords.yaml \
  "Dermoscopic image showing a blue-white veil and atypical network"
```

Then dry-run over a handful of XML files you've already cached:

```bash
uv run nf-curator run --xml cache/PMC*/PMC*.xml --keywords my_keywords.yaml \
  --output /tmp/preview
uv run nf-curator inspect /tmp/preview/dataset.jsonl
```

## Step 5 — Run for real

```bash
uv run nf-curator run --config config/melanoma.yaml --email you@example.com
```

## What you should *not* need to touch

- `search.py`, `oa_checker.py`, `downloader.py`, `extractor.py` — these are
  disease-agnostic (E-utilities + JATS are the same regardless of topic).
- `quality.py`, `exporter.py` — generic.
- `pipeline.py`, `cli.py`, `http_client.py` — infrastructure.

If you find yourself editing those for a topic change, that's a smell — push
the topic-specific knowledge back into config + keywords instead.

## Honoring licenses when you redistribute

Each record keeps its source article's `license`. CC BY / BY-SA / BY-NC etc.
all require attribution; `CC0` does not. If you publish a derived dataset,
carry the per-image license forward and attribute the source article
(`article.doi` / `article.pmcid` are right there in every record).
