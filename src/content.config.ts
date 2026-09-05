import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const prompts = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/prompts' }),
  schema: z.object({
    title: z.string(),
    titleHe: z.string().optional(),
    category: z.string(),
    tags: z.array(z.string()).default([]),
    image: z.string().optional(),
    compatible: z.array(z.enum(['gpt', 'gemini', 'midjourney', 'sora', 'veo3', 'leonardo', 'flux'])).default(['gpt', 'gemini']),
    difficulty: z.enum(['beginner', 'intermediate', 'advanced']).default('intermediate'),
    publishedAt: z.coerce.date(),
    featured: z.boolean().default(false),
  }),
});

const categories = defineCollection({
  loader: glob({ pattern: '**/*.json', base: './src/content/categories' }),
});

export const collections = { prompts, categories };
