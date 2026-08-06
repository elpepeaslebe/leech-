import type { HealthResponse, ModelsResponse } from "./types";

const STORAGE_BACKEND_URL = "nyx.backendUrl";

export function getBackendUrl(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(STORAGE_BACKEND_URL) ?? "";
}

export function setBackendUrl(url: string) {
  localStorage.setItem(STORAGE_BACKEND_URL, url.replace(/\/+$/, ""));
}

function apiUrl(path: string): string {
  const base = getBackendUrl();
  return base ? `${base}${path}` : path;
}

export type ChatStreamEvent =
  | { type: "token"; token: string }
  | { type: "image"; image: { url: string; alt?: string; caption?: string } }
  | { type: "tool_call"; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; name: string; result: string };

export async function fetchModels(): Promise<ModelsResponse> {
  const response = await fetch(apiUrl("/models"));
  if (!response.ok) {
    throw new Error(`models request failed (${response.status})`);
  }
  return response.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(apiUrl("/health"));
  if (!response.ok) {
    throw new Error(`health request failed (${response.status})`);
  }
  return response.json();
}

export async function streamChat(
  payload: { message: string; model: string; sessionId: string; effort?: string },
  onEvent: (event: ChatStreamEvent) => void
): Promise<void> {
  const response = await fetch(apiUrl("/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!response.ok || !response.body) {
    throw new Error(`chat request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const line = event.replace(/^data: /, "").trim();
      if (!line || line === "[DONE]") continue;
      const parsed = JSON.parse(line) as Partial<ChatStreamEvent> & { token?: string; name?: string; args?: Record<string, unknown>; result?: string };
      if (parsed.type === "image" && parsed.image?.url) {
        onEvent({ type: "image", image: parsed.image });
      } else if (parsed.type === "tool_call" && parsed.name) {
        onEvent({ type: "tool_call", name: parsed.name, args: parsed.args ?? {} });
      } else if (parsed.type === "tool_result" && parsed.name) {
        onEvent({ type: "tool_result", name: parsed.name, result: parsed.result ?? "" });
      } else if (parsed.token) {
        onEvent({ type: "token", token: parsed.token });
      }
    }
  }
}
