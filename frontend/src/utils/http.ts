export async function checkedJson<T = any>(response: Response, operation: string): Promise<T> {
  const text = await response.text();
  let body: any = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      if (response.ok) throw new Error(`${operation} returned invalid JSON (${response.status})`);
    }
  }
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : body?.error || "";
    throw new Error(`${operation} failed (${response.status})${detail ? `: ${detail}` : ""}`);
  }
  if (body === null) throw new Error(`${operation} returned an empty response (${response.status})`);
  return body as T;
}
