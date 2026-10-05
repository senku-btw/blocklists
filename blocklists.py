#!/usr/bin/env python3
"""
Production-grade script to extract valid, verified, non-empty blocklist URLs
from a Pi-hole gravity.db database. Overwrites blocklists.txt completely on 
subsequent runs, filters out unverified/pending lists (status, N/A counts, etc.),
enforces uniqueness via frozen immutable objects (frozenset), and sorts them alphabetically.
"""

from pathlib import Path
import sqlite3
import sys

# Path to Pi-hole gravity database specified in requirements
GRAVITY_DB_PATH = Path(
    "/mnt/dietpi_userdata/docker/primary-stack/pihole/etc-pihole/gravity.db"
)
OUTPUT_FILENAME = "blocklists.txt"


def get_output_path() -> Path:
  """Returns the absolute path for blocklists.txt in the script's execution directory."""
  return Path(__file__).resolve().parent / OUTPUT_FILENAME


def extract_blocklist_urls(db_path: Path) -> frozenset[str]:
  """Connects to the Pi-hole gravity SQLite database, inspects table schema,

  and extracts valid, verified, non-empty blocklist URLs (excluding allowlists
  and unverified/N/A entries), returning them as a unique, immutable frozenset.
  """
  if not db_path.exists():
    raise FileNotFoundError(f"Gravity database not found at target path: {db_path}")

  urls = set()
  
  # Connect in read-only mode via URI for data safety
  db_uri = f"file:{db_path.as_posix()}?mode=ro"

  try:
    with sqlite3.connect(db_uri, uri=True) as conn:
      cursor = conn.cursor()

      # Verify that the 'adlist' table exists
      cursor.execute(
          "SELECT name FROM sqlite_master WHERE type='table' AND name='adlist';"
      )
      if not cursor.fetchone():
        raise sqlite3.OperationalError(
            "The 'adlist' table does not exist in the provided gravity database."
        )

      # Inspect table columns dynamically to support both Pi-hole v5 and v6 schemas
      cursor.execute("PRAGMA table_info(adlist);")
      columns = {row[1] for row in cursor.fetchall()}

      # Base condition: enabled = 1
      conditions = ["enabled = 1"]
      params = []

      # Exclude allowlists (Type 0 = blocklist/denylist, Type 1 = allowlist in v6+)
      if "type" in columns:
        conditions.append("type = ?")
        params.append(0)

      # Exclude unverified or failed lists:
      # Pi-hole status codes: 1 = Successful download, 2 = Unchanged upstream (valid local copy).
      # Status 0 (Unknown / not downloaded so far), 3, or 4 (unavailable) are excluded.
      if "status" in columns:
        conditions.append("status IN (?, ?)")
        params.extend([1, 2])

      # Ensure list has verified entries (Filters out 'N/A' or zero entries)
      if "number" in columns:
        conditions.append("number IS NOT NULL AND number > ?")
        params.append(0)

      # Ensure list has a valid update timestamp (Filters out 'Content last updated on: N/A')
      if "date_updated" in columns:
        conditions.append("date_updated IS NOT NULL")

      query = f"SELECT address FROM adlist WHERE {' AND '.join(conditions)};"

      cursor.execute(query, params)
      rows = cursor.fetchall()

      for row in rows:
        url = row[0]
        if url and isinstance(url, str):
          cleaned_url = url.strip()
          if cleaned_url:
            urls.add(cleaned_url)

  except sqlite3.Error as sqlite_err:
    print(f"SQLite database error occurred: {sqlite_err}", file=sys.stderr)
    raise
  except Exception as err:
    print(f"An unexpected error occurred during database processing: {err}", file=sys.stderr)
    raise

  # Enforce uniqueness using a frozen immutable object (frozenset)
  return frozenset(urls)


def main():
  print(f"Reading Pi-hole gravity database from: {GRAVITY_DB_PATH}")
  try:
    blocklists_frozenset = extract_blocklist_urls(GRAVITY_DB_PATH)

    if not blocklists_frozenset:
      print("Warning: No valid, verified, non-empty blocklists matched the criteria.", file=sys.stderr)
      return

    # Sort the unique immutable items alphabetically
    sorted_blocklists = sorted(blocklists_frozenset)

    output_path = get_output_path()
    print(f"Writing {len(sorted_blocklists)} unique blocklists to: {output_path}")

    # Write sorted blocklists line by line ('w' mode ensures full file overwrite on every run)
    with open(output_path, "w", encoding="utf-8") as f:
      for url in sorted_blocklists:
        f.write(f"{url}\n")

    print("Success: Blocklists exported, overwritten, and sorted alphabetically.")

  except Exception as e:
    print(f"Execution failed: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
