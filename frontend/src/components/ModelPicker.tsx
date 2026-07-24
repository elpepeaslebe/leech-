import { Bot, Check, ChevronDown } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import type { ModelOption } from "../types";

type ModelPickerProps = {
  groups: Record<string, ModelOption[]>;
  value: string;
  onChange: (value: string) => void;
};

const GROUP_ORDER = ["OpenAI", "Anthropic", "Google", "DeepSeek", "More"];

function activeLabel(groups: Record<string, ModelOption[]>, value: string) {
  return Object.values(groups)
    .flat()
    .find((option) => option.slug === value)?.label ?? "Select model";
}

export function ModelPicker({ groups, value, onChange }: ModelPickerProps) {
  return (
    <div className="model-field">
      <span>selected model</span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="model-trigger" type="button">
            <span className="model-trigger-main">
              <Bot size={15} />
              <span>{activeLabel(groups, value)}</span>
            </span>
            <ChevronDown size={15} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="model-menu" sideOffset={8}>
          {GROUP_ORDER.map((group) => {
            const options = groups[group];
            if (!options?.length) return null;
            return (
              <div className="model-group" key={group}>
                <div className="model-group-label">{group}</div>
                {options.map((option) => (
                  <DropdownMenuItem
                    className="model-option"
                    key={option.slug}
                    onSelect={() => onChange(option.slug)}
                  >
                    <span>{option.label}</span>
                    {option.slug === value && <Check size={14} />}
                  </DropdownMenuItem>
                ))}
              </div>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
