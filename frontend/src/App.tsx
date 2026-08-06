import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, MessageSquare, PanelLeftClose, PanelLeftOpen, Plus, Send, Settings, SquarePen, Trash2 } from "lucide-react";
import { fetchHealth, fetchModels, getBackendUrl, setBackendUrl, streamChat } from "./api";
import type { ChatMessage, HealthResponse, ModelOption } from "./types";
import { MessageList } from "./components/MessageList";
import { ModelPicker } from "./components/ModelPicker";
import { StatusPill } from "./components/StatusPill";
import { AnimatedAIInput } from "./components/ui/animated-ai-input";

const STORAGE_THREADS = "nyx.threads.react";
const STORAGE_ACTIVE_THREAD = "nyx.activeThread.react";
const LEGACY_STORAGE_THREAD = "nyx.thread.react";
const LEGACY_STORAGE_SESSION = "nyx.sessionId";
const STORAGE_MODEL = "nyx.model";
const STORAGE_EFFORT = "nyx.effort";
const SIDEBAR_BREAKPOINT = "(max-width: 860px)";

type ChatThread = {
  id: string;
  sessionId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
};

function makeId(prefix: string) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

function createSessionId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createThread(title = "New chat", messages: ChatMessage[] = []): ChatThread {
  const now = Date.now();
  return {
    id: makeId("thread"),
    sessionId: createSessionId(),
    title,
    createdAt: now,
    updatedAt: now,
    messages
  };
}

function titleFromMessage(message: string) {
  const compact = message.trim().replace(/\s+/g, " ");
  return compact.length > 36 ? `${compact.slice(0, 36)}...` : compact || "New chat";
}

function looksLikeImageRequest(message: string) {
  const text = message.toLowerCase();
  const asksForCode =
    /\b(html|css|javascript|typescript|tsx|jsx|react|three\.?js|webgl|canvas|shader|code|app|website|page|component|demo|interactive)\b/.test(
      text
    );
  if (asksForCode) return false;

  return /\b(image|picture|photo|photograph|wallpaper|poster|portrait|illustration|logo|icon|avatar|sticker|artwork)\b/.test(
    text
  );
}

function loadThreads(): ChatThread[] {
  try {
    const saved = localStorage.getItem(STORAGE_THREADS);
    if (saved) {
      const parsed = JSON.parse(saved) as ChatThread[];
      if (Array.isArray(parsed) && parsed.length) return parsed;
    }

    const legacy = localStorage.getItem(LEGACY_STORAGE_THREAD);
    const legacyMessages = legacy ? (JSON.parse(legacy) as ChatMessage[]) : [];
    if (legacyMessages.length) {
      const firstUser = legacyMessages.find((message) => message.role === "user")?.content ?? "Imported chat";
      return [
        {
          ...createThread(titleFromMessage(firstUser), legacyMessages),
          sessionId: localStorage.getItem(LEGACY_STORAGE_SESSION) || createSessionId()
        }
      ];
    }
  } catch {
    return [createThread()];
  }

  return [createThread()];
}

function providerOf(label: string) {
  if (/GPT|OpenAI/i.test(label)) return "OpenAI";
  if (/Claude/i.test(label)) return "Anthropic";
  if (/Gemini/i.test(label)) return "Google";
  if (/DeepSeek/i.test(label)) return "DeepSeek";
  return "More";
}

function initialSidebarOpen() {
  if (typeof window === "undefined") return true;
  return !window.matchMedia(SIDEBAR_BREAKPOINT).matches;
}

export function App() {
  const [threads, setThreads] = useState<ChatThread[]>(loadThreads);
  const [activeThreadId, setActiveThreadId] = useState(() => {
    const saved = localStorage.getItem(STORAGE_ACTIVE_THREAD);
    const loaded = loadThreads();
    return loaded.some((thread) => thread.id === saved) ? saved! : loaded[0].id;
  });
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState(() => localStorage.getItem(STORAGE_MODEL) ?? "default");
  const [effort, setEffort] = useState(() => localStorage.getItem(STORAGE_EFFORT) ?? "medium");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(initialSidebarOpen);
  const [backendUrl, setBackendUrlState] = useState(() => getBackendUrl());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [backendInput, setBackendInput] = useState(() => getBackendUrl());
  const pendingId = useRef<string | null>(null);

  const activeThread = threads.find((thread) => thread.id === activeThreadId) ?? threads[0];
  const messages = activeThread?.messages ?? [];
  const sessionId = activeThread?.sessionId ?? createSessionId();

  useEffect(() => {
    localStorage.setItem(STORAGE_THREADS, JSON.stringify(threads.slice(0, 80)));
  }, [threads]);

  useEffect(() => {
    localStorage.setItem(STORAGE_ACTIVE_THREAD, activeThreadId);
  }, [activeThreadId]);

  useEffect(() => {
    if (threads.length && !threads.some((thread) => thread.id === activeThreadId)) {
      setActiveThreadId(threads[0].id);
    }
  }, [activeThreadId, threads]);

  useEffect(() => {
    localStorage.setItem(STORAGE_MODEL, model);
  }, [model]);

  useEffect(() => {
    localStorage.setItem(STORAGE_EFFORT, effort);
  }, [effort]);

  function saveBackendUrl() {
    const cleaned = backendInput.trim().replace(/\/+$/, "");
    setBackendUrl(cleaned);
    setBackendUrlState(cleaned);
    setSettingsOpen(false);
    window.location.reload();
  }

  useEffect(() => {
    let cancelled = false;
    fetchModels()
      .then((data) => {
        if (cancelled) return;
        setModels(data.models ?? []);
        const saved = localStorage.getItem(STORAGE_MODEL);
        const validSaved = saved && data.models?.some((item) => item.slug === saved);
        setModel(validSaved ? saved : data.default ?? "default");
      })
      .catch(() => {
        if (!cancelled) setModels([{ slug: "default", label: "Default" }]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await fetchHealth();
        if (!cancelled) setHealth(next);
      } catch {
        if (!cancelled) setHealth({ status: "critical", reasons: ["backend unreachable"] });
      }
    };
    poll();
    const timer = window.setInterval(poll, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const groupedModels = useMemo(() => {
    return models.reduce<Record<string, ModelOption[]>>((acc, item) => {
      const provider = providerOf(item.label);
      acc[provider] = [...(acc[provider] ?? []), item];
      return acc;
    }, {});
  }, [models]);

  const activeModel = models.find((item) => item.slug === model);

  function updateActiveThread(updater: (thread: ChatThread) => ChatThread) {
    setThreads((current) =>
      current.map((thread) => (thread.id === activeThreadId ? updater(thread) : thread))
    );
  }

  function startNewThread() {
    const next = createThread();
    pendingId.current = null;
    setThreads((current) => [next, ...current]);
    setActiveThreadId(next.id);
  }

  function deleteThread(threadId: string) {
    setThreads((current) => {
      const remaining = current.filter((thread) => thread.id !== threadId);
      if (remaining.length) {
        if (threadId === activeThreadId) setActiveThreadId(remaining[0].id);
        return remaining;
      }
      const next = createThread();
      setActiveThreadId(next.id);
      return [next];
    });
  }

  async function handleSend(content: string) {
    const trimmed = content.trim();
    if (!trimmed || isSending) return;

    const isImageRequest = looksLikeImageRequest(trimmed);
    const userMessage: ChatMessage = { id: makeId("user"), role: "user", content: trimmed };
    const assistantId = makeId("assistant");
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      variant: isImageRequest ? "image" : "text",
      pending: true
    };
    pendingId.current = assistantId;
    setIsSending(true);
    updateActiveThread((thread) => ({
      ...thread,
      title: thread.messages.length ? thread.title : titleFromMessage(trimmed),
      updatedAt: Date.now(),
      messages: [...thread.messages, userMessage, assistantMessage].slice(-200)
    }));

    try {
      await streamChat({ message: trimmed, model, sessionId, effort }, (event) => {
        updateActiveThread((thread) => ({
          ...thread,
          updatedAt: Date.now(),
          messages: thread.messages.map((message) => {
            if (message.id !== assistantId) return message;
            if (event.type === "token") {
              return { ...message, content: message.content + event.token, pending: false };
            }
            if (event.type === "image") {
              return {
                ...message,
                content: message.content || event.image.caption || "",
                imageUrl: event.image.url,
                imageAlt: event.image.alt || "Generated image",
                variant: "image",
                pending: false,
              };
            }
            if (event.type === "tool_call") {
              const existing = message.toolCalls ?? [];
              return {
                ...message,
                toolCalls: [...existing, { name: event.name, args: event.args }],
                pending: false,
              };
            }
            if (event.type === "tool_result") {
              const existing = message.toolCalls ?? [];
              const last = existing[existing.length - 1];
              if (last && last.name === event.name && !last.result) {
                const updated = [...existing.slice(0, -1), { ...last, result: event.result }];
                return { ...message, toolCalls: updated, pending: false };
              }
              return {
                ...message,
                toolCalls: [...existing, { name: event.name, args: {}, result: event.result }],
                pending: false,
              };
            }
            return message;
          })
        }));
      });
      updateActiveThread((thread) => ({
        ...thread,
        updatedAt: Date.now(),
        messages: thread.messages.map((message) =>
          message.id === assistantId ? { ...message, content: message.content || "(no response)", pending: false } : message
        )
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      updateActiveThread((thread) => ({
        ...thread,
        updatedAt: Date.now(),
        messages: thread.messages.map((item) =>
          item.id === assistantId ? { ...item, content: `error: ${message}`, pending: false, error: true } : item
        )
      }));
    } finally {
      pendingId.current = null;
      setIsSending(false);
    }
  }

  function handleContinue(previousContent: string) {
    const tail = previousContent.trim().split("\n").slice(-18).join("\n");
    void handleSend(
      [
        "Continue exactly from where you stopped.",
        "Do not restart the answer and do not repeat earlier code.",
        "Resume from this last part:",
        "```",
        tail,
        "```"
      ].join("\n")
    );
  }

  return (
    <div className={sidebarOpen ? "app-shell" : "app-shell is-sidebar-closed"}>
      <button
        className="sidebar-scrim"
        type="button"
        aria-label="Close sidebar"
        onClick={() => setSidebarOpen(false)}
      />
      <aside className="side-panel" aria-label="Workspace status">
        <div className="brand-lockup">
          <div className="brand-mark">
            <MessageSquare size={19} strokeWidth={2.1} />
          </div>
          <div>
            <p className="eyebrow">local chat</p>
            <h1>WMan</h1>
          </div>
        </div>

        <button className="new-chat-button" type="button" onClick={startNewThread}>
          <Plus size={16} />
          New chat
        </button>

        <div className="history-section">
          <p className="section-label">history</p>
          <div className="history-list">
            {threads.map((thread) => (
              <button
                className={thread.id === activeThreadId ? "history-item is-active" : "history-item"}
                key={thread.id}
                type="button"
                onClick={() => setActiveThreadId(thread.id)}
              >
                <span>{thread.title}</span>
                <Trash2
                  size={14}
                  onClick={(event) => {
                    event.stopPropagation();
                    deleteThread(thread.id);
                  }}
                />
              </button>
            ))}
          </div>
        </div>

        <div className="panel-section">
          <p className="section-label">runtime</p>
          <StatusPill health={health} />
          <div className="meter-row">
            <span>session</span>
            <code>{sessionId.slice(0, 8)}</code>
          </div>
          <div className="meter-row">
            <span>thread</span>
            <code>{messages.length} turns</code>
          </div>
        </div>

        <div className="panel-section">
          <p className="section-label">model</p>
          <ModelPicker groups={groupedModels} value={model} onChange={setModel} />
        </div>

        <div className="panel-section">
          <p className="section-label">effort</p>
          <div className="effort-picker">
            {(["low", "medium", "high"] as const).map((level) => (
              <button
                key={level}
                className={`effort-button ${effort === level ? "is-active" : ""}`}
                type="button"
                onClick={() => setEffort(level)}
              >
                {level}
              </button>
            ))}
          </div>
        </div>

        <div className="panel-section">
          <p className="section-label">backend</p>
          <button className="settings-toggle" type="button" onClick={() => setSettingsOpen(!settingsOpen)}>
            <Settings size={14} />
            {backendUrl ? "Connected" : "Not connected"}
          </button>
          {settingsOpen && (
            <div className="settings-panel">
              <input
                className="settings-input"
                type="text"
                placeholder="https://xxx.trycloudflare.com"
                value={backendInput}
                onChange={(e) => setBackendInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveBackendUrl(); }}
              />
              <button className="settings-save" type="button" onClick={saveBackendUrl}>
                Save & Reload
              </button>
              {backendUrl && (
                <p className="settings-current">{backendUrl}</p>
              )}
            </div>
          )}
        </div>

        <div className="panel-actions">
          <button className="utility-button ghost" type="button" onClick={() => setSidebarOpen(false)}>
            <PanelLeftClose size={16} />
            Collapse
          </button>
        </div>
      </aside>

      <main className="workspace">
        <header className="top-rail">
          <button
            className="icon-button"
            type="button"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-label={sidebarOpen ? "Collapse workspace panel" : "Open workspace panel"}
          >
            {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>
          <div className="top-title">
            <p className="eyebrow">{activeModel?.label ?? "Default model"}</p>
            <h2>{activeThread?.title ?? "New chat"}</h2>
          </div>
          <div className="top-meta">
            <span className="live-chip">
              <Activity size={14} />
              {health?.status ?? "checking"}
            </span>
          </div>
        </header>

        <MessageList messages={messages} onContinue={handleContinue} />

        <div className="composer-dock">
          <div className="draft-label">
            <SquarePen size={14} />
            <span>compose</span>
          </div>
          <AnimatedAIInput
            models={models}
            selectedModel={model}
            disabled={isSending}
            onModelChange={setModel}
            onSend={handleSend}
          />
          <p className="send-note">
            <Send size={12} />
            Enter sends. Shift+Enter adds a line.
          </p>
        </div>
      </main>
    </div>
  );
}
