#!/usr/bin/env python3
"""
Production-grade script to extract valid, verified, non-empty blocklist URLs
from a Pi-hole gravity.db database. Includes status 3 (local fallbacks) 
and enforces uniqueness via frozen immutable objects (frozenset).
"""

from pathlib import Path
import sqlite3
import sys

GRAVITY_DB_PATH = Path(
    "/mnt/dietpi_userdata/docker/primary-stack/pihole/etc-pihole/gravity.db"
)
OUTPUT_FILENAME = "blocklists.txt"


def get_output_path() -> Path:
  return Path(__file__).resolve().parent / OUTPUT_FILENAME


def extract_blocklist_urls(db_path: Path) -> frozenset[str]:
  if not db_path.exists():
    raise FileNotFoundError(f"Gravity database not found at target path: {db_path}")

  urls = set()
  db_uri = f"file:{db_path.as_posix()}?mode=ro"

  try:
    with sqlite3.connect(db_uri, uri=True) as conn:
      cursor = conn.cursor()

      cursor.execute(
          "SELECT name FROM sqlite_master WHERE type='table' AND name='adlist';"
      )
      if not cursor.fetchone():
        raise sqlite3.OperationalError(
            "The 'adlist' table does not exist in the provided gravity database."
        )

      cursor.execute("PRAGMA table_info(adlist);")
      columns = {row[1] for row in cursor.fetchall()}

      conditions = ["enabled = 1"]
      params = []

      # Exclude allowlists (Type 0 = blocklist, Type 1 = allowlist)
      if "type" in columns:
        conditions.append("type = ?")
        params.append(0)

      # Pi-hole status codes:
      # 1 = Successful download, 2 = Unchanged upstream, 3 = List unavailable, Pi-hole used a local copy
      if "status" in columns:
        conditions.append("status IN (?, ?, ?)")
        params.extend([1, 2, 3])

      if "number" in columns:
        conditions.append("number IS NOT NULL AND number > ?")
        params.append(0)

      query = f"SELECT address FROM adlist WHERE {' AND '.join(conditions)};"

      cursor.execute(query, params)
      for row in cursor.fetchall():
        url = row[0]
        if url and isinstance(url, str):
          cleaned_url = url.strip()
          if cleaned_url:
            urls.add(cleaned_url)

  except sqlite3.Error as sqlite_err:
    print(f"SQLite database error occurred: {sqlite_err}", file=sys.stderr)
    raise

  return frozenset(urls)


def main():
  print(f"Reading Pi-hole gravity database from: {GRAVITY_DB_PATH}")
  try:
    blocklists_frozenset = extract_blocklist_urls(GRAVITY_DB_PATH)

    if not blocklists_frozenset:
      print("Warning: No valid blocklists matched the criteria.", file=sys.stderr)
      return

    sorted_blocklists = sorted(blocklists_frozenset)
    output_path = get_output_path()
    
    print(f"Writing {len(sorted_blocklists)} unique blocklists to: {output_path}")

    with open(output_path, "w", encoding="utf-8") as f:
      for url in sorted_blocklists:
        f.write(f"{url}\n")

    print("Success: Blocklists exported, overwritten, and sorted alphabetically.")

  except Exception as e:
    print(f"Execution failed: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
