export async function api(path, options = {}) {
  const res = await fetch(`/api/${path}`, options);
  if (!res.ok) {
    const body = await res.text();
    let detail;
    try { detail = JSON.parse(body).detail; } catch { /* Proxy errors may be HTML. */ }
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status}).`);
  }
  return res.json();
}

export function post(path, body) {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}
