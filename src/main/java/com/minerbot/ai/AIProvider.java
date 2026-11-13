package com.minerbot.ai;

import java.util.concurrent.CompletableFuture;

/**
 * Clean provider interface. All bot code talks to AI through this;
 * provider-specific HTTP stays inside implementations.
 */
public interface AIProvider {

    /** Stable id used in config, e.g. "gemini", "openai", "custom". */
    String id();

    /** Human-readable label for the GUI. */
    String displayName();

    /** Default model shown when the model field is empty. */
    String defaultModel();

    /** Default endpoint (may be empty when not needed). */
    String defaultEndpoint();

    /** Whether this provider needs a custom endpoint field. */
    default boolean needsEndpoint() {
        return false;
    }

    /**
     * Async completion. Must never block the caller; implementations run
     * HTTP on {@link AiExecutor} pool threads.
     */
    CompletableFuture<AiResult> complete(String apiKey, String model, String endpoint,
            String systemPrompt, String userPrompt, int timeoutMs);

    /**
     * Lightweight connection check: sends a minimal prompt ("ping") and
     * reports ok/failure without throwing.
     */
    default CompletableFuture<AiResult> testConnection(String apiKey, String model,
            String endpoint, int timeoutMs) {
        return complete(apiKey, model, endpoint,
                "Reply with exactly the word: ok", "ping", timeoutMs);
    }

    /** Parse provider-specific error bodies into a short human message. */
    static String shortError(String raw, int maxLen) {
        if (raw == null || raw.isEmpty()) return "empty response";
        // Strip obvious HTML to keep GUI readable.
        String s = raw.replaceAll("<[^>]*>", " ").replaceAll("\\s+", " ").trim();
        if (s.length() > maxLen) s = s.substring(0, maxLen) + "...";
        return s;
    }

    /** Extract plain text from common OpenAI-compatible JSON shapes. */
    static String extractOpenAiText(String json) {
        // choices[0].message.content
        String marker = "\"content\"";
        int i = json.indexOf(marker);
        while (i >= 0) {
            int colon = json.indexOf(':', i + marker.length());
            if (colon < 0) break;
            int q1 = json.indexOf('"', colon + 1);
            if (q1 < 0) break;
            StringBuilder sb = new StringBuilder();
            boolean esc = false;
            for (int k = q1 + 1; k < json.length(); k++) {
                char c = json.charAt(k);
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
                    return unescapeUnicode(sb.toString());
                } else {
                    sb.append(c);
                }
            }
            i = json.indexOf(marker, i + 1);
        }
        return "";
    }

    static String unescapeUnicode(String s) {
        if (!s.contains("\\u") && !s.contains("\\U")) return s;
        StringBuilder out = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\\' && i + 5 < s.length() && (s.charAt(i + 1) == 'u' || s.charAt(i + 1) == 'U')) {
                try {
                    out.append((char) Integer.parseInt(s.substring(i + 2, i + 6), 16));
                    i += 5;
                    continue;
                } catch (NumberFormatException ignored) {
                }
            }
            out.append(c);
        }
        return out.toString();
    }

    /** Minimal JSON string escaper (no external deps). */
    static String jsonEscape(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder(s.length() + 16);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
                }
            }
        }
        return sb.toString();
    }
}
