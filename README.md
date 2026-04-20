# f0337
# Unique Organisation Extractor

A Python script that extracts and deduplicates research organisations from the affiliations Excel file, using the [ROR (Research Organization Registry) API](https://ror.org/) to normalise messy affiliation strings into canonical institution names.

## The problem

Raw affiliation data from Crossref and OpenAlex contains department names, faculties, cities, states, and country — all concatenated into a single string. The same institution appears in many forms:

- "Brain and Psychological Sciences Research Centre Faculty of Life and Social Sciences Swinburne University of Technology Melbourne Vic. Australia"
- "Centre for Mental Health, Faculty of Health, Arts & Design, Swinburne University of Technology, Melbourne, VIC, Australia"
- "Swinburne University of Technology Melbourne Victoria Australia"
- "Swinburne University of Technology"

All of these should resolve to **Swinburne University of Technology**.

## How it works

1. **Collect**: Read all affiliation strings from the input Excel file, decoding HTML entities (e.g., `&amp;` → `&`) before splitting by semicolons.
2. **Resolve**: For each unique raw affiliation string, query the ROR API's affiliation endpoint. ROR is specifically designed to parse unstructured affiliation strings and match them to canonical institutions from a registry of 100,000+ organisations.
3. **Group**: Raw strings that resolve to the same ROR ID are grouped together under the canonical institution name.
4. **Output**: One row per unique institution with its ROR ID, country, city, organisation type, all raw variants, and the linked authors and DOIs.

## Requirements

- Python 3.7+
- Libraries: `openpyxl`, `requests`

```bash
pip install openpyxl requests
```

## Setup

Uses the same `config.ini` as the other scripts in this pipeline:

```ini
[crossref]
email = yourname@example.com
delay = 1
save_every = 50
max_retries = 3
```

## Input file format

The script expects the output of `fetch_affiliations.py` — an Excel file with at minimum:

| Column | Required | Description |
|---|---|---|
| `Affiliations` | Yes | Semicolon-separated affiliation strings |
| `Author_Name` | No | Author name (carried through to output) |
| `DOIs` | No | Semicolon-separated DOIs (carried through to output) |

## Usage

### From a terminal

```bash
python extract_unique_orgs.py affiliations.xlsx
```

### From Spyder

```python
!python "E:\your\folder\extract_unique_orgs.py" "E:\your\folder\affiliations.xlsx"
```

## Output

The script produces `<input_name>_unique_orgs.xlsx` with ten columns:

| Column | Description |
|---|---|
| `Organisation_Name` | Canonical institution name from ROR (or raw string if unresolved) |
| `ROR_ID` | ROR persistent identifier (e.g., `https://ror.org/031rekg67`) |
| `Country` | Country where the institution is located |
| `City` | City where the institution is located |
| `Type` | Organisation type (education, healthcare, facility, etc.) |
| `Raw_Variants` | All original affiliation strings that resolved to this institution |
| `Author_Count` | Number of unique authors affiliated with this institution |
| `Authors` | Semicolon-separated list of author names |
| `DOI_Count` | Number of unique DOIs linked to this institution |
| `DOIs` | Semicolon-separated list of DOIs |

## Cache and resumability

The script creates a `<input>_ror_cache.json` file storing all ROR lookup results. Re-running skips previously resolved affiliations. Delete the cache to force a full re-fetch.

## Full pipeline

This is step 4 in the pipeline:

```
1. python crossref_author_fetch.py <input>.xlsx
     → adds Crossref_Authors column

2. python extract_unique_authors.py <step1_output>.xlsx
     → one row per unique author with DOIs

3. python fetch_affiliations.py <step2_output>.xlsx
     → adds Affiliations column (Crossref + OpenAlex)

4. python extract_unique_orgs.py <step3_output>.xlsx
     → one row per unique institution with ROR ID
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `Could not find 'Affiliations' column` | Input must have a column named exactly `Affiliations`. Run `fetch_affiliations.py` first. |
| Many orgs without ROR ID | ROR may not recognise very specific sub-units (research centres, departments). These remain as raw strings. |
| HTML entities in output (`&amp;`) | The script decodes these automatically. If you still see them, the input file may have double-encoded entities. |
| Incorrect ROR match | ROR's affiliation matching is generally accurate but can occasionally match the wrong institution for ambiguous strings. Check the `Raw_Variants` column. |

## Limitations

- **ROR coverage**: ROR contains ~109,000 organisations. Smaller research groups, hospitals, and commercial entities may not be in the registry.
- **Department-level granularity**: ROR identifies institutions, not departments. "Department of Psychiatry, University of Melbourne" resolves to "University of Melbourne" — the department information is not preserved separately.
- **Rate limits**: The ROR API allows approximately 2,000 requests per 5-minute window. The `delay` setting in config.ini helps stay within limits.

## License

This script is provided as-is for research and data management purposes.
