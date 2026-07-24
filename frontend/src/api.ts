import type { HealthResponse, ModelsResponse } from "./types";

export type ChatStreamEvent =
  | { type: "token"; token: string }
  | { type: "image"; image: { url: string; alt?: string; caption?: string } };

export async function fetchModels(): Promise<ModelsResponse> {
  const response = await fetch("/models");
  if (!response.ok) {
    throw new Error(`models request failed (${response.status})`);
  }
  return response.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch("/health");
  if (!response.ok) {
    throw new Error(`health request failed (${response.status})`);
  }
  return response.json();
}

export async function streamChat(
  payload: { message: string; model: string; sessionId: string },
  onEvent: (event: ChatStreamEvent) => void
): Promise<void> {
  const response = await fetch("/chat", {
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
      const parsed = JSON.parse(line) as Partial<ChatStreamEvent> & { token?: string };
      if (parsed.type === "image" && parsed.image?.url) {
        onEvent({ type: "image", image: parsed.image });
      } else if (parsed.token) {
        onEvent({ type: "token", token: parsed.token });
      }
    }
  }
}
