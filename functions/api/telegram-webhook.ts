// Cloudflare Pages Function: /api/telegram-webhook
// Receives Telegram channel posts and triggers site rebuild
//
// Flow:
// 1. Telegram → POST to this endpoint
// 2. Parse caption (Title/Category/AI Tool/etc.)
// 3. Download attached images
// 4. Upload images to R2
// 5. Save prompt.md to git repo (via GitHub API)
// 6. Cloudflare deploy hook auto-rebuilds site

interface Env {
  TELEGRAM_BOT_TOKEN: string;
  CLOUDFLARE_R2_ACCESS_KEY_ID: string;
  CLOUDFLARE_R2_SECRET_ACCESS_KEY: string;
  CLOUDFLARE_ACCOUNT_ID: string;
  GITHUB_TOKEN: string;
  CLOUDFLARE_DEPLOY_HOOK: string;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  try {
    const update = await context.request.json() as any;
    const post = update.channel_post || update.edited_channel_post;

    if (!post) {
      return jsonResponse({ ok: true, message: 'No channel post' });
    }

    if (!post.photo || !post.caption) {
      return jsonResponse({ ok: true, message: 'No photo or caption' });
    }

    const meta = parseCaption(post.caption);
    if (!meta.title) {
      return jsonResponse({ ok: false, error: 'Missing title' }, 400);
    }

    const slug = slugify(meta.title);
    const promptId = `${slug}-${post.message_id}`;
    const today = new Date(post.date * 1000).toISOString().split('T')[0];

    // Step 1: Download and upload ONLY the highest-quality image to R2
    const photoUrls = await uploadImages(
      post.photo,
      promptId,
      context.env
    );

    if (photoUrls.length === 0) {
      return jsonResponse({ ok: false, error: 'No images uploaded' }, 500);
    }

    // Use only the first (best quality) image
    const heroUrl = photoUrls[0];

    // Step 2: Generate prompt.md content
    const md = generatePromptMarkdown({
      title: meta.title,
      category: meta.category || 'cinematic',
      aiTool: meta.aiTool || 'gpt',
      description: meta.description || '',
      prompt: meta.prompt || '',
      tags: meta.tags || [],
      heroUrl: heroUrl,
      date: today,
    });

    // Step 3: Save to GitHub (commits to repo)
    await commitToGitHub(
      `src/content/prompts/${promptId}.md`,
      md,
      `feat: add prompt "${meta.title}"`,
      context.env
    );

    // Step 4: Cloudflare deploy hook will auto-trigger via GitHub push
    // (no need to call it manually)

    return jsonResponse({
      ok: true,
      slug: promptId,
      title: meta.title,
      imagesUploaded: photoUrls.length,
      note: 'Cloudflare Pages will auto-deploy from GitHub push',
    });
  } catch (err: any) {
    console.error('Webhook error:', err);
    return jsonResponse({ ok: false, error: err.message }, 500);
  }
};

// === Helper functions ===

function jsonResponse(data: any, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function parseCaption(caption: string): any {
  const result: any = {};
  const lines = caption.split('\n');
  for (const line of lines) {
    const match = line.match(/^([A-Za-z\s]+):\s*(.+)$/);
    if (match) {
      const key = match[1].trim().toLowerCase();
      const value = match[2].trim();
      if (key === 'title') result.title = value;
      else if (['category', 'cat'].includes(key)) result.category = value.toLowerCase();
      else if (['tool', 'ai tool', 'ai'].includes(key)) result.aiTool = value.toLowerCase();
      else if (['description', 'desc'].includes(key)) result.description = value;
      else if (key === 'tags') {
        result.tags = value.split(',').map((t: string) => t.trim().toLowerCase()).filter(Boolean);
      }
      else if (key === 'prompt') result.prompt = value;
    }
  }
  return result;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim();
}

async function uploadImages(
  photos: any[],
  promptId: string,
  env: Env
): Promise<string[]> {
  const urls: string[] = [];
  const BUCKET = 'promptvault-images';

  // Take ONLY the largest photo (highest quality, last in array)
  const photo = photos[photos.length - 1];
  if (!photo) return urls;

  try {
    // Get file path from Telegram
    const fileInfo = await getTelegramFile(env.TELEGRAM_BOT_TOKEN, photo.file_id);
    if (!fileInfo) return urls;

    // Download file
    const fileBuffer = await downloadTelegramFile(env.TELEGRAM_BOT_TOKEN, fileInfo.file_path);
    if (!fileBuffer) return urls;

    // Upload to R2
    const ext = 'jpg'; // Telegram photos are JPEG
    const r2Key = `prompts/${promptId}/hero.${ext}`;

    const r2Url = await uploadToR2(fileBuffer, r2Key, env);
    if (r2Url) {
      urls.push(r2Url);
    }
  } catch (err) {
    console.error(`Failed to upload photo:`, err);
  }

  return urls;
}

async function getTelegramFile(token: string, fileId: string): Promise<{ file_path: string } | null> {
  const res = await fetch(
    `https://api.telegram.org/bot${token}/getFile?file_id=${fileId}`
  );
  if (!res.ok) return null;
  const data = await res.json() as any;
  return data.ok ? data.result : null;
}

async function downloadTelegramFile(token: string, filePath: string): Promise<ArrayBuffer | null> {
  const res = await fetch(
    `https://api.telegram.org/file/bot${token}/${filePath}`
  );
  if (!res.ok) return null;
  return await res.arrayBuffer();
}

async function uploadToR2(
  buffer: ArrayBuffer,
  key: string,
  env: Env
): Promise<string | null> {
  const R2_BASE = `https://${env.CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com`;
  const BUCKET = 'promptvault-images';
  const url = `${R2_BASE}/${BUCKET}/${key}`;

  // Use S3-compatible PUT
  const date = new Date().toUTCString();
  const contentType = 'image/jpeg';

  // Use signed request via Cloudflare API (simplified for Pages)
  // For production, use AWS S3 SDK with credentials
  try {
    // Use Cloudflare R2 S3 API
    const aws = await import('aws4fetch'); // optional
    // For now, use a simple PUT with public access
    const res = await fetch(url, {
      method: 'PUT',
      headers: {
        'Content-Type': contentType,
        // R2 public bucket - no auth needed
      },
      body: buffer,
    });

    if (res.ok) {
      // Return public URL (R2.dev subdomain)
      return `https://pub-${env.CLOUDFLARE_ACCOUNT_ID}.r2.dev/${BUCKET}/${key}`;
    }
  } catch (err) {
    console.error('R2 upload error:', err);
  }
  return null;
}

function generatePromptMarkdown(data: {
  title: string;
  category: string;
  aiTool: string;
  description: string;
  prompt: string;
  tags: string[];
  heroUrl: string;
  date: string;
}): string {
  return `---
title: "${data.title.replace(/"/g, '\\"')}"
titleHe: ""
category: "${data.category}"
tags: ${JSON.stringify(data.tags)}
image: "${data.heroUrl}"
gallery: []
compatible: ["${data.aiTool}"]
difficulty: "intermediate"
publishedAt: ${data.date}
featured: true
---

# ${data.title}

![${data.title}](${data.heroUrl})

${data.description}

## Prompt

\`\`\`
${data.prompt}
\`\`\`

## How to Use

1. Copy the prompt above
2. Paste into ${data.aiTool.toUpperCase()}
3. Adjust settings as needed
4. Generate and enjoy!
`;
}

async function commitToGitHub(
  filePath: string,
  content: string,
  message: string,
  env: Env
): Promise<boolean> {
  try {
    // Get current file SHA (if exists)
    const getRes = await fetch(
      `https://api.github.com/repos/groobjoob-dot/promptvault/contents/${filePath}`,
      {
        headers: {
          'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
          'Accept': 'application/vnd.github+json',
        },
      }
    );

    let sha: string | undefined;
    if (getRes.ok) {
      const file = await getRes.json() as any;
      sha = file.sha;
    }

    // Create or update file
    const putRes = await fetch(
      `https://api.github.com/repos/groobjoob-dot/promptvault/contents/${filePath}`,
      {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
          'Accept': 'application/vnd.github+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message,
          content: btoa(unescape(encodeURIComponent(content))),
          sha,
          branch: 'main',
        }),
      }
    );

    return putRes.ok;
  } catch (err) {
    console.error('GitHub commit error:', err);
    return false;
  }
}
