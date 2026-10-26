/* Talking to the server. Errors become short messages: an opaque id the server logged, or a
   status line, never a stack trace (the server never sends one). */

export async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = body.error_id ? ` (error id ${body.error_id})` : typeof body.detail === "string" ? `: ${body.detail}` : "";
    } catch (_) { /* no JSON body */ }
    throw new Error(`Request failed (${response.status})${detail}`);
  }
  return response.json();
}

export const post = (path, body) =>
  api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
