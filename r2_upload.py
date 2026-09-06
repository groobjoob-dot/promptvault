#!/usr/bin/env python3
"""
R2 Upload Script for Content Library
Uploads Images, Videos, and Documents to Cloudflare R2 in parallel.

Usage:
    python3 r2_upload.py [--dry-run] [--parallel 4]
"""

import os
import sys
import argparse
import boto3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import mimetypes
import time

# Load .env file
def load_env():
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()

# Config
ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
ACCESS_KEY = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID")
SECRET_KEY = os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
ENDPOINT = os.environ.get("CLOUDFLARE_R2_ENDPOINT") or f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"
BUCKET = "promptvault-images"

VAULT = Path("/Users/mystudio/Documents/MyVault/MyVault/10_Resources/Content Library")

# Folders to upload (relative paths in vault -> R2 prefix)
FOLDERS = {
    "Images": "library/images",
    "Videos": "library/videos",
    "Documents": "library/documents",
}

# File type config
SKIP_EXTENSIONS = {".crdownload", ".part", ".tmp", ".DS_Store"}


def get_s3_client():
    """Get boto3 S3 client for R2."""
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="auto",
    )


def upload_file(client, local_path: Path, r2_key: str) -> tuple[str, bool, str]:
    """Upload single file to R2. Returns (filename, success, message)."""
    try:
        content_type, _ = mimetypes.guess_type(str(local_path))
        if not content_type:
            content_type = "application/octet-stream"

        size = local_path.stat().st_size
        # S3 metadata only supports ASCII - use safe-name + original-name-safe
        with open(local_path, "rb") as f:
            client.upload_fileobj(
                f,
                BUCKET,
                r2_key,
                ExtraArgs={
                    "ContentType": content_type,
                    "Metadata": {
                        "original-name": local_path.name.encode('ascii', 'ignore').decode('ascii') or 'file',
                        "uploaded-at": datetime.now().isoformat(),
                    },
                },
            )
        return (local_path.name, True, f"{size:,} bytes")
    except Exception as e:
        return (local_path.name, False, str(e)[:100])


def main():
    parser = argparse.ArgumentParser(description="Upload Content Library to R2")
    parser.add_argument("--dry-run", action="store_true", help="List files without uploading")
    parser.add_argument("--parallel", type=int, default=4, help="Parallel uploads")
    args = parser.parse_args()

    # Verify credentials
    if not all([ACCOUNT_ID, ACCESS_KEY, SECRET_KEY]):
        print("❌ Missing R2 credentials in .env")
        print("   Required: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_R2_ACCESS_KEY_ID, CLOUDFLARE_R2_SECRET_ACCESS_KEY")
        sys.exit(1)

    # Collect files
    files_to_upload = []
    for folder, prefix in FOLDERS.items():
        folder_path = VAULT / folder
        if not folder_path.exists():
            continue
        for file_path in folder_path.iterdir():
            if file_path.is_file() and file_path.suffix not in SKIP_EXTENSIONS:
                r2_key = f"{prefix}/{file_path.name}"
                files_to_upload.append((file_path, r2_key))

    print(f"\n🚀 R2 Upload — Content Library → {BUCKET}")
    print(f"   Files: {len(files_to_upload)}")
    print(f"   Parallel: {args.parallel}")
    print(f"   Endpoint: {ENDPOINT}\n")

    if args.dry_run:
        print("=== DRY RUN — files that would be uploaded ===\n")
        for local, r2 in files_to_upload:
            size = local.stat().st_size
            print(f"  {local.name:50s} → {r2} ({size:,} bytes)")
        return

    # Connect
    try:
        client = get_s3_client()
        print("✅ Connected to R2\n")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        sys.exit(1)

    # Upload in parallel
    start = time.time()
    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = {
            executor.submit(upload_file, client, local, r2): (local, r2)
            for local, r2 in files_to_upload
        }

        for i, future in enumerate(as_completed(futures), 1):
            local, r2 = futures[future]
            name, ok, msg = future.result()
            status = "✓" if ok else "✗"
            size_str = f"({local.stat().st_size:,} bytes)" if local.exists() else ""
            print(f"  [{i:3d}/{len(files_to_upload)}] {status} {name[:45]:45s} {msg}")
            if ok:
                success += 1
            else:
                failed += 1

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"✅ Uploaded: {success}")
    print(f"❌ Failed:   {failed}")
    print(f"⏱️  Time:     {elapsed:.1f}s")
    print(f"\n🌐 R2 endpoint: {ENDPOINT}")
    print(f"📦 Bucket: {BUCKET}")
    print(f"📁 Library: {', '.join(FOLDERS.keys())}")


if __name__ == "__main__":
    main()
