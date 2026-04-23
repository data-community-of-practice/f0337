# f0337
# Enrich Organisations with ROR and Wikidata IDs

A Python script that extracts all unique organisation names from researcher affiliations, resolves them against the [ROR (Research Organization Registry) API](https://ror.org/), and produces three JSON outputs: a deduplicated organisation node list, a researcher-to-organisation relationship table, and an updated researcher file with organisation IDs embedded in each affiliation.

No API key required — ROR is a free, open registry.

## Pipeline context

```
f0334  →  Crossref_AuthorMetadata.json
f0335  →  Normalised_Authors.json
f0335a →  Resolved_Authors.json
f0336  →  Authors_With_Affiliations.json
f0336a →  Authors_With_Affiliations.json   (further enriched)
f0337  →  Organisations.json
           Researcher_Organisation.json
           Authors_Enriched.json
```

By this stage, each researcher has a list of affiliation strings sourced from Crossref, ORCID, Semantic Scholar, or Firecrawl. These strings are inconsistent — the same institution can appear in dozens of forms across publications. f0337 resolves them all to canonical ROR records and assigns each unique organisation a stable UUID for downstream use.

## How it works

1. **Collect** — walks every researcher's `affiliations` list and builds a set of unique organisation name strings.
2. **Resolve** — for each unique name, queries the ROR API using two strategies:
   - **Affiliation matching** (`?affiliation=...`): ROR's purpose-built endpoint for messy, full-text affiliation strings. Accepts a match if the API marks it `chosen` or returns a score of 0.80 or above.
   - **Query search fallback** (`?query=...`): if affiliation matching fails, strips department names, postcodes, and country suffixes from the string and retries with the core institution name.
3. **Deduplicate** — multiple affiliation strings that resolve to the same ROR ID are merged into one organisation node. The node records all original name variants.
4. **Build outputs** — creates the three JSON files and caches all ROR responses for resumable re-runs.

## Outputs

| File | Description |
|------|-------------|
| `Organisations.json` | One node per unique organisation, with ROR ID, Wikidata ID, GRID, ISNI, country, city, type, and all raw name variants. |
| `Researcher_Organisation.json` | Relationship records pairing researcher UUIDs to organisation UUIDs. One record per unique pair. |
| `Authors_Enriched.json` | Copy of the input researchers, with `organisation_id`, `ror_id`, and `wikidata` added to each affiliation object. |
| `ror_lookup_cache.json` | Cached ROR responses keyed by normalised affiliation name. Enables resumable runs. |

### Organisation node

```json
{
  "id": "a1b2c3d4-...",
  "name": "University of Melbourne",
  "ror_id": "https://ror.org/01ej9dk98",
  "wikidata": "Q598841",
  "grid": "grid.1008.9",
  "isni": "0000 0001 2179 088X",
  "country": "AU",
  "city": "Melbourne",
  "org_type": ["education"],
  "original_names": [
    "University of Melbourne",
    "The University of Melbourne, Melbourne, VIC, Australia",
    "School of Computing, University of Melbourne"
  ]
}
```

| Field | Description |
|-------|-------------|
| `id` | Pipeline-internal UUID (stable within a run). |
| `name` | Canonical display name from ROR. |
| `ror_id` | ROR persistent identifier URL. `null` if unmatched. |
| `wikidata` | Wikidata QID (e.g. `"Q598841"`). `null` if not in ROR record. |
| `grid` | GRID identifier. `null` if not available. |
| `isni` | ISNI identifier. `null` if not available. |
| `country` | ISO country code (e.g. `"AU"`). Empty string if unmatched. |
| `city` | City name from GeoNames. Empty string if unmatched. |
| `org_type` | List of ROR organisation types (e.g. `["education"]`, `["healthcare"]`). |
| `original_names` | All raw affiliation strings that resolved to this organisation. |

### Relationship record

```json
{
  "researcher_id": "3f2a1b4c-...",
  "organisation_id": "a1b2c3d4-..."
}
```

One record per unique researcher–organisation pair. A researcher with two affiliations at the same institution (listed with different strings) generates only one relationship record.

### Updated affiliation object (in `Authors_Enriched.json`)

The affiliation objects within each researcher are extended with:

```json
{
  "name": "School of Computing, University of Melbourne",
  "organisation_id": "a1b2c3d4-...",
  "ror_id": "https://ror.org/01ej9dk98",
  "wikidata": "Q598841"
}
```

## Requirements

- Python 3.7+
- Library: `requests`

```bash
pip install requests
```

No API key or registration required.

## Usage

```bash
python f0337.py
```

By default, reads `Authors_Final.json` from the current directory (then the script directory). To specify a path:

```bash
python f0337.py path/to/Authors_With_Affiliations.json
```

Outputs are written to the same directory as the input by default. To use a different output directory:

```bash
python f0337.py input.json --output-dir ./output/
```

### All options

| Option | Description |
|--------|-------------|
| `input_json` | Input researcher JSON (default: `Authors_Final.json`). |
| `--output-dir`, `-o` | Directory for all output files (default: same as input). |
| `--dry-run` | Print all unique organisation names and researcher counts without making any API calls. |

### From Spyder or Jupyter

```python
!python "E:\your\folder\f0337.py" "E:\your\folder\Authors_With_Affiliations.json"
```

## Dry run

Preview all unique organisation strings before spending API calls:

```bash
python f0337.py --dry-run
```

Output:

```
Total researchers:     2075
Unique affiliations:   843

--- Unique organisations ---
  University of Melbourne (312 researchers)
  Monash University (287 researchers)
  Royal Melbourne Hospital (94 researchers)
  ...
```

## Resuming an interrupted run

ROR lookup results are cached in `ror_lookup_cache.json`. Re-running the script skips all previously resolved affiliations — only new strings incur API calls.

```
Total researchers:     2075
Unique affiliations:   843
ROR cache:             721 entries
Cached:                721
To look up:            122
```

## Console output

```
Input:   /path/to/Authors_With_Affiliations.json
Outputs: /path/to/

Total researchers:     2075
Unique affiliations:   843
ROR cache:             0 entries
Cached:                0
To look up:            843

[1/843] University of Melbourne -> University of Melbourne [ROR: https://ror.org/01ej9dk98] [Wikidata: Q598841]
[2/843] Dept of Psychiatry, Monash University, Clayton VIC -> Monash University [ROR: https://ror.org/02bfwt286] [Wikidata: Q598059]
[3/843] Some Small Research Centre -> no match
...

=======================================================
ORGANISATION ENRICHMENT SUMMARY
=======================================================
Unique affiliation strings:  843
Deduplicated organisations:  561
  Matched to ROR:            498
  With Wikidata:             471
  Unmatched:                 63
Researcher-Org links:        3847

Organisation types:
  education: 312
  healthcare: 89
  facility: 54
  government: 31
  nonprofit: 12

Saved:
  Organisations:       /path/to/Organisations.json
  Researcher-Org:      /path/to/Researcher_Organisation.json
  Researchers updated: /path/to/Authors_Enriched.json
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ERROR: pip install requests` | Run `pip install requests` and retry. |
| Many `no match` results | Run `--dry-run` to inspect the raw affiliation strings. Very specific department names or small research centres may not be in ROR. The unmatched organisations are still written to `Organisations.json` with `ror_id: null`. |
| ROR matched the wrong institution | Check `original_names` in the organisation node. If a short or ambiguous string (e.g. "Centre for Health") matched incorrectly, the cache entry can be removed and the script re-run. |
| Rate limit errors (HTTP 429) | The script waits 0.2s between requests. If errors persist, increase the sleep by modifying the `time.sleep(0.2)` calls. |
| Output files in wrong location | Use `--output-dir` to set a specific directory. |

## Limitations

- **ROR coverage**: ROR contains ~109,000 organisations. Very small research groups, some hospitals, and some commercial entities may not be registered.
- **Department-level strings**: ROR resolves to the institution level. "Department of Psychiatry, University of Melbourne" resolves to the university — the department is preserved only in `original_names`.
- **Match threshold**: The script accepts ROR affiliation matches marked `chosen` or with score >= 0.80. Borderline matches just below this threshold are not captured; they fall through to the query-search fallback.

## License

This script is provided as-is for research and data management purposes.
