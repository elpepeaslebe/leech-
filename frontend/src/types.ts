export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  variant?: "text" | "image";
  imageUrl?: string;
  imageAlt?: string;
  pending?: boolean;
  error?: boolean;
};

export type ModelOption = {
  slug: string;
  label: string;
};

export type ModelsResponse = {
  models: ModelOption[];
  default: string;
};

export type HealthResponse = {
  status?: "ok" | "warning" | "critical" | string;
  reasons?: string[];
  fresh_accounts?: number;
  warm_accounts?: number;
  pool_target?: number;
  send_success_rate?: number | null;
  recent_errors?: Array<{ where: string; error: string }>;
};
