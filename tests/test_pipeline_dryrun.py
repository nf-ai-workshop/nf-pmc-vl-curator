import json

import pytest

from nf_pmc_vl_curator.config import Config
from nf_pmc_vl_curator.http_client import DryRunError, HTTPClient
from nf_pmc_vl_curator.models import NFRelevance
from nf_pmc_vl_curator.pipeline import Pipeline, sample_xml_files


def _config(tmp_path, keywords_path):
    return Config(
        keywords_path=keywords_path,
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        dry_run=True,
    )


def test_dry_run_blocks_network():
    cfg = Config(dry_run=True)
    client = HTTPClient(cfg.ncbi, dry_run=True)
    with pytest.raises(DryRunError):
        client.get("https://example.com")


def test_run_from_xml_end_to_end(tmp_path, keywords_path):
    cfg = _config(tmp_path, keywords_path)
    pipeline = Pipeline(cfg)
    summary = pipeline.run_from_xml(sample_xml_files())

    # 3 articles -> 5 figures total in the bundled sample set.
    assert summary["articles"] == 3
    assert summary["total_candidates"] == 5
    assert summary["by_nf_relevance"].get("nf1") == 2
    assert summary["by_nf_relevance"].get("nf2") == 2

    dataset = cfg.output_dir / "dataset.jsonl"
    records = [json.loads(l) for l in dataset.read_text().splitlines() if l.strip()]
    assert len(records) == summary["exported"]

    # Every exported record carries provenance + license metadata.
    for rec in records:
        assert rec["provenance"]["source_xml"]
        assert rec["provenance"]["tool_version"]
        assert rec["license"] is not None
        # dry-run must not leak the live query into provenance
        assert rec["provenance"]["search_query"] is None


def test_offline_and_network_paths_share_schema(tmp_path, keywords_path):
    # The offline path should produce records that validate as FigureRecord,
    # i.e. identical schema to the networked path.
    from nf_pmc_vl_curator.models import FigureRecord

    cfg = _config(tmp_path, keywords_path)
    Pipeline(cfg).run_from_xml(sample_xml_files())
    dataset = cfg.output_dir / "dataset.jsonl"
    for line in dataset.read_text().splitlines():
        if line.strip():
            FigureRecord.model_validate_json(line)  # raises on schema drift
