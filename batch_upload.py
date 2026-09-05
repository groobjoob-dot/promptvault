#!/usr/bin/env python3
"""
Batch upload images + prompts to Cloudflare R2 + create content files.

Usage:
    python3 batch_upload.py --prompts prompts.json --images-dir ./images/

prompts.json format:
[
  {
    "title": "Cinematic Portrait",
    "category": "portraits",
    "aiTool": "gpt",
    "description": "...",
    "prompt": "...",
    "tags": ["portrait", "cinematic"],
    "images": ["image1.webp", "image2.webp", "image3.webp"]
  }
]
"""

import os
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Load .env file if exists
def load_env():
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()

def slugify(text):
    import re
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

def run_wrangler(args):
    """Run a wrangler R2 command."""
    cmd = ["npx", "wrangler", "r2", "object"] + args
    return subprocess.run(cmd, capture_output=True, text=True, cwd="/Users/mystudio/Sites/promptvault")

def upload_to_r2(local_path: Path, r2_key: str) -> bool:
    """Upload file to R2 bucket."""
    result = run_wrangler([
        "put", str(local_path), r2_key,
        "--bucket", "promptvault-images",
        "--content-type", "image/webp",
    ])
    if result.returncode == 0:
        print(f"  ✓ Uploaded: {r2_key}")
        return True
    else:
        print(f"  ✗ Failed: {r2_key}")
        print(f"    {result.stderr}")
        return False

def upload_markdown(content: str, r2_key: str) -> bool:
    """Upload markdown to R2."""
    tmp_file = Path("/tmp") + r2_key
    tmp_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file.write_text(content)
    result = run_wrangler([
        "put", str(tmp_file), r2_key,
        "--bucket", "promptvault-images",
        "--content-type", "text/markdown",
    ])
    tmp_file.unlink()
    if result.returncode == 0:
        print(f"  ✓ MD uploaded: {r2_key}")
        return True
    else:
        print(f"  ✗ MD failed: {r2_key}")
        return False

def build_prompt_md(item: dict, slug: str, image_keys: list) -> str:
    """Generate Markdown file for a prompt."""
    hero = image_keys[0] if image_keys else ""
    gallery = image_keys[1:]

    today = datetime.now().strftime("%Y-%m-%d")

    frontmatter = f"""---
title: "{item['title']}"
titleHe: ""
category: "{item.get('category', 'cinematic').lower()}"
tags: {json.dumps(item.get('tags', []))}
image: "/cdn/{hero}"
gallery: {json.dumps([f"/cdn/{k}" for k in gallery])}
compatible: ["{item.get('aiTool', 'gpt').lower()}"]
difficulty: "{item.get('difficulty', 'intermediate')}"
publishedAt: {today}
featured: {str(item.get('featured', True)).lower()}
---

# {item['title']}

![{item['title']}](/cdn/{hero})

{item.get('description', '')}

## Prompt

```
{item.get('prompt', '')}
```

"""
    if gallery:
        frontmatter += f"""## Gallery

{chr(10).join([f"![{item['title']} - variation {i+1}](/cdn/{k})" for i, k in enumerate(gallery)])}
"""

    frontmatter += f"""## Compatible With

- **{item.get('aiTool', 'GPT')}** and similar AI image generators

## How to Use

1. Copy the prompt above
2. Paste it into {item.get('aiTool', 'your AI tool')}
3. Adjust settings as needed
4. Generate and enjoy!
"""
    return frontmatter

def main():
    parser = argparse.ArgumentParser(description="Batch upload prompts to PromptVault")
    parser.add_argument("--prompts", required=True, help="Path to prompts.json")
    parser.add_argument("--images-dir", required=True, help="Path to images directory")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually upload")
    args = parser.parse_args()

    with open(args.prompts) as f:
        prompts = json.load(f)

    images_dir = Path(args.images_dir)

    print(f"\n🚀 PromptVault Batch Upload")
    print(f"   Prompts: {len(prompts)}")
    print(f"   Images dir: {images_dir}")
    print()

    uploaded = 0
    failed = 0

    for idx, item in enumerate(prompts, 1):
        print(f"\n[{idx}/{len(prompts)}] {item['title']}")
        slug = slugify(item['title'])
        prompt_id = f"{slug}-{idx:03d}"

        # Upload images
        image_keys = []
        for i, img_name in enumerate(item.get('images', [])):
            local_path = images_dir / img_name
            if not local_path.exists():
                print(f"  ✗ Missing: {img_name}")
                continue

            ext = local_path.suffix.lstrip('.')
            r2_key = f"prompts/{prompt_id}/{i}.{ext}"
            if not args.dry_run:
                if upload_to_r2(local_path, r2_key):
                    image_keys.append(r2_key)
            else:
                image_keys.append(r2_key)
                print(f"  [DRY] Would upload: {r2_key}")

        if not image_keys:
            print(f"  ✗ No images uploaded, skipping")
            failed += 1
            continue

        # Generate and upload markdown
        md = build_prompt_md(item, prompt_id, image_keys)
        md_key = f"content/prompts/{prompt_id}.md"
        if not args.dry_run:
            if upload_markdown(md, md_key):
                uploaded += 1
            else:
                failed += 1
        else:
            print(f"  [DRY] Would upload MD: {md_key}")
            uploaded += 1

    print(f"\n{'='*50}")
    print(f"✅ Uploaded: {uploaded}")
    print(f"❌ Failed: {failed}")
    print(f"\nNext step: Trigger Cloudflare Pages rebuild")
    print(f"  Or visit: https://api.cloudflare.com/.../deploy-hook")

if __name__ == "__main__":
    main()
