package com.minerbot.ai;

import java.util.concurrent.CompletableFuture;

/** Google Gemini via generateContent REST endpoint (API key in header). */
public final class GeminiProvider implements AIProvider {

    public static final String ID = "gemini";

    @Override
    public String id() {
        return ID;
    }

    @Override
    public String displayName() {
        return "Gemini";
    }

    @Override
    public String defaultModel() {
        return "gemini-2.0-flash";
    }

    @Override
    public String defaultEndpoint() {
        return "";
    }

    @Override
    public CompletableFuture<AiResult> complete(String apiKey, String model, String endpoint,
            String systemPrompt, String userPrompt, int timeoutMs) {
        String m = (model == null || model.isBlank()) ? defaultModel() : model.trim();
        String safeModel = m.replaceAll("[^A-Za-z0-9._-]", "");
        if (safeModel.isEmpty()) safeModel = defaultModel();
        String url = (endpoint == null || endpoint.isBlank())
                ? "https://generativelanguage.googleapis.com/v1beta/models/" + safeModel + ":generateContent"
                : endpoint.trim();
        String sys = systemPrompt == null ? "" : systemPrompt;
        String usr = userPrompt == null ? "" : userPrompt;
        String json = "{\"contents\":[{\"role\":\"user\",\"parts\":[{\"text\":\""
                + AIProvider.jsonEscape((sys.isEmpty() ? "" : sys + "\n\n") + usr)
                + "\"}]}],\"generationConfig\":{\"maxOutputTokens\":512,\"temperature\":0.4}}";
        // Gemini authenticates via the x-goog-api-key header.
        return AiHttp.postJson(url, "x", "",
                java.util.Map.of("x-goog-api-key", apiKey == null ? "" : apiKey),
                json, timeoutMs, GeminiProvider::extractText);
    }

    /** Gemini generateContent JSON -> first candidates[0].content.parts[*].text. */
    static String extractText(String json) {
        if (json == null || json.isEmpty()) return "";
        // Reuse the generic content extractor over all "text" fields after "candidates".
        int cand = json.indexOf("\"candidates\"");
        String slice = cand >= 0 ? json.substring(cand) : json;
        StringBuilder out = new StringBuilder();
        String marker = "\"text\"";
        int i = slice.indexOf(marker);
        while (i >= 0) {
            int colon = slice.indexOf(':', i + marker.length());
            if (colon < 0) break;
            int q1 = slice.indexOf('"', colon + 1);
            if (q1 < 0) break;
            StringBuilder sb = new StringBuilder();
            boolean esc = false;
            boolean closed = false;
            for (int k = q1 + 1; k < slice.length(); k++) {
                char c = slice.charAt(k);
                if (esc) {
                    switch (c) {
                        case 'n' -> sb.append('\n');
                        case 't' -> sb.append('\t');
                        case 'r' -> sb.append('\r');
                        case '"' -> sb.append('"');
                        case '\\' -> sb.append('\\');
                        default -> sb.append(c);
                    }
                    esc = false;
                } else if (c == '\\') {
                    esc = true;
                } else if (c == '"') {
                    closed = true;
                    break;
                } else {
                    sb.append(c);
                }
            }
            if (closed) {
                if (out.length() > 0) out.append('\n');
                out.append(AIProvider.unescapeUnicode(sb.toString()));
            }
            i = slice.indexOf(marker, i + 1);
            if (out.length() > 4000) break;
        }
        // Fallback to generic OpenAI-style extraction if nothing found.
        if (out.length() == 0) return AIProvider.extractOpenAiText(json);
        return out.toString();
    }

    @Override
    public CompletableFuture<AiResult> testConnection(String apiKey, String model, String endpoint, int timeoutMs) {
        // Custom minimal ping: same path, tiny body.
        return complete(apiKey, model, endpoint, "Reply with exactly: ok", "ping", timeoutMs);
    }
}
