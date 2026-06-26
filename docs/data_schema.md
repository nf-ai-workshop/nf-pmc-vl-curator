# Dataset schema

The exporter writes `dataset.jsonl` — one JSON object per line, each a
`FigureRecord`. The canonical definition is the Pydantic model in
[models.py](../src/nf_pmc_vl_curator/models.py); this page is the
human-readable summary.

## One record (annotated example)

```jsonc
{
  "record_id": "PMC9000001:fig1",          // unique: "<pmcid>:<fig_id>"
  "article": {
    "pmid": "90000001",
    "pmcid": "PMC9000001",
    "doi": "10.0000/synthetic.9000001",
    "title": "Imaging of plexiform neurofibroma ...",
    "journal": "Journal of Synthetic Neurocutaneous Disorders",
    "pub_year": 2021
  },
  "figure": {
    "fig_id": "fig1",
    "label": "Figure 1",
    "caption": "Contrast-enhanced T1-weighted axial MRI showing ...",
    "graphic_href": "9000001_fig1.jpg",     // image filename in the OA package
    "local_image_path": "cache/PMC9000001/assets/9000001_fig1.jpg"  // or null
  },
  "license": {
    "code": "CC BY",
    "url": "https://creativecommons.org/licenses/by/4.0/",
    "requires_attribution": true,
    "raw": "CC BY"
  },
  "annotations": {
    "nf_relevance": "nf1",                   // nf1 | nf2 | both | none | unknown
    "nf_relevance_score": 0.9,               // 0..1 confidence
    "modality": "mri",                       // mri|ct|ultrasound|xray|pet|histology|
                                             //   clinical_photo|illustration|chart|unknown
    "figure_type": "radiology",              // radiology|histopathology|clinical_photo|
                                             //   diagram|chart|mixed|unknown
    "entities": ["plexiform neurofibroma"],  // matched lesion/entity keywords
    "matched_terms": {                       // audit trail: term -> label
      "nf_caption": ["nf1", "neurofibromatosis type 1"],
      "modality:mri": ["mri", "t1-weighted", "contrast-enhanced"],
      "entities": ["plexiform neurofibroma"]
    },
    "image_modality": {                      // null unless --classify-images (Claude vision)
      "modality": "mri", "figure_type": "radiology",
      "is_multipanel": false, "confidence": 0.9,
      "rationale": "T1-weighted axial MRI", "model": "claude-haiku-4-5"
    }
  },
  "quality": {
    "flags": [],                             // see QualityFlag enum
    "passed": true
  },
  "review": {                                // null until a human reviews it
    "status": "accepted",                    // pending | accepted | rejected
    "reviewer": "Dr. Smith",
    "decided_at": "2026-06-23T20:15:02+00:00",
    "notes": "clear plexiform neurofibroma",
    "corrections": { "figure_type": "radiology" }  // human label edits (audit)
  },
  "provenance": {
    "search_query": "(neurofibromatosis ...) AND open access[filter]",
    "source_xml": "cache/PMC9000001/PMC9000001.xml",
    "package_url": "ftp://ftp.ncbi.nlm.nih.gov/.../PMC9000001.tar.gz",
    "oa_retrieved_at": "2026-06-23T20:01:12+00:00",
    "tool_version": "0.1.0"
  }
}
```

## Field reference

| Field | Type | Notes |
|-------|------|-------|
| `record_id` | string | `"<pmcid>:<fig_id>"`, globally unique |
| `article.*` | strings/int | bibliographic reference; any field may be null |
| `figure.caption` | string | plain text, whitespace-normalised |
| `figure.graphic_href` | string\|null | image filename referenced in the JATS XML |
| `figure.local_image_path` | string\|null | set once the asset is downloaded |
| `license.code` | string | canonical CC code, or `"unknown"` |
| `license.requires_attribution` | bool | false only for `CC0` |
| `annotations.*` | see enums | weak (heuristic) labels |
| `quality.flags` | string[] | machine-checkable issues |
| `quality.passed` | bool | whether the record passed automated checks |
| `review` | object\|null | human-in-the-loop decision (null until reviewed) — see [curation_app.md](curation_app.md) |
| `provenance.*` | strings\|null | full reproduction trail |

## Quality flags

| Flag | Meaning | Fatal? |
|------|---------|--------|
| `missing_caption` | empty caption | always |
| `duplicate_caption` | caption already seen in this batch | always |
| `missing_license` | no license metadata | if `require_license` |
| `missing_image` | no image href / no downloaded file | if `require_image_file` |
| `not_nf_relevant` | NF relevance = none | if `drop_not_nf_relevant` |
| `short_caption` | caption shorter than `min_caption_length` | advisory |
| `no_modality` | modality = unknown | advisory |

`dataset.jsonl` contains only records with `passed = true`. Rejected records
(when any) are written to `rejected.jsonl` for inspection. `summary.json`
holds aggregate counts.

## Working with the dataset

```python
import json
from nf_pmc_vl_curator.models import FigureRecord

with open("output/dataset.jsonl") as fh:
    records = [FigureRecord.model_validate_json(line) for line in fh if line.strip()]

mri = [r for r in records if r.annotations.modality.value == "mri"]
```
