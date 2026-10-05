#!/usr/bin/env python3
"""
Production-grade script to extract valid, verified, non-empty blocklist URLs
from a Pi-hole gravity.db database, sort them alphabetically, overwrite
blocklists.txt, and automatically push the updated file to GitHub using
a secure 7-character random hexadecimal commit message.
"""

from pathlib import Path
import secrets
import sqlite3
import subprocess
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
    and unverified entries), returning them as a unique, immutable frozenset.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"Gravity database not found at target path: {db_path}"
        )

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

            # Exclude allowlists (Type 0 = blocklist, Type 1 = allowlist)
            if "type" in columns:
                conditions.append("type = ?")
                params.append(0)

            # Pi-hole status codes: 1 = Successful, 2 = Unchanged upstream, 3 = Local copy fallback
            if "status" in columns:
                conditions.append("status IN (?, ?, ?)")
                params.extend([1, 2, 3])

            if "number" in columns:
                conditions.append("number IS NOT NULL AND number > ?")
                params.append(0)

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
        print(
            f"An unexpected error occurred during database processing: {err}",
            file=sys.stderr,
        )
        raise

    return frozenset(urls)


def generate_secure_hex_msg() -> str:
    """Generates a secure 7-character random hexadecimal commit message."""
    return secrets.token_hex(4)[:7]


def git_commit_and_push(output_path: Path):
    """Stages, commits, and pushes blocklists.txt to the remote repository

    using a cryptographically secure 7-digit hex string commit message.
    """
    repo_dir = output_path.parent
    commit_msg = generate_secure_hex_msg()

    print(f"Initiating Git workflow in: {repo_dir}")

    try:
        # Ensure it's a valid git repository work tree
        subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--is-inside-work-tree"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Stage blocklists.txt
        subprocess.run(
            ["git", "-C", str(repo_dir), "add", output_path.name],
            check=True,
            text=True,
        )

        # Check if there are actual changes to commit (prevents empty commit errors)
        status_res = subprocess.run(
            ["git", "-C", str(repo_dir), "diff", "--cached", "--quiet"],
            check=False,
            text=True,
        )

        if status_res.returncode == 0:
            print(
                "No changes detected in blocklists.txt. Skipping commit and push."
            )
            return

        # Commit with random secure 7-char hex message
        subprocess.run(
            ["git", "-C", str(repo_dir), "commit", "-m", commit_msg],
            check=True,
            text=True,
        )
        print(f"Successfully committed changes with message: '{commit_msg}'")

        # Push to remote repository
        subprocess.run(
            ["git", "-C", str(repo_dir), "push"],
            check=True,
            text=True,
        )
        print("Successfully pushed new blocklists version to GitHub.")

    except subprocess.CalledProcessError as git_err:
        print(f"Git workflow failed: {git_err}", file=sys.stderr)
        raise


def main():
    """Main execution entry point for extracting and publishing blocklists."""
    print(f"Reading Pi-hole gravity database from: {GRAVITY_DB_PATH}")
    try:
        blocklists_frozenset = extract_blocklist_urls(GRAVITY_DB_PATH)

        if not blocklists_frozenset:
            print(
                "Warning: No valid blocklists matched the criteria.",
                file=sys.stderr,
            )
            return

        sorted_blocklists = sorted(blocklists_frozenset)
        output_path = get_output_path()

        print(
            f"Writing {len(sorted_blocklists)} unique blocklists to: {output_path}"
        )

        # Write sorted blocklists line by line ('w' mode overwrites completely)
        with open(output_path, "w", encoding="utf-8") as f:
            for url in sorted_blocklists:
                f.write(f"{url}\n")

        print(
            "Success: Blocklists exported, overwritten, and sorted alphabetically."
        )

        # Push the validated file changes to GitHub
        git_commit_and_push(output_path)

    except (sqlite3.Error, subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        print(f"Execution failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
