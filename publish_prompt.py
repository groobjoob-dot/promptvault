#!/usr/bin/env python3
"""
Publish prompt to PromptVault site + Telegram channel.

Usage:
    python3 publish_prompt.py \\
        --image ./image.jpg \\
        --title "Cyberpunk Samurai at Night" \\
        --category cinematic \\
        --tool midjourney \\
        --tags cyberpunk,samurai,neon \\
        --description "A neon-lit samurai walking..." \\
        --prompt "Full prompt text here..."

Or from JSON config:
    python3 publish_prompt.py --config item.json
"""

import os
import sys
import json
import argparse
import subprocess
import requests
import boto3
import re
import urllib.parse
from pathlib import Path
from datetime import datetime
from getpass import getpass

# Load .env
def load_env():
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()

# === Config ===
VAULT_PROMPTS = Path.home() / "Documents" / "MyVault" / "MyVault" / "10_Resources" / "Content Library" / "Prompts"
PROMPTS_DIR = Path("/Users/mystudio/Sites/promptvault/src/content/prompts")
R2_BUCKET = "promptvault-images"
R2_PUBLIC_BASE = "https://pub-8577310d5d0d45508bd4d705e1528e54.r2.dev"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "groobjoob-dot/promptvault"


# === Helpers ===

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


def upload_to_r2(image_path: Path, prompt_id: str) -> str:
    """Upload image to R2, return public URL."""
    client = get_s3_client()
    ext = image_path.suffix.lower() or ".jpg"
    r2_key = f"prompts/{prompt_id}/hero{ext}"
    content_type = f"image/{ext.lstrip('.')}" if ext in [".jpg", ".jpeg", ".png", ".webp"] else "image/jpeg"

    print(f"  ↑ Uploading to R2: {r2_key}")
    with open(image_path, "rb") as f:
        client.upload_fileobj(
            f, R2_BUCKET, r2_key,
            ExtraArgs={"ContentType": content_type}
        )
    return f"{R2_PUBLIC_BASE}/{r2_key}"


def save_prompt_to_vault(item: dict, prompt_id: str) -> Path:
    """Save prompt as Markdown in Obsidian vault."""
    VAULT_PROMPTS.mkdir(parents=True, exist_ok=True)

    frontmatter = f"""---
title: "{item['title']}"
category: {item['category']}
aiTool: {item['tool']}
tags: [{', '.join(item.get('tags', []))}]
description: "{item.get('description', '')}"
image: "{item.get('image_url', '')}"
publishedAt: {datetime.now().strftime('%Y-%m-%d')}
status: published
---

# {item['title']}

![Hero]({item.get('image_url', '')})

## Image

**Local file:** `{item.get('image_filename', 'N/A')}`
**R2 URL:** {item.get('image_url', 'N/A')}

## Description

{item.get('description', '')}

## Prompt

```
{item['prompt']}
```

## Metadata

- **Category:** {item['category']}
- **AI Tool:** {item['tool']}
- **Tags:** {', '.join(item.get('tags', []))}
- **Prompt ID:** {prompt_id}
- **URL:** https://promptvault-72s.pages.dev/prompt/{prompt_id}
"""

    filepath = VAULT_PROMPTS / f"{prompt_id}.md"
    filepath.write_text(frontmatter)
    print(f"  💾 Saved to vault: {filepath}")
    return filepath


def create_prompt_md(item: dict, image_url: str, prompt_id: str) -> str:
    """Generate Astro prompt.md content."""
    return f"""---
title: "{item['title'].replace(chr(34), chr(92) + chr(34))}"
titleHe: ""
category: "{item['category']}"
tags: {json.dumps(item.get('tags', []))}
image: "{image_url}"
gallery: []
compatible: ["{item['tool']}"]
difficulty: "intermediate"
publishedAt: {datetime.now().strftime('%Y-%m-%d')}
featured: true
---

# {item['title']}

![{item['title']}]({image_url})

{item.get('description', '')}

## Prompt

```
{item['prompt']}
```

## How to Use

1. Copy the prompt above
2. Paste into {item['tool'].upper()}
3. Adjust settings as needed
4. Generate and enjoy!
"""


def commit_to_github(content: str, file_path: str, message: str) -> bool:
    """Commit file to GitHub repo via API."""
    print(f"  📤 Committing to GitHub: {file_path}")

    # Get existing file SHA if exists
    get_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    get_headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    sha = None
    try:
        resp = requests.get(get_url, headers=get_headers, timeout=10)
        if resp.ok:
            sha = resp.json().get("sha")
    except Exception:
        pass

    # Create or update
    put_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    payload = {
        "message": message,
        "content": base64_encode(content),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(put_url, headers={**get_headers, "Content-Type": "application/json"}, json=payload, timeout=30)
        if resp.ok:
            print(f"  ✓ Committed: {resp.json().get('commit', {}).get('sha', 'unknown')[:8]}")
            return True
        else:
            print(f"  ✗ GitHub error: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ✗ GitHub error: {e}")
        return False


def base64_encode(text: str) -> str:
    import base64
    return base64.b64encode(text.encode()).decode()


def wait_for_deploy(max_wait: int = 60) -> bool:
    """Wait for Cloudflare Pages to deploy after GitHub push."""
    print(f"  ⏳ Waiting for deploy (max {max_wait}s)...")
    import time
    start = time.time()
    while time.time() - start < max_wait:
        try:
            resp = requests.get("https://promptvault-72s.pages.dev/", timeout=5)
            if resp.ok:
                elapsed = int(time.time() - start)
                print(f"  ✓ Site updated ({elapsed}s)")
                return True
        except Exception:
            pass
        time.sleep(3)
    print(f"  ⚠️ Deploy timeout ({max_wait}s)")
    return False


def send_to_telegram_bot(item: dict, prompt_id: str, image_url: str) -> bool:
    """Send the published prompt to the Telegram bot to publish to channel."""
    print(f"  📱 Sending to Telegram bot...")

    # Build caption for the channel post
    channel_text = f"""⚡ *{item['title']}*

🎨 {item['category'].title()} · {item['tool'].upper()}

{item.get('description', '')}

🔗 Get the full prompt → https://promptvault-72s.pages.dev/prompt/{prompt_id}

#PromptVault #{item['category']} #{item['tool']}"""

    # Send photo to channel
    send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "photo": image_url,
        "caption": channel_text,
        "parse_mode": "Markdown",
    }

    try:
        resp = requests.post(send_url, json=payload, timeout=15)
        if resp.ok:
            msg_id = resp.json().get("result", {}).get("message_id")
            print(f"  ✓ Published to channel (msg #{msg_id})")
            return True
        else:
            print(f"  ✗ Telegram error: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ✗ Telegram error: {e}")
        return False


# === Main Flow ===

def process_item(item: dict) -> bool:
    """Process a single prompt item end-to-end."""
    title = item["title"]
    print(f"\n{'='*60}")
    print(f"📝 Publishing: {title}")
    print(f"{'='*60}")

    # Find image file
    image_path = Path(item.get("image_path", ""))
    if not image_path.exists():
        print(f"❌ Image not found: {image_path}")
        return False

    # Generate prompt_id
    slug = slugify(title)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prompt_id = f"{slug}-{timestamp}"

    # Step 1: Upload image to R2
    print("\n[1/4] Uploading to R2...")
    image_url = upload_to_r2(image_path, prompt_id)
    item["image_url"] = image_url
    item["image_filename"] = image_path.name

    # Step 2: Save to Obsidian vault
    print("\n[2/4] Saving to Obsidian vault...")
    save_prompt_to_vault(item, prompt_id)

    # Step 3: Commit to GitHub (triggers Cloudflare deploy)
    print("\n[3/4] Committing to GitHub...")
    md_content = create_prompt_md(item, image_url, prompt_id)
    github_path = f"src/content/prompts/{prompt_id}.md"
    if not commit_to_github(md_content, github_path, f"feat: add prompt '{title}'"):
        return False

    # Wait for deploy
    wait_for_deploy(60)

    # Step 4: Publish to Telegram channel
    print("\n[4/4] Publishing to Telegram channel...")
    send_to_telegram_bot(item, prompt_id, image_url)

    print(f"\n✅ DONE! {title} is now:")
    print(f"   📁 In vault: {VAULT_PROMPTS}/{prompt_id}.md")
    print(f"   🌐 On site: https://promptvault-72s.pages.dev/prompt/{prompt_id}")
    print(f"   📱 In channel: {TELEGRAM_CHANNEL_ID}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Publish prompt to PromptVault site + Telegram")
    parser.add_argument("--image", type=str, help="Path to image file")
    parser.add_argument("--title", type=str, help="Prompt title")
    parser.add_argument("--category", type=str, help="Category (portraits, cinematic, 3d, etc.)")
    parser.add_argument("--tool", type=str, help="AI tool (gpt, midjourney, gemini, etc.)")
    parser.add_argument("--tags", type=str, help="Comma-separated tags")
    parser.add_argument("--description", type=str, default="", help="Short description")
    parser.add_argument("--prompt", type=str, help="Full prompt text")
    parser.add_argument("--config", type=str, help="Path to JSON config (alternative to flags)")
    args = parser.parse_args()

    # Build item from args
    if args.config:
        with open(args.config) as f:
            item = json.load(f)
    elif args.image and args.title and args.prompt:
        item = {
            "image_path": args.image,
            "title": args.title,
            "category": args.category or "cinematic",
            "tool": args.tool or "gpt",
            "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
            "description": args.description,
            "prompt": args.prompt,
        }
    else:
        print("Usage:")
        print("  python3 publish_prompt.py --image <path> --title <title> --prompt <text> [options]")
        print("  python3 publish_prompt.py --config <file.json>")
        print()
        print("Required: --image, --title, --prompt, --category, --tool")
        sys.exit(1)

    # Verify required credentials
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("❌ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID in .env")
        sys.exit(1)
    if not GITHUB_TOKEN:
        print("❌ Missing GITHUB_TOKEN in .env")
        sys.exit(1)

    # Process
    success = process_item(item)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
