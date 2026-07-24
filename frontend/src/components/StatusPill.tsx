import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import type { HealthResponse } from "../types";

type StatusPillProps = {
  health: HealthResponse | null;
};

function statusTone(status?: string) {
  if (status === "ok") return "ok";
  if (status === "warning") return "warning";
  return "critical";
}

function statusLabel(status?: string) {
  if (status === "ok") return "Ready";
  if (status === "warning") return "Degraded";
  if (status === "critical") return "Runner unstable";
  return "Checking";
}

function cleanDetail(detail: string) {
  return detail
    .replace(/message success low/i, "message success is low")
    .replace(/use\.ai signup or WS protocol may have changed/i, "model runner may need attention");
}

export function StatusPill({ health }: StatusPillProps) {
  const tone = statusTone(health?.status);
  const Icon = tone === "ok" ? CheckCircle2 : tone === "warning" ? CircleDashed : AlertTriangle;
  const detail = cleanDetail(health?.reasons?.join(" | ") ?? "checking backend");

  return (
    <div className={`status-pill ${tone}`}>
      <Icon size={17} />
      <div>
        <strong>{statusLabel(health?.status)}</strong>
        <span>{detail}</span>
      </div>
    </div>
  );
}
