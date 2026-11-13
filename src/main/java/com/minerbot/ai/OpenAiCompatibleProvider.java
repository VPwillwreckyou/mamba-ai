package com.minerbot.ai;

import java.util.concurrent.CompletableFuture;

/** OpenAI-compatible /chat/completions endpoint (Bearer auth). */
public final class OpenAiCompatibleProvider implements AIProvider {

    public static final String ID = "openai";

    @Override
    public String id() {
        return ID;
    }

    @Override
    public String displayName() {
        return "OpenAI-compatible";
    }

    @Override
    public String defaultModel() {
        return "gpt-4o-mini";
    }

    @Override
    public String defaultEndpoint() {
        return "https://api.openai.com/v1/chat/completions";
    }

    @Override
    public boolean needsEndpoint() {
        return true;
    }

    @Override
    public CompletableFuture<AiResult> complete(String apiKey, String model, String endpoint,
            String systemPrompt, String userPrompt, int timeoutMs) {
        String m = (model == null || model.isBlank()) ? defaultModel() : model.trim();
        String url = (endpoint == null || endpoint.isBlank()) ? defaultEndpoint() : endpoint.trim();
        String sys = systemPrompt == null ? "" : systemPrompt;
        String usr = userPrompt == null ? "" : userPrompt;
        StringBuilder json = new StringBuilder();
        json.append("{\"model\":\"").append(AIProvider.jsonEscape(m)).append("\",");
        json.append("\"max_tokens\":512,\"temperature\":0.4,\"messages\":[");
        if (!sys.isEmpty()) {
            json.append("{\"role\":\"system\",\"content\":\"").append(AIProvider.jsonEscape(sys)).append("\"},");
        }
        json.append("{\"role\":\"user\",\"content\":\"").append(AIProvider.jsonEscape(usr)).append("\"}]}");
        return AiHttp.postJson(url, apiKey, "Bearer ", json.toString(), timeoutMs, AIProvider::extractOpenAiText);
    }
}
