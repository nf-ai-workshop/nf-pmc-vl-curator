"""Command-line interface for the NF PMC VL curator.

Commands
--------
  nf-curator run        Run the curation pipeline (networked or offline).
  nf-curator inspect    Print summary stats for an exported dataset.
  nf-curator extract    Parse a single JATS XML file and list its figures.
  nf-curator annotate   Weak-annotate an ad-hoc caption string (demo/debug).

The ``run`` command is the headline. Use ``--dry-run`` (or pass ``--xml``
files) to curate offline from local XML with no network access at all.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from . import __version__
from .agents import AnnotationAgent, FigureExtractionAgent
from .config import Config, load_config
from .models import ArticleRef
from .pipeline import Pipeline, sample_xml_files


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _print_summary(summary: dict) -> None:
    click.echo(click.style("\nCuration summary", bold=True))
    click.echo(f"  candidates : {summary['total_candidates']}")
    click.echo(f"  exported   : {summary['exported']}")
    click.echo(f"  rejected   : {summary['rejected']}")
    click.echo(f"  articles   : {summary['articles']}")
    for title, key in [
        ("NF relevance", "by_nf_relevance"),
        ("Modality", "by_modality"),
        ("Figure type", "by_figure_type"),
        ("License", "by_license"),
        ("Quality flags", "quality_flags"),
    ]:
        dist = summary.get(key) or {}
        if dist:
            rendered = ", ".join(f"{k}={v}" for k, v in sorted(dist.items()))
            click.echo(f"  {title:<13}: {rendered}")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="nf-curator")
def cli() -> None:
    """Reproducible NF1/NF2 PMC Open Access vision-language dataset curator."""


@cli.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              help="YAML config file.")
@click.option("--dry-run", is_flag=True,
              help="No network: curate bundled sample XML (or --xml files).")
@click.option("--xml", "xml_paths", multiple=True, type=click.Path(path_type=Path),
              help="Curate these local JATS XML files offline (repeatable).")
@click.option("--query", help="Override the search query.")
@click.option("--retmax", type=int, help="Override max number of search hits.")
@click.option("--output", "output_dir", type=click.Path(path_type=Path),
              help="Output directory (default: ./output).")
@click.option("--cache", "cache_dir", type=click.Path(path_type=Path),
              help="Cache directory (default: ./cache).")
@click.option("--email", help="Contact email sent to NCBI E-utilities.")
@click.option("--api-key", help="NCBI API key (raises the rate limit).")
@click.option("--assets/--no-assets", default=True,
              help="Download figure image assets (networked runs only).")
@click.option("-v", "--verbose", is_flag=True, help="Verbose (DEBUG) logging.")
def run(config_path, dry_run, xml_paths, query, retmax, output_dir, cache_dir,
        email, api_key, assets, verbose):
    """Run the curation pipeline and export a JSONL dataset."""
    _setup_logging(verbose)
    config = load_config(config_path) if config_path else Config()

    # Apply CLI overrides over the loaded/default config.
    if dry_run:
        config.dry_run = True
    if query:
        config.search.query = query
    if retmax:
        config.search.retmax = retmax
    if output_dir:
        config.output_dir = output_dir
    if cache_dir:
        config.cache_dir = cache_dir
    if email:
        config.ncbi.email = email
    if api_key:
        config.ncbi.api_key = api_key

    pipeline = Pipeline(config)

    offline = config.dry_run or bool(xml_paths)
    if offline:
        files = [Path(p) for p in xml_paths] or sample_xml_files()
        if not files:
            raise click.ClickException("No XML files to curate (none found in sample).")
        click.echo(f"Curating {len(files)} local XML file(s) offline...")
        summary = pipeline.run_from_xml(files)
    else:
        if config.ncbi.email == "you@example.com":
            click.echo(click.style(
                "warning: using placeholder NCBI email; set --email or config.",
                fg="yellow"))
        summary = pipeline.run(download_assets=assets)

    _print_summary(summary)
    click.echo(f"\nDataset written to {config.output_dir}/dataset.jsonl")


@cli.command()
@click.option("--query", default="NF1[Title/Abstract] AND open access[filter]",
              show_default=True, help="Probe query (kept tiny: retmax=1).")
@click.option("--email", help="Contact email sent to NCBI E-utilities.")
@click.option("--api-key", help="NCBI API key (optional).")
@click.option("--no-assets", is_flag=True,
              help="Skip the image-download check (test metadata path only).")
def doctor(query, email, api_key, no_assets):
    """Diagnose live connectivity: search -> OA -> XML -> image download.

    Runs one tiny real request through each network stage and prints a
    pass/fail checklist, so you can confirm the tool can actually fetch
    relevant figure images (and what access info, if any, you still need).
    """
    import tempfile

    from .agents import (DownloadAgent, FigureExtractionAgent,
                         OAAvailabilityAgent, SearchAgent)
    from .config import Config
    from .http_client import HTTPClient

    cfg = Config()
    cfg.search.query = query
    cfg.search.retmax = 1
    if email:
        cfg.ncbi.email = email
    if api_key:
        cfg.ncbi.api_key = api_key

    ok = click.style("PASS", fg="green")
    bad = click.style("FAIL", fg="red")

    def line(status, label, detail=""):
        click.echo(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))

    click.echo(click.style("nf-curator doctor", bold=True))
    if cfg.ncbi.email == "you@example.com":
        click.echo(click.style(
            "  note: no --email given; NCBI asks clients to identify themselves.",
            fg="yellow"))
    click.echo(f"  identity: email={cfg.ncbi.email} api_key={'set' if cfg.ncbi.api_key else 'none'}")

    client = HTTPClient(cfg.ncbi, dry_run=False)
    failures = 0
    try:
        refs = SearchAgent(client).run(cfg)
        if not refs:
            line(bad, "search (esearch/esummary)", "query returned 0 hits")
            raise click.ClickException("search returned nothing; try a broader --query")
        ref = refs[0]
        line(ok, "search (esearch/esummary)", f"found {ref.pmcid}")

        oa = OAAvailabilityAgent(client).check(ref.pmcid)
        if not oa.oa_available:
            line(bad, "OA availability (oa.fcgi)", f"{ref.pmcid} not Open Access")
            raise click.ClickException("first hit is not OA; try another --query")
        lic = oa.license.code if oa.license else "?"
        line(ok, "OA availability (oa.fcgi)", f"license={lic}")

        with tempfile.TemporaryDirectory() as tmp:
            dl = DownloadAgent(client, Path(tmp))
            xml_path = dl.fetch_article_xml(ref.pmcid)
            _, figures = FigureExtractionAgent().parse_file(xml_path)
            line(ok, "article XML (efetch)", f"{len(figures)} figure(s) parsed")

            if no_assets:
                line("SKIP", "image download", "skipped (--no-assets)")
            elif not oa.package_url:
                line(bad, "image download", "no package URL in OA record")
                failures += 1
            else:
                figures = dl.fetch_assets(oa, figures)
                resolved = [f for f in figures if f.local_image_path
                            and Path(f.local_image_path).exists()]
                if resolved:
                    sample = resolved[0]
                    size = Path(sample.local_image_path).stat().st_size
                    line(ok, "image download (OA package)",
                         f"{len(resolved)}/{len(figures)} figures -> images "
                         f"(e.g. {Path(sample.local_image_path).name}, {size} B)")
                else:
                    line(bad, "image download (OA package)",
                         "package fetched but no figure image matched")
                    failures += 1
    except click.ClickException:
        raise
    except Exception as exc:
        line(bad, "network", f"{type(exc).__name__}: {exc}")
        failures += 1

    click.echo()
    if failures:
        raise click.ClickException(
            f"{failures} check(s) failed. If you are behind a proxy/firewall, allow "
            "HTTPS to eutils.ncbi.nlm.nih.gov, www.ncbi.nlm.nih.gov and "
            "ftp.ncbi.nlm.nih.gov. See docs/network_access.md.")
    click.echo(click.style("All checks passed — the tool can fetch figure images.",
                           fg="green"))


@cli.command()
@click.argument("dataset", required=False, default=Path("output/dataset.jsonl"),
                type=click.Path(path_type=Path))
@click.option("--output", "output_dir", type=click.Path(path_type=Path),
              default=Path("dataset"), show_default=True,
              help="Destination dataset directory.")
@click.option("--accepted-only", is_flag=True,
              help="Only include records ACCEPTED in the curation app.")
@click.option("--image-format", type=click.Choice(["keep", "png", "jpg"]),
              default="keep", show_default=True,
              help="'keep' copies jpg/png and converts others to png.")
@click.option("--image-root", type=click.Path(path_type=Path), default=Path("."),
              show_default=True,
              help="Base dir for relative local_image_path values in the dataset.")
def materialize(dataset, output_dir, accepted_only, image_format, image_root):
    """Build a HuggingFace imagefolder dataset (images/ + metadata.jsonl).

    Reads a dataset.jsonl index and copies the actual figure images into a
    self-contained folder, each paired with its caption + weak labels.
    """
    from .curation import load_dataset
    from .materialize import materialize_dataset

    if not Path(dataset).exists():
        raise click.ClickException(f"dataset not found: {dataset}")
    records = load_dataset(dataset)
    stats = materialize_dataset(
        records, output_dir, accepted_only=accepted_only,
        image_format=image_format, image_root=image_root,
    )

    click.echo(click.style("\nMaterialized image dataset", bold=True))
    click.echo(f"  images written     : {stats['images']}")
    click.echo(f"  skipped (no image) : {stats['skipped_no_image']}")
    click.echo(f"  missing on disk    : {stats['missing_on_disk']}")
    if accepted_only:
        click.echo(f"  skipped (unaccepted): {stats['skipped_not_accepted']}")
    click.echo(f"\nDataset at {output_dir}/ (images/, metadata.jsonl, README.md)")
    click.echo("Load it with:")
    click.echo("  from datasets import load_dataset")
    click.echo(f"  ds = load_dataset('imagefolder', data_dir='{output_dir}')")


@cli.command()
@click.argument("dataset", type=click.Path(exists=True, path_type=Path))
def inspect(dataset: Path) -> None:
    """Print summary stats for an exported dataset.jsonl."""
    from collections import Counter

    nf, modality, flags = Counter(), Counter(), Counter()
    n = 0
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        n += 1
        nf[rec["annotations"]["nf_relevance"]] += 1
        modality[rec["annotations"]["modality"]] += 1
        for f in rec["quality"]["flags"]:
            flags[f] += 1
    click.echo(f"records: {n}")
    click.echo(f"nf_relevance: {dict(nf)}")
    click.echo(f"modality: {dict(modality)}")
    click.echo(f"quality_flags: {dict(flags)}")


@cli.command()
@click.argument("xml_file", type=click.Path(exists=True, path_type=Path))
def extract(xml_file: Path) -> None:
    """Parse one JATS XML file and list the figures it contains."""
    ref, figures = FigureExtractionAgent().parse_file(xml_file)
    click.echo(f"{ref.pmcid} | {ref.title or '(no title)'}")
    click.echo(f"{len(figures)} figure(s):")
    for fig in figures:
        cap = (fig.caption[:80] + "...") if len(fig.caption) > 80 else fig.caption
        click.echo(f"  [{fig.fig_id}] {fig.label or ''} href={fig.graphic_href}")
        click.echo(f"      {cap}")


@cli.command()
@click.option("--dataset", type=click.Path(path_type=Path),
              help="dataset.jsonl to open for review (default: <output>/dataset.jsonl).")
@click.option("--output", "output_dir", type=click.Path(path_type=Path),
              default=Path("output"), show_default=True,
              help="Output dir for decisions.json + curated exports.")
@click.option("--port", type=int, default=8501, show_default=True)
def app(dataset, output_dir, port):
    """Launch the interactive curation web app (Streamlit)."""
    try:
        import streamlit  # noqa: F401
    except ImportError as exc:
        raise click.ClickException(
            "Streamlit is not installed. Install the app extra:\n"
            "  uv sync --extra app"
        ) from exc

    import os
    import subprocess
    import sys

    app_path = Path(__file__).resolve().parent / "app.py"
    env = dict(os.environ)
    env["NF_CURATOR_OUTPUT"] = str(output_dir)
    if dataset:
        env["NF_CURATOR_DATASET"] = str(dataset)
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path),
           "--server.port", str(port)]
    click.echo(f"Launching curation app on http://localhost:{port} ...")
    subprocess.run(cmd, env=env, check=False)


@cli.command()
@click.argument("caption")
@click.option("--title", default="", help="Article title for NF-relevance context.")
@click.option("--keywords", type=click.Path(path_type=Path),
              help="Custom keywords YAML (defaults to bundled resource).")
def annotate(caption: str, title: str, keywords) -> None:
    """Weak-annotate a single caption string (handy for tuning keywords)."""
    from .config import DEFAULT_KEYWORDS_PATH
    from .models import Figure

    agent = AnnotationAgent(keywords or DEFAULT_KEYWORDS_PATH)
    ann = agent.annotate(Figure(fig_id="adhoc", caption=caption),
                         ArticleRef(pmcid="PMC0", title=title))
    click.echo(json.dumps(ann.model_dump(), indent=2))


if __name__ == "__main__":
    cli()
