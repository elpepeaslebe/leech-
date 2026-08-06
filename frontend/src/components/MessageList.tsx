import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Copy, FileCode, ImageIcon, Repeat2, Terminal, UserRound } from "lucide-react";
import type { ChatMessage, ToolCall } from "../types";
import { ImageGeneration } from "./ui/ai-chat-image-generation-1";
import { ShiningText } from "./ui/shining-text";

type MessageListProps = {
  messages: ChatMessage[];
  onContinue?: (content: string) => void;
};

type ImageResult = {
  src: string;
  alt: string;
  text: string;
};

const MARKDOWN_IMAGE = /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/;
const IMAGE_URL =
  /(https?:\/\/[^\s<>()"]+(?:\.(?:png|jpe?g|webp|gif|avif)(?:\?[^\s<>()"]*)?|\/[^\s<>()"]*(?:image|img|generated|output)[^\s<>()"]*)|data:image\/[a-zA-Z+.-]+;base64,[a-zA-Z0-9+/=]+)/i;
const FENCED_CODE = /```(\w+)?\n?([\s\S]*?)(?:```|$)/g;
const CODE_HINT =
  /\b(const|let|var|function|class|import|export|return|async|await|THREE\.|document\.|window\.|<\/?[a-z][\s\S]*?>|#include|def |print\(|console\.log|=>)\b/;

function extractImage(content: string): ImageResult | null {
  const markdown = content.match(MARKDOWN_IMAGE);
  if (markdown?.[2]) {
    return {
      alt: markdown[1] || "Generated image",
      src: markdown[2],
      text: content.replace(markdown[0], "").trim()
    };
  }

  const directUrl = content.match(IMAGE_URL);
  if (directUrl?.[0]) {
    return {
      alt: "Generated image",
      src: directUrl[0],
      text: content.replace(directUrl[0], "").trim()
    };
  }

  return null;
}

function isCodeLike(content: string) {
  const lines = content.split("\n").filter((line) => line.trim());
  if (content.includes("```")) return true;
  if (lines.length < 4) return CODE_HINT.test(content);

  const codeLines = lines.filter((line) =>
    /(;|{|}|\)|\]|\/\/|const |let |var |function |class |=>|THREE\.|document\.|window\.|<\/?[a-z])/i.test(line)
  ).length;
  return codeLines / lines.length > 0.34 || CODE_HINT.test(content);
}

function splitContent(content: string) {
  const parts: Array<{ type: "text"; value: string } | { type: "code"; value: string; language: string }> = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  FENCED_CODE.lastIndex = 0;

  while ((match = FENCED_CODE.exec(content))) {
    if (match.index > cursor) {
      parts.push({ type: "text", value: content.slice(cursor, match.index) });
    }
    parts.push({ type: "code", language: match[1] || "code", value: match[2].trimEnd() });
    cursor = FENCED_CODE.lastIndex;
  }

  if (cursor < content.length) {
    parts.push({ type: "text", value: content.slice(cursor) });
  }

  if (!parts.length && content) {
    return isCodeLike(content)
      ? [{ type: "code" as const, language: "code", value: content.trimEnd() }]
      : [{ type: "text" as const, value: content }];
  }

  if (parts.length === 1 && parts[0].type === "text" && isCodeLike(content)) {
    return [{ type: "code" as const, language: "code", value: content.trimEnd() }];
  }

  return parts.filter((part) => part.value.trim());
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="code-block">
      <div className="code-toolbar">
        <span>{language}</span>
        <button className="code-copy-button" type="button" onClick={copyCode}>
          <Copy size={13} />
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

function ToolCallBlock({ tool }: { tool: ToolCall }) {
  const [expanded, setExpanded] = useState(true);
  const argsStr = Object.keys(tool.args).length
    ? JSON.stringify(tool.args, null, 2)
    : "(no arguments)";

  return (
    <div className="tool-call-block">
      <button
        className="tool-call-header"
        type="button"
        onClick={() => setExpanded(!expanded)}
      >
        <Terminal size={13} />
        <span className="tool-call-name">{tool.name}</span>
        <span className="tool-call-chevron">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>
      {expanded && (
        <div className="tool-call-body">
          <div className="tool-call-section">
            <span className="tool-call-label">arguments</span>
            <pre className="tool-call-code">
              <code>{argsStr}</code>
            </pre>
          </div>
          {tool.result && (
            <div className="tool-call-section">
              <span className="tool-call-label">result</span>
              <pre className="tool-call-code">
                <code>{tool.result.slice(0, 2000)}{tool.result.length > 2000 ? "\n... (truncated)" : ""}</code>
              </pre>
            </div>
          )}
          {!tool.result && (
            <div className="tool-call-section tool-call-pending">
              <ShiningText text="executing..." className="font-medium" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RichText({ content }: { content: string }) {
  const parts = splitContent(content);
  return (
    <>
      {parts.map((part, index) =>
        part.type === "code" ? (
          <CodeBlock code={part.value} language={part.language} key={`code-${index}`} />
        ) : (
          <span key={`text-${index}`}>{part.value}</span>
        )
      )}
    </>
  );
}

function GeneratedImage({ image }: { image: ImageResult }) {
  return (
    <div className="generated-image-result">
      {image.text && <p className="generated-image-caption">{image.text}</p>}
      <ImageGeneration>
        <img className="generated-image" src={image.src} alt={image.alt} loading="lazy" />
      </ImageGeneration>
    </div>
  );
}

function ImagePending() {
  return (
    <ImageGeneration>
      <div className="generated-image-placeholder" aria-hidden="true">
        <ImageIcon size={34} />
      </div>
    </ImageGeneration>
  );
}

function MessageContent({ message }: { message: ChatMessage }) {
  if (message.pending && !message.content && (!message.toolCalls || message.toolCalls.length === 0)) {
    return message.variant === "image" ? (
      <ImagePending />
    ) : (
      <ShiningText text="WMan is thinking..." className="font-medium" />
    );
  }

  if (message.imageUrl) {
    return (
      <GeneratedImage
        image={{
          alt: message.imageAlt || "Generated image",
          src: message.imageUrl,
          text: message.content
        }}
      />
    );
  }

  const image = message.role === "assistant" && !message.error ? extractImage(message.content) : null;
  if (image) return <GeneratedImage image={image} />;

  return (
    <>
      {message.toolCalls && message.toolCalls.length > 0 && (
        <div className="tool-calls-container">
          {message.toolCalls.map((tool, index) => (
            <ToolCallBlock key={`tool-${index}`} tool={tool} />
          ))}
        </div>
      )}
      {message.content && <RichText content={message.content} />}
    </>
  );
}

export function MessageList({ messages, onContinue }: MessageListProps) {
  const listRef = useRef<HTMLElement | null>(null);
  const followKey = useMemo(
    () =>
      messages
        .map((message) => `${message.id}:${message.content.length}:${message.pending ? "1" : "0"}:${message.imageUrl ?? ""}`)
        .join("|"),
    [messages]
  );

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [followKey]);

  if (!messages.length) {
    return (
      <section className="empty-state" aria-label="Empty chat" ref={listRef}>
        <div className="empty-grid">
          <span />
          <span />
          <span />
          <span />
        </div>
        <p className="eyebrow">ready</p>
        <h2>Start with the work, not the noise.</h2>
        <p>
          A calmer command surface for model switching, status, and long-form responses.
        </p>
      </section>
    );
  }

  return (
    <section className="message-list" aria-live="polite" ref={listRef}>
      {messages.map((message) => (
        <article
          className={[
            "message-row",
            message.role === "user" ? "from-user" : "from-assistant",
            message.error ? "is-error" : "",
            message.pending ? "is-pending" : ""
          ].join(" ")}
          key={message.id}
        >
          <div className="avatar" aria-hidden="true">
            {message.role === "user" ? <UserRound size={16} /> : <Bot size={16} />}
          </div>
          <div className="message-card">
            <div className="message-meta">
              <span>{message.role === "user" ? "You" : "WMan"}</span>
              {message.pending && <span>thinking</span>}
            </div>
            <div className="message-body">
              <MessageContent message={message} />
            </div>
            {message.role === "assistant" && message.content && !message.error && (
              <div className="message-actions">
                {isCodeLike(message.content) && onContinue && (
                  <button className="copy-button" type="button" onClick={() => onContinue(message.content)}>
                    <Repeat2 size={13} />
                    Continue
                  </button>
                )}
                <button
                  className="copy-button"
                  type="button"
                  onClick={() => navigator.clipboard.writeText(message.content)}
                >
                  <Copy size={13} />
                  Copy
                </button>
              </div>
            )}
          </div>
        </article>
      ))}
    </section>
  );
}
