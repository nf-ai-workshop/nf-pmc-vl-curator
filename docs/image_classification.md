# Image-based modality classification (Claude vision)

The caption-keyword annotator labels modality from *text* — but many PMC figure
captions don't describe the image, so those labels are often `unknown` or wrong.
The optional **`ImageModalityAgent`** fixes this by classifying from the
**pixels** with a Claude vision model and **structured outputs**, so every
result is a valid label from the controlled vocabulary (never free text).

## Run it

```bash
uv sync --extra vision                 # one-time: install the anthropic SDK
export ANTHROPIC_API_KEY=sk-ant-...    # your key
uv run nf-curator run --retmax 20 --classify-images --email you@inst.edu
# --vision-model claude-sonnet-4-6     # optional: more accuracy
```

`--classify-images` implies `--assets` (it needs the downloaded images). It is a
networked-only step — dry-run/offline runs skip it.

## What it produces

For each figure with a downloaded image, the agent fills
`annotations.image_modality` with:

```jsonc
"image_modality": {
  "modality": "ct",              // mri|ct|ultrasound|xray|pet|histology|
                                 //   clinical_photo|illustration|chart|unknown
  "figure_type": "radiology",
  "is_multipanel": true,         // PMC figures are often composites
  "confidence": 0.82,
  "rationale": "axial CT slices of the abdomen",
  "model": "claude-haiku-4-5"
}
```

The caption-derived `modality`/`figure_type` are **kept alongside** it, so you
can compare. When the two disagree, the quality agent raises a
`modality_disagreement` flag (advisory) — a strong signal for the curation app
to surface that figure for human review. `materialize` adds `image_modality`,
`image_figure_type`, `image_modality_confidence`, and `is_multipanel` columns to
`metadata.jsonl`.

## Why this design

- **Structured outputs** (`output_config.format` with a JSON-schema enum) make
  the label space a hard constraint — the model can only return a valid class.
- **Cheap.** A figure is ~1–1.5K input tokens, so ~100 images ≈ **$0.15** on
  `claude-haiku-4-5` ($1/$5 per Mtok). Use `--vision-model claude-sonnet-4-6`
  ($3/$15) or `claude-opus-4-8` for harder cases. Images are downscaled to a
  1568px long edge before sending to keep token cost down.
- **Best-effort.** A per-image failure is logged and skipped, never aborting the
  run; the figure simply keeps its caption-derived label.
- **Pluggable.** The agent ([image_modality.py](../src/nf_pmc_vl_curator/agents/image_modality.py))
  is UI/pipeline-agnostic and accepts an injected client, so it's unit-tested
  without any network.

## Scaling tips

- For large corpora, batch the classifications through the **Message Batches
  API** (50% cheaper, async) — the per-image `classify()` call is the unit to
  wrap.
- The vision labels are weak supervision: once you have a few thousand, you can
  **distill** them into a small local image classifier for offline labeling.

## Programmatic use

```python
from nf_pmc_vl_curator.agents.image_modality import ImageModalityAgent

agent = ImageModalityAgent(model="claude-haiku-4-5")  # reads ANTHROPIC_API_KEY
result = agent.classify("cache/PMC.../assets/fig1.jpg", caption="...")
print(result.modality, result.confidence)
```
