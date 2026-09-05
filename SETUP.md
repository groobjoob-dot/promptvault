# 🚀 PromptVault — Setup Guide

## Architecture

```
┌─────────────────┐
│  📱 Telegram    │
│     Channel     │
└────────┬────────┘
         │ Webhook
         ↓
┌─────────────────┐
│ Cloudflare Pages │
│   Function:     │
│  /api/telegram  │
│   -webhook      │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ Cloudflare R2    │
│  promptvault-   │
│    images       │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ Cloudflare Pages │
│   Build + CDN   │
│ promptvault.dev │
└─────────────────┘
```

## Step 1: Cloudflare Setup

### 1.1 Create R2 Bucket

1. Go to https://dash.cloudflare.com → R2
2. Click "Create bucket"
3. Name: `promptvault-images`
4. Region: Automatic

### 1.2 Connect Domain (Optional)

1. R2 → `promptvault-images` → Settings
2. Custom domain: `images.promptvault.dev`
3. Or use: `<account-id>.r2.cloudflarestorage.com`

### 1.3 Get R2 API Token

1. R2 → Manage R2 API Tokens
2. Create token with:
   - Permissions: Object Read & Write
   - Bucket: `promptvault-images`
3. Save the Access Key ID and Secret Access Key

### 1.4 Create Pages Project

1. Cloudflare → Workers & Pages → Create
2. Pages → Connect to Git
3. Select your GitHub repo (e.g. `yurinzon/promptvault`)
4. Build settings:
   - Build command: `npm run build`
   - Output directory: `dist`
5. Save and Deploy

### 1.5 Add R2 Binding

1. Pages → promptvault → Settings → Functions
2. R2 Bucket Bindings:
   - Variable name: `PROMPTS`
   - Bucket: `promptvault-images`

### 1.6 Set Environment Variables

1. Pages → Settings → Environment Variables
2. Add:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `DEPLOY_HOOK_URL` = (created in next step)
   - `R2_ACCESS_KEY_ID` = from 1.3
   - `R2_SECRET_ACCESS_KEY` = from 1.3

### 1.7 Create Deploy Hook

1. Pages → Settings → Builds
2. Create deploy hook: "telegram-new-prompt"
3. Copy the URL → save as `DEPLOY_HOOK_URL`

---

## Step 2: Telegram Bot Setup

### 2.1 Create Bot

1. Open Telegram, message [@BotFather](https://t.me/BotFather)
2. Send: `/newbot`
3. Name: `PromptVault Bot`
4. Username: `promptvault_bot` (or unique name)
5. **Save the token** (looks like `123456:ABC-DEF...`)

### 2.2 Create Channel

1. Create new channel in Telegram
2. Add your bot as **admin** (with "Post messages" permission)
3. Get channel ID:
   - Post any message in the channel
   - Visit: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Look for `"chat":{"id":-1001234567890}` — this is your channel ID

### 2.3 Set Webhook

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://promptvault.dev/api/telegram-webhook",
    "allowed_updates": ["channel_post", "edited_channel_post"]
  }'
```

Replace `<YOUR_BOT_TOKEN>` and verify the URL matches your Pages project.

### 2.4 Verify Webhook

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

Should show your URL with `pending_update_count: 0`

---

## Step 3: Post Format

Posts in your Telegram channel should follow this format:

### 3.1 Caption Template

```
Title: Ultra-Realistic Editorial Male Portrait
Category: Portraits
AI Tool: GPT Image 2
Tags: portrait, male, editorial, natural-light
Description: A hyper-realistic editorial portrait of a 32-year-old man...
Prompt: Create an ultra-realistic editorial portrait...
```

### 3.2 Rules

- **Photos:** Attach 1-4 images (last 4 are used, best quality)
- **Required fields:** `Title:`, `Category:`, `AI Tool:`, `Prompt:`
- **Optional fields:** `Description:`, `Tags:` (comma-separated)
- **Categories:** must match existing category ID (see below)
- **AI Tools:** gpt, gemini, midjourney, sora, veo3, leonardo, flux

### 3.3 Available Categories

| ID | Name |
|----|------|
| portraits | Portraits |
| cinematic | Cinematic |
| 3d | 3D & Stylized |
| realistic | Realistic |
| art | Art & Illustration |
| video | Video |
| products | Products |
| anime | Anime |
| car | Cars & Vehicles |
| animals | Animals & Pets |
| drawing | Drawing & Sketch |
| nature | Nature & Landscape |
| ui-design | UI/UX & Branding |
| scifi | Sci-Fi & Fantasy |
| tools | Developer Tools |

### 3.4 Example Post

Title: Cinematic Street Fashion Portrait
Category: Cinematic
AI Tool: Midjourney
Tags: streetwear, fashion, night, neon
Description: A moody nighttime street fashion portrait with neon lighting
Prompt: A cinematic street fashion portrait of a young model walking through a rainy Tokyo alley at night. Wearing oversized black leather jacket with neon orange accents...

[📷 Attach 4 images: hero, variation 1, 2, 3]

### 3.5 What Happens After You Post

1. ⏱️ Bot receives post (instant)
2. 📥 Images downloaded to R2 (1-3 sec)
3. 📝 Markdown file created in R2
4. 🚀 Cloudflare Pages rebuild triggered
5. 🌐 Live at `promptvault.dev/<slug>` (30-60 sec)

---

## Step 4: Batch Upload (Manual)

If you have existing images + prompts, use the batch script:

### 4.1 Create prompts.json

```json
[
  {
    "title": "Ultra-Realistic Editorial Male Portrait",
    "category": "portraits",
    "aiTool": "gpt",
    "description": "...",
    "prompt": "...",
    "tags": ["portrait", "male"],
    "images": ["1.webp", "2.webp", "3.webp", "4.webp"],
    "featured": true
  }
]
```

### 4.2 Organize Images

```
images/
├── 1.webp
├── 2.webp
├── 3.webp
└── 4.webp
```

### 4.3 Run Upload

```bash
cd /Users/mystudio/Sites/promptvault
python3 batch_upload.py --prompts ./prompts.json --images-dir ./images/
```

### 4.4 Dry Run First

```bash
python3 batch_upload.py --prompts ./prompts.json --images-dir ./images/ --dry-run
```

---

## Step 5: Local Development

### 5.1 Run Dev Server

```bash
cd /Users/mystudio/Sites/promptvault
npm run dev
```

Visit: http://localhost:4321/

### 5.2 Test Webhook Locally

Use ngrok or Cloudflare Tunnel:

```bash
npm install -g cloudflared
cloudflared tunnel --url http://localhost:4321
```

Then set webhook to the tunnel URL.

### 5.3 Add R2 Locally

1. Install Wrangler: `npm install -g wrangler`
2. Login: `wrangler login`
3. List buckets: `wrangler r2 bucket list`
4. Upload: `wrangler r2 object put promptvault-images/test.txt --remote`

---

## Step 6: Git Workflow

### 6.1 First Push

```bash
cd /Users/mystudio/Sites/promptvault
git init
git add .
git commit -m "Initial PromptVault setup"
git branch -M main
git remote add origin https://github.com/yurinzon/promptvault.git
git push -u origin main
```

### 6.2 Future Updates

```bash
git add .
git commit -m "Add new prompts"
git push
```

Cloudflare Pages will auto-rebuild.

---

## Cost Breakdown

| Service | Free Tier | Cost Beyond |
|---------|-----------|-------------|
| Cloudflare Pages | Unlimited requests | $0 |
| Cloudflare R2 | 10GB storage + 10M requests | $0.015/GB/month |
| Telegram Bot API | Unlimited | $0 |
| Wrangler CLI | 500 deploys/day | $0 |
| **Total (up to 1000 prompts)** | | **$0** |

---

## Troubleshooting

### Webhook not working?

```bash
# Check webhook status
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# Should show:
# {"ok":true,"result":{"url":"https://...","pending_update_count":0}}
```

If `last_error_message` shows, check:
- Bot is admin in channel
- URL is HTTPS
- Cloudflare Pages function is deployed

### Images not loading?

- Check R2 bucket is public (Settings → Public access)
- Or use custom domain
- Verify image keys in R2: `wrangler r2 object list promptvault-images`

### Build failing?

- Check Pages function logs
- Verify `wrangler.toml` is correct
- Test build locally: `npm run build`

---

## Next Steps

- [ ] Set up Cloudflare R2 bucket
- [ ] Create Telegram bot
- [ ] Set webhook
- [ ] Push to GitHub
- [ ] Connect to Cloudflare Pages
- [ ] Post first test message
- [ ] Verify it appears on site
- [ ] Run batch upload for existing images

🤖 *Generated by PromptVault setup wizard*
