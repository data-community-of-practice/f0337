#!/usr/bin/env python3
"""
Enrich Organisations with ROR + Wikidata IDs
===============================================
Reads a researcher JSON from the pipeline, extracts all unique
organisation names from affiliations, enriches them via the ROR API,
and produces three JSON files:

  1. Organisations.json — deduplicated organisation nodes, each with
     a UUID primary key, ROR ID, Wikidata ID, country, city, type

  2. Researcher_Organisation.json — relationship records connecting
     researcher UUIDs to organisation UUIDs

  3. Authors_Enriched.json — researchers updated with organisation
     UUIDs in their affiliations

Uses the ROR affiliation matching endpoint, designed for messy
affiliation strings. No API key required.

Usage:
  python f0337.py [Authors_Final.json] [--output-dir ./output]
  python f0337.py --dry-run
"""

import sys
import json
import time
import re
import uuid
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = "Authors_Final.json"

ROR_API_BASE = "https://api.ror.org/v2/organizations"


# ============================================================
# ROR API
# ============================================================

def ror_affiliation_match(affiliation_string, session, max_retries=3):
    """Use ROR affiliation matching for messy strings."""
    params = {"affiliation": affiliation_string}

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(ROR_API_BASE, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            if attempt < max_retries:
                time.sleep(1)
            else:
                return None
    return None


def ror_query_search(org_name, session, max_retries=3):
    """Fallback: ROR query search for clean names."""
    params = {"query": org_name}

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(ROR_API_BASE, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            if attempt < max_retries:
                time.sleep(1)
            else:
                return None
    return None


def parse_ror_affiliation_response(data):
    """Parse ROR affiliation endpoint response. Returns best match."""
    if not data or not data.get("items"):
        return None

    for item in data["items"]:
        chosen = item.get("chosen", False)
        score = item.get("score", 0)
        org = item.get("organization", {})

        if chosen or score >= 0.8:
            return extract_org_metadata(org, score)

    return None


def parse_ror_query_response(data):
    """Parse ROR query endpoint response. Returns top result."""
    if not data or not data.get("items"):
        return None

    if data["items"]:
        return extract_org_metadata(data["items"][0], 1.0)

    return None


def extract_org_metadata(org, score):
    """Extract structured metadata from a ROR record."""
    if not org:
        return None

    result = {
        "ror_id": org.get("id", ""),
        "name": "",
        "country": "",
        "city": "",
        "wikidata": None,
        "grid": None,
        "isni": None,
        "org_type": [],
        "match_score": score,
    }

    # Primary name
    for n in org.get("names", []):
        if "ror_display" in n.get("types", []):
            result["name"] = n.get("value", "")
            break
    if not result["name"]:
        names = org.get("names", [])
        if names:
            result["name"] = names[0].get("value", "")

    # Location
    locations = org.get("locations", [])
    if locations:
        geo = locations[0].get("geonames_details", {})
        result["country"] = geo.get("country_code", "")
        result["city"] = geo.get("name", "")

    # External IDs
    for ext_id in org.get("external_ids", []):
        id_type = ext_id.get("type", "")
        preferred = ext_id.get("preferred")
        all_ids = ext_id.get("all", [])
        value = preferred or (all_ids[0] if all_ids else None)

        if id_type == "wikidata" and value:
            result["wikidata"] = value
        elif id_type == "grid" and value:
            result["grid"] = value
        elif id_type == "isni" and value:
            result["isni"] = value

    # Organisation type
    result["org_type"] = org.get("types", [])

    return result


def extract_core_org_name(affiliation_string):
    """Strip department/city/country from affiliation to get core org name."""
    parts = [p.strip() for p in affiliation_string.split(",")]

    location_patterns = [
        r'^[A-Z]{2,3}$',
        r'^Australia$',
        r'^\d{4}',
    ]

    org_parts = []
    for part in parts:
        is_location = any(re.match(pat, part.strip(), re.IGNORECASE)
                          for pat in location_patterns)
        if not is_location and len(part) > 3:
            org_parts.append(part)

    return ", ".join(org_parts) if org_parts else affiliation_string


# ============================================================
# NAME NORMALISATION
# ============================================================

def normalise_org_name(name):
    """Normalise organisation name for deduplication."""
    n = name.lower().strip()
    n = n.replace("&amp;", "and").replace("&", "and")
    n = re.sub(r'[,.\-\'\"()]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Enrich organisations with ROR/Wikidata IDs"
    )
    parser.add_argument("input_json", nargs="?", default=None,
                        help=f"Input JSON (default: {DEFAULT_INPUT})")
    parser.add_argument("--output-dir", "-o", default=None,
                        help="Output directory (default: same as input)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show unique organisations without API calls")
    args = parser.parse_args()

    # Resolve paths
    if args.input_json:
        input_path = Path(args.input_json).resolve()
    else:
        input_path = Path.cwd() / DEFAULT_INPUT
        if not input_path.exists():
            input_path = SCRIPT_DIR / DEFAULT_INPUT

    if not input_path.exists():
        print(f"ERROR: {input_path} not found")
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    orgs_path = output_dir / "Organisations.json"
    rels_path = output_dir / "Researcher_Organisation.json"
    authors_path = output_dir / "Authors_Enriched.json"
    cache_path = output_dir / "ror_lookup_cache.json"

    print(f"Input:   {input_path}")
    print(f"Outputs: {output_dir}")
    print()

    # Load researchers
    with open(input_path, "r", encoding="utf-8") as f:
        researchers = json.load(f)

    # Extract all unique affiliation names
    # Track which researchers have which affiliations
    all_affs = {}  # normalised_name -> {"original": first_seen_name, "researchers": [rid]}
    for r in researchers:
        for aff in r.get("affiliations", []):
            name = aff.get("name", "").strip()
            if not name:
                continue
            norm = normalise_org_name(name)
            if norm not in all_affs:
                all_affs[norm] = {"original": name, "researchers": set()}
            all_affs[norm]["researchers"].add(r["id"])

    print(f"Total researchers:     {len(researchers)}")
    print(f"Unique affiliations:   {len(all_affs)}")

    if args.dry_run:
        def safe(s):
            return s.encode("ascii", errors="replace").decode("ascii")
        print(f"\n--- Unique organisations ---")
        for norm, info in sorted(all_affs.items()):
            print(f"  {safe(info['original'])} ({len(info['researchers'])} researchers)")
        return

    # Load cache
    cache = {}
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        print(f"ROR cache:             {len(cache)} entries")

    # Look up each unique affiliation
    session = requests.Session()
    to_process = [(norm, info) for norm, info in all_affs.items()
                  if norm not in cache]
    cached_count = len(all_affs) - len(to_process)

    print(f"Cached:                {cached_count}")
    print(f"To look up:            {len(to_process)}")
    print()

    def safe(s):
        """Make string safe for Windows console output."""
        return s.encode("ascii", errors="replace").decode("ascii")

    for i, (norm, info) in enumerate(to_process, 1):
        orig = info["original"]
        print(f"[{i}/{len(to_process)}] {safe(orig[:65])}", end=" ", flush=True)

        # Strategy 1: Affiliation matching
        data = ror_affiliation_match(orig, session)
        result = parse_ror_affiliation_response(data)

        # Strategy 2: Query search with core name
        if not result:
            core = extract_core_org_name(orig)
            if core != orig:
                time.sleep(0.2)
                data = ror_query_search(core, session)
                result = parse_ror_query_response(data)

        if result:
            cache[norm] = result
            wk = result.get("wikidata", "n/a")
            print(f"-> {safe(result['name'])} [ROR: {result['ror_id']}] [Wikidata: {wk}]")
        else:
            cache[norm] = None
            print("-> no match")

        time.sleep(0.2)

    # Save cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # ---- Build organisation nodes ----
    # Deduplicate by ROR ID (multiple affiliation strings can map to same org)
    ror_to_org = {}       # ror_id -> org node
    norm_to_org_id = {}   # normalised_name -> org uuid
    unmatched_orgs = {}   # normalised_name -> org node (no ROR)

    for norm, info in all_affs.items():
        enriched = cache.get(norm)

        if enriched and enriched.get("ror_id"):
            ror_id = enriched["ror_id"]

            if ror_id not in ror_to_org:
                org_id = str(uuid.uuid4())
                ror_to_org[ror_id] = {
                    "id": org_id,
                    "name": enriched["name"],
                    "ror_id": ror_id,
                    "wikidata": enriched.get("wikidata"),
                    "grid": enriched.get("grid"),
                    "isni": enriched.get("isni"),
                    "country": enriched.get("country", ""),
                    "city": enriched.get("city", ""),
                    "org_type": enriched.get("org_type", []),
                    "original_names": [info["original"]],
                }
            else:
                # Same ROR, different affiliation string — record the variant
                existing = ror_to_org[ror_id]
                if info["original"] not in existing["original_names"]:
                    existing["original_names"].append(info["original"])

            norm_to_org_id[norm] = ror_to_org[ror_id]["id"]

        else:
            # No ROR match — create org node from original name
            if norm not in unmatched_orgs:
                org_id = str(uuid.uuid4())
                unmatched_orgs[norm] = {
                    "id": org_id,
                    "name": info["original"],
                    "ror_id": None,
                    "wikidata": None,
                    "grid": None,
                    "isni": None,
                    "country": "",
                    "city": "",
                    "org_type": [],
                    "original_names": [info["original"]],
                }
            norm_to_org_id[norm] = unmatched_orgs[norm]["id"]

    # Combine all organisations
    all_orgs = list(ror_to_org.values()) + list(unmatched_orgs.values())

    # ---- Build researcher-organisation relationships ----
    relationships = []
    seen_rels = set()

    for r in researchers:
        for aff in r.get("affiliations", []):
            name = aff.get("name", "").strip()
            if not name:
                continue

            norm = normalise_org_name(name)
            org_id = norm_to_org_id.get(norm)

            if org_id:
                rel_key = (r["id"], org_id)
                if rel_key not in seen_rels:
                    seen_rels.add(rel_key)
                    relationships.append({
                        "researcher_id": r["id"],
                        "organisation_id": org_id,
                    })

    # ---- Update researcher affiliations with org IDs ----
    for r in researchers:
        for aff in r.get("affiliations", []):
            name = aff.get("name", "").strip()
            if not name:
                continue

            norm = normalise_org_name(name)
            org_id = norm_to_org_id.get(norm)
            enriched = cache.get(norm)

            if org_id:
                aff["organisation_id"] = org_id
            if enriched:
                aff["ror_id"] = enriched.get("ror_id", "")
                if enriched.get("wikidata"):
                    aff["wikidata"] = enriched["wikidata"]

    # ---- Save outputs ----
    with open(orgs_path, "w", encoding="utf-8") as f:
        json.dump(all_orgs, f, ensure_ascii=False, indent=2)

    with open(rels_path, "w", encoding="utf-8") as f:
        json.dump(relationships, f, ensure_ascii=False, indent=2)

    with open(authors_path, "w", encoding="utf-8") as f:
        json.dump(researchers, f, ensure_ascii=False, indent=2)

    # ---- Summary ----
    matched_count = len(ror_to_org)
    unmatched_count = len(unmatched_orgs)
    with_wikidata = sum(1 for o in all_orgs if o.get("wikidata"))

    # Count org types
    type_counts = {}
    for o in all_orgs:
        for t in o.get("org_type", []):
            type_counts[t] = type_counts.get(t, 0) + 1

    print(f"\n{'='*55}")
    print(f"ORGANISATION ENRICHMENT SUMMARY")
    print(f"{'='*55}")
    print(f"Unique affiliation strings:  {len(all_affs)}")
    print(f"Deduplicated organisations:  {len(all_orgs)}")
    print(f"  Matched to ROR:            {matched_count}")
    print(f"  With Wikidata:             {with_wikidata}")
    print(f"  Unmatched:                 {unmatched_count}")
    print(f"Researcher-Org links:        {len(relationships)}")

    if type_counts:
        print(f"\nOrganisation types:")
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {t}: {c}")

    print(f"\nSaved:")
    print(f"  Organisations:       {orgs_path}")
    print(f"  Researcher-Org:      {rels_path}")
    print(f"  Researchers updated: {authors_path}")


if __name__ == "__main__":
    main()