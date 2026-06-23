# Interactive curation app

The pipeline produces *weak* (heuristic) labels. The curation app is where a
**human reviewer** turns that raw output into a trustworthy dataset — without
touching the command line beyond one launch command.

```bash
uv sync --extra app          # one-time: install the app dependency
uv run nf-curator app        # opens http://localhost:8501 in your browser
```

Point it at a specific dataset / output location:

```bash
uv run nf-curator app --dataset output/dataset.jsonl --output output
```

## What a reviewer does

1. **Load data** — either open an existing `dataset.jsonl`, or run the pipeline
   straight from the sidebar (including an offline dry-run on the sample data).
2. **Browse** — figures are shown one at a time: the image beside its caption,
   article title, license, and any quality flags.
3. **Correct labels** — if the weak NF-relevance / modality / figure-type label
   is wrong, fix it with the dropdowns. Only changed fields are recorded.
4. **Accept or reject** — one click. The decision saves immediately.
5. **Export** — write the accepted subset to `curated_dataset.jsonl` and
   `curated_dataset.csv` (the CSV opens directly in Excel).

## Decisions are persistent and resumable

Every decision is written to `output/decisions.json` the moment you click. So:

- closing the browser loses nothing — reopen and pick up where you left off;
- re-running the pipeline (which rewrites `dataset.jsonl`) **never clobbers**
  your review work, because decisions live in a separate file keyed by
  `record_id`;
- the weak label and the human correction are both retained — corrections are
  stored as an audit trail (`review.corrections`), so you can always see what a
  reviewer changed and why (`review.notes`).

```jsonc
// output/decisions.json
{
  "PMC9000001:fig1": {
    "status": "accepted",
    "reviewer": "Dr. Smith",
    "decided_at": "2026-06-23T20:15:02+00:00",
    "notes": "clear plexiform neurofibroma on MRI",
    "corrections": { "figure_type": "radiology" }
  }
}
```

## How it fits together

The review logic is in [curation.py](../src/nf_pmc_vl_curator/curation.py) and
is fully unit-tested independently of the UI:

- `DecisionStore` — load/save/update `decisions.json`;
- `apply_decisions(records, store)` — merge decisions + corrections back onto
  records (returns copies; never mutates the inputs);
- `curated_records(records)` — the accepted subset;
- `write_curated(records, dir)` — emit the JSONL + CSV.

[app.py](../src/nf_pmc_vl_curator/app.py) is a thin Streamlit shell over those
functions, so you could build a different front end (notebook, REST API)
against the same curation layer.

## Scripting the same thing without the UI

Because the curation layer is UI-agnostic, you can apply decisions in code too
— handy for reproducible re-exports or programmatic review:

```python
from nf_pmc_vl_curator.curation import (
    DecisionStore, apply_decisions, write_curated, load_dataset,
)
from nf_pmc_vl_curator.models import ReviewStatus

records = load_dataset("output/dataset.jsonl")
store = DecisionStore.load("output/decisions.json")
store.decide("PMC9000001:fig1", ReviewStatus.ACCEPTED, reviewer="batch")
store.save()

write_curated(apply_decisions(records, store), "output")
```
