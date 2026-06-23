"""Smoke test: the Streamlit app module imports cleanly and wires to curation.

The interactive UI itself isn't exercised here (that needs a Streamlit
runtime); the reviewable logic lives in curation.py and is tested separately.
"""

import pytest

pytest.importorskip("streamlit")


def test_app_module_imports():
    from nf_pmc_vl_curator import app

    assert hasattr(app, "main")
    # the app exposes the same correctable label space as the curation layer
    from nf_pmc_vl_curator.curation import CORRECTABLE_FIELDS

    assert set(app.ENUMS) == set(CORRECTABLE_FIELDS)


def test_app_runs_and_loads_dataset(tmp_path, monkeypatch):
    """Execute the script under Streamlit's AppTest harness; assert no errors."""
    from streamlit.testing.v1 import AppTest

    from nf_pmc_vl_curator import app as app_module
    from nf_pmc_vl_curator.config import Config
    from nf_pmc_vl_curator.pipeline import Pipeline, sample_xml_files

    out = tmp_path / "out"
    cfg = Config(output_dir=out, cache_dir=tmp_path / "c", dry_run=True)
    Pipeline(cfg).run_from_xml(sample_xml_files())

    monkeypatch.setenv("NF_CURATOR_DATASET", str(out / "dataset.jsonl"))
    monkeypatch.setenv("NF_CURATOR_OUTPUT", str(out))

    at = AppTest.from_file(app_module.__file__).run(timeout=30)
    assert not at.exception
    # the dataset auto-loaded, so review widgets (selectboxes) are present
    assert len(at.selectbox) >= 1
