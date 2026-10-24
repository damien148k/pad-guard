// Calls to the local server (127.0.0.1). The session token comes from the page itself.
const token = document.querySelector('meta[name="pad-guard-token"]').content;

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { 'X-PAD-Guard': token, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) throw new Error((data && data.error) || `erreur ${res.status}`);
  return data;
}

// Links, images and the event stream cannot send headers: the token goes in the query string.
export function url(path) {
  return path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(token);
}
