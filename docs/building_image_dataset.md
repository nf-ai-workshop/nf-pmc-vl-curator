# From `dataset.jsonl` to an image dataset

`dataset.jsonl` is an **index**: it records captions, weak labels, license and
provenance, and points at each figure's image via `figure.local_image_path` —
but those images live in the (git-ignored, ephemeral) download `cache/`. The
`materialize` step turns that index into a **self-contained, portable image
dataset** you can train on or share.

## Run it

```bash
# default: read output/dataset.jsonl -> write ./dataset/
uv run nf-curator materialize

# explicit paths / options
uv run nf-curator materialize output/dataset.jsonl --output dataset \
    --image-format keep          # jpg/png copied; gif/tif -> png
# --accepted-only                 # only figures you ACCEPTED in the curation app
# --image-format jpg|png          # force everything to one format
```

## What you get (HuggingFace `imagefolder` layout)

```
dataset/
  images/
    PMC13280527_f1-ol-32-2-15695.jpg
    PMC13284643_F1.jpg
    ...
  metadata.jsonl      # one row per image
  README.md           # auto-generated data card
```

Each `metadata.jsonl` row pairs the image with its **language annotation**
(the caption) plus the weak structured labels:

```json
{
  "file_name": "images/PMC13280527_f1-ol-32-2-15695.jpg",
  "record_id": "PMC13280527:f1-ol-32-2-15695",
  "caption": "Contrast-enhanced T1-weighted MRI showing ...",
  "nf_relevance": "nf1", "modality": "mri", "figure_type": "radiology",
  "entities": ["plexiform neurofibroma"],
  "pmcid": "PMC13280527", "doi": "10.x/y", "license": "CC BY"
}
```

`file_name` is the column the imagefolder loader keys on, so the dataset loads
with no extra config:

```python
from datasets import load_dataset

ds = load_dataset("imagefolder", data_dir="dataset")
ex = ds["train"][0]
ex["image"]        # a PIL.Image (decoded from images/…)
ex["caption"]      # the language annotation
ex["modality"], ex["entities"]   # weak labels as columns
```

## Image normalisation

- `.jpg` / `.png` are copied byte-for-byte.
- other formats (`.gif` thumbnails, `.tif`, …) are converted with Pillow —
  to PNG by default, or to whatever `--image-format` you pass. JPEG output is
  converted to RGB (JPEG has no alpha/palette).

## Recommended flow

1. `nf-curator run --assets …` → `output/dataset.jsonl` (+ cached images)
2. `nf-curator app` → review/correct/accept figures (writes `decisions.json`)
3. `nf-curator materialize --accepted-only` → a curated, human-approved
   image-caption dataset in `dataset/`

## Licensing reminder

Images carry their source article's license (preserved per row). CC BY/BY-NC/…
require attribution to the source article (`doi`/`pmcid` are in every row);
CC0 does not. Honor these when you redistribute the materialized dataset.
"""
