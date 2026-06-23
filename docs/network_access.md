# Network access & how to test live image retrieval

This page answers two questions: **what access information do I need to fetch
images**, and **how do I verify the tool can actually get them**.

## TL;DR

- **No credentials / login / API key are *required*.** Every source is public.
- Provide a **contact email** (`--email you@inst.edu`) — NCBI asks all clients
  to identify themselves and may throttle anonymous traffic.
- Optionally add a **free NCBI API key** (`--api-key …`) to raise the rate
  limit from 3 to 10 requests/second for larger runs.
- One command tests the whole chain end-to-end:

```bash
uv run nf-curator doctor --email you@inst.edu
```

A green `All checks passed — the tool can fetch figure images.` means search,
OA lookup, XML download **and image download** all work from your machine.

## What the pipeline talks to

| Stage | Host (HTTPS, port 443) | Auth | Notes |
|-------|------------------------|------|-------|
| Search | `eutils.ncbi.nlm.nih.gov` | none | E-utilities `esearch`/`esummary`/`efetch` |
| OA check | `www.ncbi.nlm.nih.gov` | none | PMC OA service `oa.fcgi` |
| Images | `ftp.ncbi.nlm.nih.gov` | none | OA `.tar.gz` package, fetched over **HTTPS** |

All three must be reachable on outbound TCP 443. If you are behind a corporate
proxy or firewall, allow those hosts (and set the standard `HTTPS_PROXY`
environment variable, which `requests` honors automatically).

## What "access information" to provide

| Item | Required? | Why / how to get it |
|------|-----------|---------------------|
| Contact email | **Recommended** | NCBI etiquette; avoids throttling. `--email`, or `ncbi.email` in config. |
| NCBI API key | Optional | Raises rate limit 3→10 req/s. Create at <https://www.ncbi.nlm.nih.gov/account/> → Settings → API Key Management. `--api-key`, or `ncbi.api_key` in config. |
| Proxy settings | Only if firewalled | Set `HTTPS_PROXY` / `HTTP_PROXY` env vars. |

You do **not** need a PMC/PubMed login, an institutional subscription, or AWS
credentials — the Open Access subset is free and unauthenticated by design.

## How to test, step by step

Work outward from cheap/offline to full network so a failure localizes itself.

```bash
# 0. fully offline — proves the code works without any network
uv run nf-curator run --dry-run

# 1. one-shot live diagnostic — proves search/OA/XML/image-download all work
uv run nf-curator doctor --email you@inst.edu

# 2. metadata-only live run (no big downloads) — validates search + OA + XML
uv run nf-curator run --retmax 5 --no-assets --email you@inst.edu --output /tmp/meta

# 3. full live run WITH images, then confirm files landed on disk
uv run nf-curator run --retmax 5 --assets --email you@inst.edu \
    --output /tmp/full --cache /tmp/full_cache
find /tmp/full_cache -type f \( -iname '*.jpg' -o -iname '*.png' -o -iname '*.gif' \)
uv run nf-curator inspect /tmp/full/dataset.jsonl
```

After step 3, every exported record should have a non-null
`figure.local_image_path` pointing at a real image file under the cache dir.

## Known caveat: NCBI is migrating the article datasets (2026)

The `oa.fcgi` service currently returns **legacy** package URLs of the form
`ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/<a>/<b>/PMCxxxx.tar.gz`. As of
April 2026 NCBI **moved those files under a `/pub/pmc/deprecated/` prefix**, and
the legacy FTP files are slated for **removal in August 2026**
(<https://ncbiinsights.ncbi.nlm.nih.gov/2026/02/12/pmc-article-dataset-distribution-services/>).

This tool handles the transition by trying both locations
(`candidate_package_urls` in
[downloader.py](../src/nf_pmc_vl_curator/agents/downloader.py)): the direct
HTTPS path first, then the `deprecated/` path. So image download works today
even though the service still hands out the old path.

**When the deprecated files are removed**, the long-term source is the free
**PMC Open Access on AWS** cloud service (HTTPS or S3, still no login):
<https://pmc.ncbi.nlm.nih.gov/tools/cloud/>. Adapting the downloader to that
bucket is a localized change — only `candidate_package_urls` /
`_download_and_extract` need to learn the new URL scheme; the rest of the
pipeline is unaffected.

## If `doctor` fails

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| All stages fail | No outbound network / proxy | Allow HTTPS to the three hosts; set `HTTPS_PROXY`. |
| Search returns 0 hits | Query too narrow | Broaden `--query`. |
| Frequent throttling/429 | Anonymous or too fast | Add `--email`, and `--api-key` for 10 req/s. |
| XML ok, image download fails | OA package path changed | Check the migration note above; the AWS bucket is the durable source. |
