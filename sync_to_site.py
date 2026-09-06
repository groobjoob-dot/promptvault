#!/usr/bin/env python3
"""
Sync script: Image → Prompt → R2 → Astro site

Usage:
    python3 sync_to_site.py                    # Interactive mode
    python3 sync_to_site.py --config item.json # From JSON
    python3 sync_to_site.py --batch items/      # Batch mode (folder of JSONs)
    python3 sync_to_site.py --from-telegram     # Webhook receiver mode
"""

import os
import sys
import json
import argparse
import subprocess
import requests
import boto3
import re
import hashlib
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Load .env
def load_env():
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()

# Config
VAULT = Path("/Users/mystudio/Documents/MyVault/MyVault/10_Resources/Content Library")
R2_BUCKET = "promptvault-images"
R2_BASE = "https://pub-8577310d5d0d45508bd4d705e1528e54.r2.dev"
PROMPTS_DIR = Path("/Users/mystudio/Sites/promptvault/src/content/prompts")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CLOUDFLARE_DEPLOY_HOOK = os.environ.get("CLOUDFLARE_DEPLOY_HOOK", "")


def slugify(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ.get('CLOUDFLARE_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def upload_to_r2(client, local_path: Path, r2_key: str) -> str:
    """Upload file to R2, return public URL."""
    content_type = "image/png" if local_path.suffix.lower() == ".png" else "image/jpeg"
    with open(local_path, "rb") as f:
        client.upload_fileobj(
            f, R2_BUCKET, r2_key,
            ExtraArgs={"ContentType": content_type}
        )
    return f"{R2_BASE}/{r2_key}"


def find_best_image(title: str, category: str) -> str:
    """Try to match title keywords to vault images."""
    images = list(VAULT.glob("Images/*"))
    if not images:
        return ""

    # Extract keywords from title
    keywords = re.findall(r'\b\w{4,}\b', title.lower())
    keywords = [k for k in keywords if k not in ['this', 'with', 'from', 'that', 'have', 'portrait', 'cinematic', 'style']]

    # Score each image by filename
    best_match = None
    best_score = 0
    for img in images:
        name_lower = img.stem.lower()
        score = sum(1 for k in keywords if k in name_lower)
        if score > best_score:
            best_score = score
            best_match = img

    return str(best_match) if best_match else str(images[0])


def create_prompt_md(item: dict, image_url: str, image_filename: str) -> tuple[str, str]:
    """Generate prompt.md file content. Returns (filename, content)."""
    title = item["title"]
    slug = slugify(title)

    frontmatter = f"""---
title: "{title}"
titleHe: ""
category: "{item.get('category', 'cinematic').lower()}"
tags: {json.dumps(item.get('tags', []))}
image: "{image_url}"
gallery: {json.dumps(item.get('gallery', []))}
compatible: {json.dumps(item.get('compatible', ['gpt']))}
difficulty: "{item.get('difficulty', 'intermediate')}"
publishedAt: {datetime.now().strftime("%Y-%m-%d")}
featured: {str(item.get('featured', True)).lower()}
---

# {title}

![{title}]({image_url})

{item.get('description', '')}

## Prompt

```
{item.get('prompt', '')}
```

## How to Use

1. Copy the prompt above
2. Paste it into {item.get('compatible', ['GPT'])[0]}
3. Adjust settings as needed
4. Generate and enjoy!
"""
    filename = f"{slug}.md"
    return filename, frontmatter


def save_prompt_md(filename: str, content: str) -> Path:
    """Save prompt.md to Astro content directory."""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PROMPTS_DIR / filename
    filepath.write_text(content)
    return filepath


def git_push():
    """Commit and push to trigger Cloudflare deploy."""
    repo_dir = "/Users/mystudio/Sites/promptvault"

    try:
        # Add
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", f"feat: add new prompts"],
            cwd=repo_dir, capture_output=True, text=True
        )

        if "nothing to commit" in result.stdout + result.stderr:
            return False

        # Push
        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=repo_dir, check=True, capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Git error: {e}")
        return False


def trigger_deploy_hook():
    """Trigger Cloudflare deploy hook."""
    if not CLOUDFLARE_DEPLOY_HOOK:
        return False
    try:
        requests.post(CLOUDFLARE_DEPLOY_HOOK, timeout=10)
        return True
    except Exception as e:
        print(f"❌ Hook error: {e}")
        return False


def process_item(item: dict) -> bool:
    """Process a single item: upload image + create md + deploy."""
    title = item.get("title", "Untitled")
    print(f"\n📝 Processing: {title}")

    # Find image
    if "image_path" in item:
        image_path = Path(item["image_path"])
    else:
        image_path = Path(find_best_image(title, item.get("category", "")))

    if not image_path.exists():
        print(f"  ✗ Image not found: {image_path}")
        return False

    # Upload to R2
    client = get_s3_client()
    img_ext = image_path.suffix.lower()
    r2_key = f"prompts/{slugify(title)}/hero{img_ext}"
    print(f"  ↑ Uploading image to R2: {r2_key}")

    try:
        image_url = upload_to_r2(client, image_path, r2_key)
        print(f"  ✓ Image: {image_url}")
    except Exception as e:
        print(f"  ✗ Upload failed: {e}")
        return False

    # Upload gallery if present
    gallery_urls = []
    for i, gallery_img in enumerate(item.get("gallery_images", [])):
        g_path = Path(gallery_img)
        if g_path.exists():
            g_key = f"prompts/{slugify(title)}/gallery-{i}{g_path.suffix.lower()}"
            try:
                g_url = upload_to_r2(client, g_path, g_key)
                gallery_urls.append(g_url)
                print(f"  ✓ Gallery {i}: {g_url}")
            except Exception as e:
                print(f"  ✗ Gallery {i} failed: {e}")

    item["gallery"] = gallery_urls

    # Create prompt.md
    filename, content = create_prompt_md(item, image_url, image_path.name)
    filepath = save_prompt_md(filename, content)
    print(f"  ✓ Created: {filepath.name}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Sync prompts to PromptVault site")
    parser.add_argument("--config", type=str, help="Path to JSON config")
    parser.add_argument("--batch", type=str, help="Folder with JSON configs")
    parser.add_argument("--from-telegram", action="store_true", help="Receive from Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Don't upload/deploy")
    args = parser.parse_args()

    items = []

    if args.config:
        with open(args.config) as f:
            items = [json.load(f)]
    elif args.batch:
        batch_dir = Path(args.batch)
        for json_file in batch_dir.glob("*.json"):
            with open(json_file) as f:
                items.append(json.load(f))
    elif args.from_telegram:
        # Will be handled by webhook server
        print("Run: python3 telegram_webhook_server.py")
        return
    else:
        print("Usage:")
        print("  python3 sync_to_site.py --config item.json")
        print("  python3 sync_to_site.py --batch items/")
        print("  python3 sync_to_site.py --from-telegram")
        return

    print(f"\n🚀 Syncing {len(items)} items")
    if args.dry_run:
        print("   [DRY RUN]")

    success = 0
    for item in items:
        if process_item(item):
            success += 1

    print(f"\n{'='*50}")
    print(f"✅ Processed: {success}/{len(items)}")

    if success > 0 and not args.dry_run:
        print("\n📤 Git push...")
        if git_push():
            print("✓ Pushed to GitHub — Cloudflare will auto-deploy")
        else:
            print("ℹ️  Nothing new to commit")
            print("   Triggering deploy hook...")
            if trigger_deploy_hook():
                print("✓ Deploy hook triggered")
            else:
                print("⚠️  Set CLOUDFLARE_DEPLOY_HOOK in .env")


if __name__ == "__main__":
    main()
