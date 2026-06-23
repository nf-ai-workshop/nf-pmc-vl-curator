import json

from click.testing import CliRunner

from nf_pmc_vl_curator.cli import cli


def test_run_dry_run(tmp_path):
    out = tmp_path / "out"
    result = CliRunner().invoke(
        cli, ["run", "--dry-run", "--output", str(out), "--cache", str(tmp_path / "c")]
    )
    assert result.exit_code == 0, result.output
    assert "Curation summary" in result.output
    assert (out / "dataset.jsonl").exists()


def test_run_with_explicit_xml(tmp_path, sample_dir):
    out = tmp_path / "out"
    xml = sample_dir / "PMC9000001.xml"
    result = CliRunner().invoke(
        cli, ["run", "--xml", str(xml), "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    records = [l for l in (out / "dataset.jsonl").read_text().splitlines() if l.strip()]
    assert len(records) == 2  # two figures in that article


def test_extract_command(sample_dir):
    result = CliRunner().invoke(cli, ["extract", str(sample_dir / "PMC9000001.xml")])
    assert result.exit_code == 0, result.output
    assert "PMC9000001" in result.output
    assert "2 figure(s)" in result.output


def test_annotate_command():
    result = CliRunner().invoke(
        cli, ["annotate", "T1-weighted MRI of a plexiform neurofibroma in NF1"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["nf_relevance"] == "nf1"
    assert payload["modality"] == "mri"


def test_inspect_command(tmp_path):
    out = tmp_path / "out"
    CliRunner().invoke(cli, ["run", "--dry-run", "--output", str(out)])
    result = CliRunner().invoke(cli, ["inspect", str(out / "dataset.jsonl")])
    assert result.exit_code == 0, result.output
    assert "records:" in result.output
