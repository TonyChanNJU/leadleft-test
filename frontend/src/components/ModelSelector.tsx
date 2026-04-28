import React from "react";
import { Settings } from "lucide-react";
import type { AppModel } from "../lib/api";

interface ModelSelectorProps {
  currentModel: string;
  onModelChange: (model: string) => void;
  availableModels: AppModel[];
  disabled?: boolean;
}

export const ModelSelector: React.FC<ModelSelectorProps> = ({ 
  currentModel, 
  onModelChange,
  availableModels,
  disabled = false
}) => {
  // Group models by provider
  const groupedModels = availableModels.reduce((acc, curr) => {
    if (!acc[curr.provider]) acc[curr.provider] = [];
    acc[curr.provider].push(curr);
    return acc;
  }, {} as Record<string, AppModel[]>);

  const providerNames: Record<string, string> = {
    openai: "OpenAI",
    anthropic: "Anthropic",
    google: "Google",
    deepseek: "DeepSeek"
  };

  return (
    <div className="flex items-center space-x-2 text-[10px] text-slate-600 dark:text-slate-300 bg-white/80 dark:bg-slate-950/30 backdrop-blur-md px-3 py-1.5 rounded-xl border border-slate-100/50 dark:border-slate-800/60 shadow-sm hover:shadow-md transition-shadow uppercase tracking-widest font-semibold">
      <Settings className="w-3.5 h-3.5 text-slate-500 dark:text-slate-300" />
      <span>Model</span>
      <select 
        value={currentModel}
        onChange={(e) => onModelChange(e.target.value)}
        disabled={disabled || availableModels.length === 0}
        className="bg-transparent border-none focus:ring-0 cursor-pointer font-semibold text-slate-900 dark:text-slate-100 outline-none uppercase tracking-widest text-[10px]"
      >
        {Object.entries(groupedModels).map(([provider, models]) => (
          <optgroup key={provider} label={providerNames[provider] || provider.toUpperCase()}>
            {models.map((m) => (
              <option key={m.model_id} value={m.model_id}>{m.display}</option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
};
