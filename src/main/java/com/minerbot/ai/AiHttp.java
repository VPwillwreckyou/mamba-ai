package com.minerbot.ai;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/** Shared HTTP helper: timeouts mapped to friendly errors, no key logging. */
final class AiHttp {
    private static volatile HttpClient client;

    private AiHttp() {
    }

    static HttpClient client(int timeoutMs) {
        HttpClient c = client;
        if (c == null) {
            synchronized (AiHttp.class) {
                c = client;
                if (c == null) {
                    c = HttpClient.newBuilder()
                            .connectTimeout(Duration.ofMillis(Math.max(1000, timeoutMs)))
                            .followRedirects(HttpClient.Redirect.NEVER)
                            .build();
                    client = c;
                }
            }
        }
        return c;
    }

    static CompletableFuture<AiResult> postJson(String url, String apiKey, String bearerPrefix,
            String jsonBody, int timeoutMs, java.util.function.Function<String, String> textExtractor) {
        return postJson(url, apiKey, bearerPrefix, null, jsonBody, timeoutMs, textExtractor);
    }

    static CompletableFuture<AiResult> postJson(String url, String apiKey, String bearerPrefix,
            Map<String, String> extraHeaders,
            String jsonBody, int timeoutMs, java.util.function.Function<String, String> textExtractor) {
        String headerKey = extraHeaders != null ? extraHeaders.get("x-goog-api-key") : null;
        boolean hasKey = (apiKey != null && !apiKey.isBlank()) || (headerKey != null && !headerKey.isBlank());
        if (url == null || url.isBlank()) return CompletableFuture.completedFuture(AiResult.failure("endpoint is empty"));
        if (!hasKey) return CompletableFuture.completedFuture(AiResult.failure("API key is not set"));
        String body = jsonBody == null ? "" : jsonBody;
        HttpRequest.Builder rb = HttpRequest.newBuilder()
                .uri(URI.create(url.trim()))
                .timeout(Duration.ofMillis(Math.max(1000, timeoutMs)))
                .header("Content-Type", "application/json; charset=utf-8")
                .header("Accept", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
        if (bearerPrefix != null && !bearerPrefix.isEmpty()) {
            rb.header("Authorization", bearerPrefix + apiKey);
        }
        if (extraHeaders != null) {
            for (Map.Entry<String, String> e : extraHeaders.entrySet()) {
                if (e.getKey() == null || e.getValue() == null) continue;
                // Never put the raw key into any header name; value only.
                rb.header(e.getKey(), e.getValue());
            }
        }
        HttpRequest req;
        try {
            req = rb.build();
        } catch (IllegalArgumentException e) {
            return CompletableFuture.completedFuture(AiResult.failure("bad endpoint URL: " + e.getMessage()));
        }
        return CompletableFuture.supplyAsync(() -> {
            try {
                HttpResponse<String> resp = client(timeoutMs).send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
                int code = resp.statusCode();
                String respBody = resp.body() == null ? "" : resp.body();
                if (code == 401 || code == 403) {
                    return AiResult.failure("invalid API key (HTTP " + code + ")");
                }
                if (code == 429) {
                    return AiResult.failure("rate limited (HTTP 429) - wait and retry");
                }
                if (code == 404) {
                    return AiResult.failure("not found (HTTP 404): check model/endpoint. " + AIProvider.shortError(respBody, 160));
                }
                if (code < 200 || code >= 300) {
                    return AiResult.failure("HTTP " + code + ": " + AIProvider.shortError(respBody, 220));
                }
                String text = "";
                try {
                    text = textExtractor.apply(respBody);
                } catch (Exception e) {
                    return AiResult.failure("malformed response: " + e.getMessage());
                }
                if (text == null || text.isBlank()) {
                    return AiResult.failure("empty model reply. " + AIProvider.shortError(respBody, 160));
                }
                return AiResult.success(text.trim());
            } catch (java.net.http.HttpTimeoutException e) {
                return AiResult.failure("request timed out after " + timeoutMs + "ms");
            } catch (java.net.ConnectException | java.net.UnknownHostException e) {
                return AiResult.failure("network unreachable: " + e.getMessage());
            } catch (IllegalArgumentException e) {
                return AiResult.failure("bad endpoint URL: " + e.getMessage());
            } catch (Exception e) {
                String m = e.getMessage();
                return AiResult.failure("request failed: " + (m == null || m.isEmpty() ? e.getClass().getSimpleName() : m));
            }
        }, AiExecutor.pool());
    }
}
