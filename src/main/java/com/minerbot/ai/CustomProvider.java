package com.minerbot.ai;

import java.util.concurrent.CompletableFuture;

/**
 * Custom endpoint: user supplies any OpenAI-compatible URL. Same wire format
 * as {@link OpenAiCompatibleProvider} but requires an explicit endpoint so we
 * never silently send a key to a default host the user did not choose.
 */
public final class CustomProvider implements AIProvider {

    public static final String ID = "custom";

    @Override
    public String id() {
        return ID;
    }

    @Override
    public String displayName() {
        return "Custom";
    }

    @Override
    public String defaultModel() {
        return "custom-model";
    }

    @Override
    public String defaultEndpoint() {
        return "http://localhost:11434/v1/chat/completions";
    }

    @Override
    public boolean needsEndpoint() {
        return true;
    }

    @Override
    public CompletableFuture<AiResult> complete(String apiKey, String model, String endpoint,
            String systemPrompt, String userPrompt, int timeoutMs) {
        if (endpoint == null || endpoint.isBlank()) {
            return CompletableFuture.completedFuture(AiResult.failure("custom endpoint is empty - set Endpoint first"));
        }
        String m = (model == null || model.isBlank()) ? defaultModel() : model.trim();
        String sys = systemPrompt == null ? "" : systemPrompt;
        String usr = userPrompt == null ? "" : userPrompt;
        StringBuilder json = new StringBuilder();
        json.append("{\"model\":\"").append(AIProvider.jsonEscape(m)).append("\",");
        json.append("\"max_tokens\":512,\"temperature\":0.4,\"messages\":[");
        if (!sys.isEmpty()) {
            json.append("{\"role\":\"system\",\"content\":\"").append(AIProvider.jsonEscape(sys)).append("\"},");
        }
        json.append("{\"role\":\"user\",\"content\":\"").append(AIProvider.jsonEscape(usr)).append("\"}]}");
        String key = apiKey == null ? "" : apiKey;
        // Some local servers need no key; send without Authorization then.
        if (key.isBlank()) {
            return AiHttp.postJson(endpoint.trim(), "x", "", json.toString(), timeoutMs, AIProvider::extractOpenAiText);
        }
        return AiHttp.postJson(endpoint.trim(), key, "Bearer ", json.toString(), timeoutMs, AIProvider::extractOpenAiText);
    }

    @Override
    public CompletableFuture<AiResult> testConnection(String apiKey, String model, String endpoint, int timeoutMs) {
        if (endpoint == null || endpoint.isBlank()) {
            return CompletableFuture.completedFuture(AiResult.failure("custom endpoint is empty - set Endpoint first"));
        }
        return complete(apiKey, model, endpoint, "Reply with exactly: ok", "ping", timeoutMs);
    }
}
