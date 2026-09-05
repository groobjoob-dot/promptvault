// Cloudflare Pages Function: /api/telegram-webhook
// Receives Telegram channel posts and creates new prompt files

interface Env {
  PROMPTS: R2Bucket;
  TELEGRAM_BOT_TOKEN: string;
  DEPLOY_HOOK_URL: string;
  GITHUB_TOKEN?: string;
  GITHUB_REPO?: string; // e.g. "yurinzon/promptvault"
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  try {
    const update = await context.request.json() as any;

    // Look for channel_post (post in channel) or edited_channel_post
    const post = update.channel_post || update.edited_channel_post;
    if (!post) {
      return new Response(JSON.stringify({ ok: true, message: 'No channel post' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Must have photos and caption
    if (!post.photo || !post.caption) {
      return new Response(JSON.stringify({ ok: true, message: 'No photo or caption' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Parse caption
    const meta = parseCaption(post.caption);
    if (!meta.title) {
      return new Response(JSON.stringify({ ok: false, error: 'Missing title' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Generate slug
    const slug = slugify(meta.title);
    const promptId = `${slug}-${post.message_id}`;

    // Download up to 4 images (last 4 are highest quality)
    const photos = post.photo.slice(-4);
    const imageKeys: string[] = [];
    for (let i = 0; i < photos.length; i++) {
      const photo = photos[i];
      const fileId = photo.file_id;
      const ext = 'webp';
      const r2Key = `prompts/${promptId}/${i}.${ext}`;

      // Get file info from Telegram
      const fileInfo = await getTelegramFile(context.env.TELEGRAM_BOT_TOKEN, fileId);
      if (!fileInfo) continue;

      // Download file
      const fileBuffer = await downloadTelegramFile(context.env.TELEGRAM_BOT_TOKEN, fileInfo.file_path);
      if (!fileBuffer) continue;

      // Upload to R2
      await context.env.PROMPTS.put(r2Key, fileBuffer, {
        httpMetadata: { contentType: 'image/webp' },
        customMetadata: { originalName: `${slug}-${i}` },
      });
      imageKeys.push(r2Key);
    }

    if (imageKeys.length === 0) {
      return new Response(JSON.stringify({ ok: false, error: 'Failed to upload any image' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Build the markdown file
    const heroImage = imageKeys[0];
    const galleryImages = imageKeys.slice(1);

    const md = buildPromptMarkdown({
      title: meta.title,
      category: meta.category || 'cinematic',
      aiTool: meta.aiTool || 'gpt',
      description: meta.description || '',
      prompt: meta.prompt || '',
      tags: meta.tags || [],
      slug: promptId,
      heroImage,
      galleryImages,
      postDate: new Date(post.date * 1000).toISOString().split('T')[0],
    });

    // Save markdown file to R2 (or commit to GitHub for Pages to pick up)
    const mdKey = `content/prompts/${promptId}.md`;
    await context.env.PROMPTS.put(mdKey, md, {
      httpMetadata: { contentType: 'text/markdown' },
    });

    // Trigger Cloudflare Pages rebuild
    if (context.env.DEPLOY_HOOK_URL) {
      await triggerDeploy(context.env.DEPLOY_HOOK_URL);
    }

    return new Response(JSON.stringify({
      ok: true,
      slug: promptId,
      title: meta.title,
      imagesUploaded: imageKeys.length,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    console.error('Webhook error:', err);
    return new Response(JSON.stringify({ ok: false, error: err.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};

function parseCaption(caption: string) {
  const result: any = {};
  const lines = caption.split('\n');
  for (const line of lines) {
    const match = line.match(/^([A-Za-z\s]+):\s*(.+)$/);
    if (match) {
      const key = match[1].trim().toLowerCase();
      const value = match[2].trim();
      if (key === 'title') result.title = value;
      else if (key === 'category' || key === 'cat') result.category = value;
      else if (key === 'tool' || key === 'ai tool' || key === 'ai') result.aiTool = value;
      else if (key === 'description' || key === 'desc') result.description = value;
      else if (key === 'tags') result.tags = value.split(',').map(t => t.trim());
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

async function getTelegramFile(botToken: string, fileId: string): Promise<{ file_path: string } | null> {
  const res = await fetch(`https://api.telegram.org/bot${botToken}/getFile?file_id=${fileId}`);
  if (!res.ok) return null;
  const data = await res.json() as any;
  return data.ok ? data.result : null;
}

async function downloadTelegramFile(botToken: string, filePath: string): Promise<ArrayBuffer | null> {
  const res = await fetch(`https://api.telegram.org/file/bot${botToken}/${filePath}`);
  if (!res.ok) return null;
  return await res.arrayBuffer();
}

function buildPromptMarkdown(data: {
  title: string;
  category: string;
  aiTool: string;
  description: string;
  prompt: string;
  tags: string[];
  slug: string;
  heroImage: string;
  galleryImages: string[];
  postDate: string;
}): string {
  const frontmatter = `---
title: "${data.title.replace(/"/g, '\\"')}"
titleHe: ""
category: "${data.category.toLowerCase()}"
tags: ${JSON.stringify(data.tags)}
image: "/cdn/${data.heroImage}"
gallery: ${JSON.stringify(data.galleryImages.map(k => `/cdn/${k}`))}
compatible: ["${data.aiTool.toLowerCase()}"]
difficulty: "intermediate"
publishedAt: ${data.postDate}
featured: true
---

# ${data.title}

![${data.title}](/cdn/${data.heroImage})

${data.description ? `## Description\n\n${data.description}\n` : ''}
## Prompt

\`\`\`
${data.prompt}
\`\`\`

${data.galleryImages.length > 0 ? `## Gallery

${data.galleryImages.map((img, i) => `![${data.title} - variation ${i + 1}](/cdn/${img})`).join('\n')}
` : ''}
## Compatible With

- **${data.aiTool}** and similar AI image generators

## How to Use

1. Copy the prompt above
2. Paste it into ${data.aiTool}
3. Adjust settings as needed
4. Generate and enjoy!
`;
  return frontmatter;
}

async function triggerDeploy(hookUrl: string) {
  try {
    await fetch(hookUrl, { method: 'POST' });
  } catch (err) {
    console.error('Deploy trigger failed:', err);
  }
}
