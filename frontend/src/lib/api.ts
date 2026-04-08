const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("openpa_token");
}

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...options.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// --- Auth ---

export async function signup(email: string, password: string, displayName: string = "") {
  return request<{ user: { id: number; email: string }; token: string }>(
    "/api/auth/signup",
    { method: "POST", body: JSON.stringify({ email, password, display_name: displayName }) }
  );
}

export async function login(email: string, password: string) {
  return request<{ user: { id: number; email: string }; token: string }>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) }
  );
}

export async function getMe() {
  return request<{ user: { id: number; email: string; display_name: string }; connected_services: { services: { service: string; updated_at: string }[] } }>(
    "/api/me"
  );
}

// --- Config ---

export async function saveServiceConfig(service: string, credentials: Record<string, string>) {
  return request<{ status: string }>(`/api/config/${service}`, {
    method: "PUT",
    body: JSON.stringify({ credentials }),
  });
}

export async function listConfig() {
  return request<{ services: { service: string; updated_at: string }[] }>("/api/config");
}

// --- Conversations ---

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export async function listConversations() {
  return request<{ conversations: Conversation[] }>("/api/conversations");
}

export async function getConversation(id: number) {
  return request<{ messages: { role: string; content: string; created_at: string }[] }>(
    `/api/conversations/${id}`
  );
}

export async function deleteConversation(id: number) {
  return request<{ status: string }>(`/api/conversations/${id}`, { method: "DELETE" });
}

// --- LLM Providers ---

export interface LLMProviderInfo {
  label: string;
  description: string;
  models: string[];
  needs_api_key: boolean;
  key_field?: string;
  get_key_url?: string;
}

export async function getLLMProviders() {
  return request<{ providers: Record<string, LLMProviderInfo> }>("/api/llm/providers");
}

export async function getLLMConfig() {
  return request<{ default_provider: string; default_model: string; configured_providers: string[] }>(
    "/api/llm/config"
  );
}

export async function saveLLMConfig(config: Record<string, string>) {
  return request<{ status: string }>("/api/llm/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

// --- Chat ---

export async function chat(message: string, provider: string = "", model: string = "") {
  return request<{ response: string }>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, provider, model }),
  });
}

export interface SSEEvent {
  type: "thinking" | "thinking_text" | "planning" | "step" | "tool_call" | "tool_result" | "compacted" | "done" | "error";
  data: Record<string, unknown>;
}

export async function chatStream(
  message: string,
  onEvent: (event: SSEEvent) => void,
  provider: string = "",
  model: string = "",
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({ message, provider, model }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Stream failed");
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7);
      } else if (line.startsWith("data: ") && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent({ type: currentEvent as SSEEvent["type"], data });
        } catch {
          // skip malformed JSON
        }
        currentEvent = "";
      }
    }
  }
}

// --- Tools ---

export async function listTools() {
  return request<{ tools: { name: string; description: string; parameters: unknown }[] }>(
    "/api/tools"
  );
}
