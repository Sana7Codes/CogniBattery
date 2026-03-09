"""
Data integrity hash writer / verifier.

Computes SHA-256 of the session CSV and writes a sidecar _hash.txt file.
The hash file is written at session *end* (after the final event has been
fsynced to disk), so it always reflects the complete session.

File naming: <csv_stem>_hash.txt

Sidecar format:
    SHA256:<hexdigest>
    File:<csv_filename>
"""
import hashlib
import os

HASH_SUFFIX = "_hash.txt"
CHUNK = 8192


def hash_path_from_csv(csv_path: str) -> str:
    """Return the hash-file path for a given CSV path."""
    return csv_path.replace("_events.csv", HASH_SUFFIX)


def write_hash(csv_path: str) -> str:
    """
    Compute SHA-256 of *csv_path* and write a sidecar _hash.txt.

    Returns the path to the written hash file.
    Raises FileNotFoundError if the CSV is missing.
    """
    digest = _hash_file(csv_path)
    path   = hash_path_from_csv(csv_path)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"SHA256:{digest}\n")
        f.write(f"File:{os.path.basename(csv_path)}\n")

    return path


def verify_hash(csv_path: str) -> tuple[bool, str]:
    """
    Verify *csv_path* against its sidecar hash file.

    Returns
    -------
    (True, "OK") on success.
    (False, <reason>) on failure or missing files.
    """
    hash_path = hash_path_from_csv(csv_path)

    if not os.path.exists(hash_path):
        return False, "No hash file found."
    if not os.path.exists(csv_path):
        return False, f"CSV not found: {csv_path}"

    with open(hash_path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    if not lines:
        return False, "Hash file is empty."

    stored = lines[0].replace("SHA256:", "").strip()
    computed = _hash_file(csv_path)

    if computed == stored:
        return True, "OK"
    return (
        False,
        f"Hash mismatch — file may have been altered.\n"
        f"  Stored:   {stored[:16]}…\n"
        f"  Computed: {computed[:16]}…",
    )


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()
