import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import { Loader2, SendHorizontal } from "lucide-react";

type ComposerProps = {
  disabled: boolean;
  onSend: (message: string) => void;
};

export function Composer({ disabled, onSend }: ComposerProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const message = value.trim();
    if (!message || disabled) return;
    onSend(message);
    setValue("");
    requestAnimationFrame(() => {
      if (inputRef.current) inputRef.current.style.height = "auto";
    });
  }

  function autoGrow(next: string) {
    setValue(next);
    requestAnimationFrame(() => {
      const node = inputRef.current;
      if (!node) return;
      node.style.height = "auto";
      node.style.height = `${Math.min(node.scrollHeight, 220)}px`;
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        ref={inputRef}
        value={value}
        onChange={(event) => autoGrow(event.target.value)}
        onKeyDown={onKeyDown}
        rows={1}
        placeholder="Ask for the next move..."
        disabled={disabled}
        aria-label="Message"
      />
      <button className="send-button" type="submit" disabled={disabled || !value.trim()}>
        {disabled ? <Loader2 className="spin" size={18} /> : <SendHorizontal size={18} />}
      </button>
    </form>
  );
}
