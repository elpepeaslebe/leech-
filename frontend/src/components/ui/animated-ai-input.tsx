"use client";

import { ArrowRight, Bot, Check, ChevronDown, Paperclip } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { ModelOption } from "@/types";

interface UseAutoResizeTextareaProps {
  minHeight: number;
  maxHeight?: number;
}

function useAutoResizeTextarea({ minHeight, maxHeight }: UseAutoResizeTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = useCallback(
    (reset?: boolean) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      if (reset) {
        textarea.style.height = `${minHeight}px`;
        return;
      }

      textarea.style.height = `${minHeight}px`;
      const newHeight = Math.max(minHeight, Math.min(textarea.scrollHeight, maxHeight ?? Number.POSITIVE_INFINITY));
      textarea.style.height = `${newHeight}px`;
    },
    [minHeight, maxHeight]
  );

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) textarea.style.height = `${minHeight}px`;
  }, [minHeight]);

  useEffect(() => {
    const handleResize = () => adjustHeight();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [adjustHeight]);

  return { textareaRef, adjustHeight };
}

type AnimatedAIInputProps = {
  models: ModelOption[];
  selectedModel: string;
  disabled?: boolean;
  onModelChange: (model: string) => void;
  onSend: (message: string) => void;
};

function selectedLabel(models: ModelOption[], selectedModel: string) {
  return models.find((model) => model.slug === selectedModel)?.label ?? selectedModel;
}

export function AnimatedAIInput({
  models,
  selectedModel,
  disabled = false,
  onModelChange,
  onSend
}: AnimatedAIInputProps) {
  const [value, setValue] = useState("");
  const { textareaRef, adjustHeight } = useAutoResizeTextarea({ minHeight: 72, maxHeight: 300 });
  const activeLabel = selectedLabel(models, selectedModel);
  const modelOptions = models.length ? models : [{ slug: "default", label: "Default" }];

  function submit() {
    const message = value.trim();
    if (!message || disabled) return;
    onSend(message);
    setValue("");
    adjustHeight(true);
  }

  return (
    <div className="ai-prompt-shell">
      <div className="ai-prompt-frame">
        <div className="relative flex flex-col">
          <div className="max-h-[400px] overflow-y-auto">
            <Textarea
              id="nyx-ai-input"
              ref={textareaRef}
              value={value}
              placeholder="What should we do next?"
              disabled={disabled}
              className={cn(
                "min-h-[72px] w-full resize-none rounded-[22px] rounded-b-none border-none bg-transparent px-4 py-3 text-base text-foreground placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
              )}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && value.trim()) {
                  event.preventDefault();
                  submit();
                }
              }}
              onChange={(event) => {
                setValue(event.target.value);
                adjustHeight();
              }}
            />
          </div>

          <div className="ai-prompt-toolbar">
            <div className="flex min-w-0 items-center gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    className="h-8 max-w-[min(56vw,18rem)] gap-1 rounded-full border border-white/10 pl-2 pr-3 text-xs text-foreground hover:bg-white/10 focus-visible:ring-1 focus-visible:ring-offset-0"
                  >
                    <AnimatePresence mode="wait">
                      <motion.div
                        key={selectedModel}
                        initial={{ opacity: 0, y: -5 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 5 }}
                        transition={{ duration: 0.15 }}
                        className="flex min-w-0 items-center gap-1"
                      >
                        <Bot className="h-4 w-4 shrink-0 opacity-70" />
                        <span className="truncate">{activeLabel}</span>
                        <ChevronDown className="h-3 w-3 shrink-0 opacity-50" />
                      </motion.div>
                    </AnimatePresence>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="max-h-[320px] min-w-[14rem] overflow-y-auto border-border bg-popover">
                  {modelOptions.map((model) => (
                    <DropdownMenuItem
                      key={model.slug}
                      onSelect={() => onModelChange(model.slug)}
                      className="flex items-center justify-between gap-2"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <Bot className="h-4 w-4 shrink-0 opacity-50" />
                        <span className="truncate">{model.label}</span>
                      </div>
                      {selectedModel === model.slug && <Check className="h-4 w-4 shrink-0 text-primary" />}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              <div className="mx-0.5 h-4 w-px bg-white/10" />

              <label
                className="rounded-full p-2 text-white/45 transition-colors hover:bg-white/10 hover:text-white"
                aria-label="Attach file"
              >
                <input type="file" className="hidden" />
                <Paperclip className="h-4 w-4" />
              </label>
            </div>

            <button
              type="button"
              className="rounded-full bg-white p-2 text-black transition-colors hover:bg-white/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:bg-white/15 disabled:text-white"
              aria-label="Send message"
              disabled={!value.trim() || disabled}
              onClick={submit}
            >
              <ArrowRight className={cn("h-4 w-4 transition-opacity duration-200", value.trim() ? "opacity-100" : "opacity-30")} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
