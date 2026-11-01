import type { NodeReadiness, OrganizationOnboardingStatus } from "../types/rights";

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

function sessionHeaders(sessionId: string): HeadersInit {
  return { "X-Session-Id": sessionId };
}

export async function getNodeReadiness(apiBase: string, sessionId: string): Promise<NodeReadiness> {
  const response = await fetch(`${apiBase}/v1/node/readiness`, {
    headers: sessionHeaders(sessionId),
  });
  return checkedJson<NodeReadiness>(response, "Load node readiness");
}

export async function getOrganizationOnboardingStatus(
  apiBase: string,
  sessionId: string,
  organizationId: string,
): Promise<OrganizationOnboardingStatus> {
  const response = await fetch(
    `${apiBase}/v1/organizations/${encodeURIComponent(organizationId)}/onboarding-status`,
    { headers: sessionHeaders(sessionId) },
  );
  return checkedJson<OrganizationOnboardingStatus>(response, "Load organization onboarding");
}
