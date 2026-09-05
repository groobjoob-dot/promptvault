// Cloudflare Pages Function: /cdn/*
// Serves images from R2 with optional transformation params

interface Env {
  PROMPTS: R2Bucket;
}

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);
  const key = url.pathname.replace(/^\/cdn\//, '');

  if (!key) {
    return new Response('Not found', { status: 404 });
  }

  // Get the object from R2
  const object = await context.env.PROMPTS.get(key);
  if (!object) {
    return new Response('Not found', { status: 404 });
  }

  // Build response with proper headers
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set('etag', object.httpEtag);
  headers.set('cache-control', 'public, max-age=31536000, immutable');

  return new Response(object.body, { headers });
};
