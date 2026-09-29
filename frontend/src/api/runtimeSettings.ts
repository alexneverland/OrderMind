import { request } from "./client";

export type AISettings = {
  provider: "mock" | "gemini" | "openai" | "anthropic" | "vertex";
  model: string;
  gemini_key_configured: boolean;
  openai_key_configured: boolean;
  anthropic_key_configured: boolean;
  google_cloud_project: string | null;
  google_cloud_location: string | null;
};

export const getAISettings = () => request<AISettings>("/runtime-settings/ai");

export const saveAISettings = (payload: {
  provider: AISettings["provider"];
  model: string;
  gemini_api_key?: string;
  openai_api_key?: string;
  anthropic_api_key?: string;
  google_cloud_project?: string;
  google_cloud_location?: string;
}) =>
  request<AISettings>("/runtime-settings/ai", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
