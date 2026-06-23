# Synthetic sample data

These JATS XML files are **fabricated** for testing and demonstration. They are
not real publications and the `PMC9000xxx` accession IDs do not exist in PMC.

They let the pipeline run end-to-end fully offline (`nf-curator run --dry-run`)
and back the deterministic, network-free test suite.

| File | Topic | License | Exercises |
|------|-------|---------|-----------|
| `PMC9000001.xml` | NF1 plexiform neurofibroma | CC BY | MRI + H&E histology, entity matching |
| `PMC9000002.xml` | NF2 vestibular schwannoma | CC BY-NC | MRI + clinical photo |
| `PMC9000003.xml` | off-topic (allergy cohort) | CC0 | `not_nf_relevant`, chart figure-type, CC0 |

For real curation, drop actual PMC OA `.nxml` files here (or just run the
networked pipeline, which downloads and caches them under `cache/`).
