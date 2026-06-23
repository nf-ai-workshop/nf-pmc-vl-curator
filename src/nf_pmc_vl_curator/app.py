"""Interactive curation web app (Streamlit).

A researcher-friendly front end over the pipeline. It lets a reviewer:

  * load an existing ``dataset.jsonl`` (or run the pipeline to make one),
  * browse figures one at a time with the image shown beside its caption,
  * correct the weak labels (NF relevance, modality, figure type),
  * accept / reject each figure, and
  * export the accepted subset as JSONL + CSV.

All decisions persist to ``decisions.json`` in the output dir, so a review
session is resumable and never lost. The heavy lifting lives in
:mod:`nf_pmc_vl_curator.curation`; this file is just the UI.

Launch with:  ``nf-curator app``  (or ``streamlit run .../app.py``).
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

# Absolute imports: Streamlit executes this file as a standalone script
# (no package parent), so relative imports would fail at runtime.
from nf_pmc_vl_curator.config import Config
from nf_pmc_vl_curator.curation import (
    CORRECTABLE_FIELDS,
    DecisionStore,
    apply_decisions,
    curated_records,
    load_dataset,
    write_curated,
)
from nf_pmc_vl_curator.models import FigureType, Modality, NFRelevance, ReviewStatus
from nf_pmc_vl_curator.pipeline import Pipeline, sample_xml_files

ENUMS = {
    "nf_relevance": [e.value for e in NFRelevance],
    "modality": [e.value for e in Modality],
    "figure_type": [e.value for e in FigureType],
}


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("records", [])          # raw weak-labelled records (baseline)
    ss.setdefault("store", None)          # DecisionStore
    ss.setdefault("output_dir", Path(os.environ.get("NF_CURATOR_OUTPUT", "output")))
    ss.setdefault("index", 0)
    ss.setdefault("loaded_from", None)


def _load(dataset_path: Path) -> None:
    ss = st.session_state
    ss.records = load_dataset(dataset_path)
    ss.store = DecisionStore.load(ss.output_dir / "decisions.json")
    ss.index = 0
    ss.loaded_from = str(dataset_path)


def _status_of(rec) -> ReviewStatus:
    info = st.session_state.store.get(rec.record_id)
    return info.status if info else ReviewStatus.PENDING


def _effective(rec, field: str) -> str:
    """Current value of a label: human correction if any, else the weak label."""
    info = st.session_state.store.get(rec.record_id)
    if info and field in info.corrections:
        return info.corrections[field]
    return getattr(rec.annotations, field).value


# --------------------------------------------------------------------------- #
# Sidebar: data source, reviewer, filters
# --------------------------------------------------------------------------- #
def _sidebar() -> dict:
    ss = st.session_state
    st.sidebar.title("🔬 NF figure curator")

    reviewer = st.sidebar.text_input("Reviewer name", value="", placeholder="your name")

    st.sidebar.subheader("Data")
    default_ds = os.environ.get(
        "NF_CURATOR_DATASET", str(ss.output_dir / "dataset.jsonl")
    )
    ds_path = st.sidebar.text_input("dataset.jsonl path", value=default_ds)
    if st.sidebar.button("📂 Load dataset", use_container_width=True):
        if Path(ds_path).exists():
            _load(Path(ds_path))
            st.sidebar.success(f"Loaded {len(ss.records)} records")
        else:
            st.sidebar.error("File not found")

    with st.sidebar.expander("⚙️ Or run the pipeline"):
        query = st.text_input("Search query", value=Config().search.query)
        retmax = st.number_input("Max articles", 1, 200, 10)
        email = st.text_input("Contact email (for NCBI)", value="")
        dry = st.checkbox("Dry-run (offline sample data)", value=True)
        if st.button("▶️ Run pipeline"):
            _run_pipeline(query, int(retmax), email, dry)

    st.sidebar.subheader("Filters")
    filters = {
        "relevance": st.sidebar.multiselect("NF relevance", ENUMS["nf_relevance"]),
        "modality": st.sidebar.multiselect("Modality", ENUMS["modality"]),
        "status": st.sidebar.multiselect(
            "Review status", [s.value for s in ReviewStatus]
        ),
        "search": st.sidebar.text_input("Caption contains"),
    }
    return {"reviewer": reviewer, **filters}


def _run_pipeline(query: str, retmax: int, email: str, dry: bool) -> None:
    ss = st.session_state
    cfg = Config(dry_run=dry, output_dir=ss.output_dir)
    cfg.search.query = query
    cfg.search.retmax = retmax
    if email:
        cfg.ncbi.email = email
    pipeline = Pipeline(cfg)
    with st.spinner("Running pipeline..."):
        if dry:
            pipeline.run_from_xml(sample_xml_files())
        else:
            pipeline.run(download_assets=True)
    _load(ss.output_dir / "dataset.jsonl")
    st.sidebar.success(f"Pipeline done: {len(ss.records)} records")


def _apply_filters(records, f: dict) -> list:
    out = []
    for rec in records:
        if f["relevance"] and rec.annotations.nf_relevance.value not in f["relevance"]:
            continue
        if f["modality"] and rec.annotations.modality.value not in f["modality"]:
            continue
        if f["status"] and _status_of(rec).value not in f["status"]:
            continue
        if f["search"] and f["search"].lower() not in rec.figure.caption.lower():
            continue
        out.append(rec)
    return out


# --------------------------------------------------------------------------- #
# Main: metrics, review card, export
# --------------------------------------------------------------------------- #
def _metrics(records) -> None:
    counts = {s: 0 for s in ReviewStatus}
    for rec in records:
        counts[_status_of(rec)] += 1
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(records))
    c2.metric("✅ Accepted", counts[ReviewStatus.ACCEPTED])
    c3.metric("❌ Rejected", counts[ReviewStatus.REJECTED])
    c4.metric("⏳ Pending", counts[ReviewStatus.PENDING])
    reviewed = counts[ReviewStatus.ACCEPTED] + counts[ReviewStatus.REJECTED]
    st.progress(reviewed / len(records) if records else 0.0,
                text=f"{reviewed}/{len(records)} reviewed")


def _review_card(rec, reviewer: str) -> None:
    ss = st.session_state
    st.markdown(f"### {rec.figure.label or rec.figure.fig_id} — `{rec.record_id}`")

    left, right = st.columns([1, 1])
    with left:
        path = rec.figure.local_image_path
        if path and Path(path).exists():
            st.image(path, use_container_width=True)
        else:
            st.info(f"No local image. Figure file: `{rec.figure.graphic_href}`\n\n"
                    "(Run the networked pipeline with assets to download images.)")
    with right:
        art = rec.article
        st.write(f"**{art.title or '(no title)'}**")
        st.caption(f"{art.journal or ''} · {art.pub_year or ''}")
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{art.pmcid}/"
        lic = rec.license.code if rec.license else "unknown"
        st.markdown(f"[{art.pmcid}]({url}) · License: **{lic}**")
        if rec.quality.flags:
            st.warning("Flags: " + ", ".join(f.value for f in rec.quality.flags))

    st.markdown("**Caption**")
    st.write(rec.figure.caption or "_(no caption)_")

    # Label correction widgets (default to current effective value).
    st.markdown("**Labels** (correct if the weak label is wrong)")
    cols = st.columns(len(CORRECTABLE_FIELDS))
    selected: dict[str, str] = {}
    for col, field in zip(cols, CORRECTABLE_FIELDS):
        cur = _effective(rec, field)
        options = ENUMS[field]
        selected[field] = col.selectbox(
            field, options, index=options.index(cur), key=f"{field}:{rec.record_id}"
        )
    notes = st.text_input("Notes", key=f"notes:{rec.record_id}")

    a, r, _ = st.columns([1, 1, 4])
    if a.button("✅ Accept & save", key=f"acc:{rec.record_id}", type="primary"):
        _save_decision(rec, ReviewStatus.ACCEPTED, reviewer, selected, notes)
    if r.button("❌ Reject & save", key=f"rej:{rec.record_id}"):
        _save_decision(rec, ReviewStatus.REJECTED, reviewer, selected, notes)


def _save_decision(rec, status, reviewer, selected, notes) -> None:
    ss = st.session_state
    # Only record fields the reviewer actually changed from the weak label.
    corrections = {
        field: value
        for field, value in selected.items()
        if value != getattr(rec.annotations, field).value
    }
    ss.store.decide(rec.record_id, status, reviewer=reviewer or None,
                    notes=notes or None, corrections=corrections)
    ss.store.save()
    ss.index += 1  # advance the queue
    st.rerun()


def _export_section(records) -> None:
    ss = st.session_state
    st.divider()
    merged = apply_decisions(records, ss.store)
    n_ok = len(curated_records(merged))
    st.subheader(f"Export — {n_ok} accepted record(s)")
    if st.button("💾 Write curated_dataset.jsonl + .csv", disabled=n_ok == 0):
        paths = write_curated(merged, ss.output_dir)
        st.success(f"Wrote {paths['jsonl']} and {paths['csv']}")


def main() -> None:
    st.set_page_config(page_title="NF figure curator", page_icon="🔬", layout="wide")
    _init_state()
    ss = st.session_state

    # Auto-load a dataset pointed to by the launcher, once.
    env_ds = os.environ.get("NF_CURATOR_DATASET")
    if not ss.records and ss.loaded_from is None and env_ds and Path(env_ds).exists():
        _load(Path(env_ds))

    f = _sidebar()

    if not ss.records:
        st.title("🔬 NF1/NF2 figure curator")
        st.info("Load a `dataset.jsonl` or run the pipeline from the sidebar to begin.")
        return

    queue = _apply_filters(ss.records, f)
    _metrics(ss.records)
    st.divider()

    if not queue:
        st.warning("No records match the current filters.")
    else:
        ss.index = max(0, min(ss.index, len(queue) - 1))
        nav1, nav2, nav3 = st.columns([1, 2, 1])
        if nav1.button("⬅️ Prev", disabled=ss.index == 0):
            ss.index -= 1
            st.rerun()
        nav2.markdown(
            f"<div style='text-align:center'>Record {ss.index + 1} of {len(queue)}"
            f" ({len(queue)} match filters)</div>", unsafe_allow_html=True)
        if nav3.button("Next ➡️", disabled=ss.index >= len(queue) - 1):
            ss.index += 1
            st.rerun()
        st.divider()
        _review_card(queue[ss.index], f["reviewer"])

    _export_section(ss.records)


# Streamlit executes the script with __name__ == "__main__"; guarding the call
# keeps the module importable (e.g. for tests) without launching the UI.
if __name__ == "__main__":
    main()
