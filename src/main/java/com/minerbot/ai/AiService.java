package com.minerbot.ai;

import com.minerbot.BotManager;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Facade the bot/GUI talks to. Holds provider registry, rate limiting,
 * response cache, and the safe AIAction layer.
 */
public final class AiService {
    private static final List<AIProvider> PROVIDERS = List.of(
            new GeminiProvider(), new OpenAiCompatibleProvider(), new CustomProvider());

    private static final long MIN_INTERVAL_MS = 3000;
    private static final long CACHE_TTL_MS = 60_000;
    private static final int MAX_PROMPT = 2000;

    private final AtomicLong lastCall = new AtomicLong(0);
    private String lastPrompt = "";
    private String lastReply = "";
    private long lastReplyAt = 0;

    private final List<String> history = new ArrayList<>();

    public static List<AIProvider> providers() {
        return PROVIDERS;
    }

    public static AIProvider byId(String id) {
        if (id == null) return PROVIDERS.get(0);
        for (AIProvider p : PROVIDERS) {
            if (p.id().equalsIgnoreCase(id)) return p;
        }
        return PROVIDERS.get(0);
    }

    /** Validate + clamp user prompt before network use. */
    static String sanitizePrompt(String s) {
        if (s == null) return "";
        String t = s.trim();
        if (t.length() > MAX_PROMPT) t = t.substring(0, MAX_PROMPT);
        return t;
    }

    public synchronized List<String> historyCopy() {
        return new ArrayList<>(history);
    }

    synchronized void addHistory(String line) {
        history.add(line);
        while (history.size() > 60) history.remove(0);
    }

    /** Async ask with rate-limit + cache. Never blocks caller. */
    public CompletableFuture<AiResult> ask(String providerId, String apiKey,
            String model, String endpoint, String systemPrompt,
            String userPrompt, int timeoutMs, BotManager bot) {
        String prompt = sanitizePrompt(userPrompt);
        if (prompt.isEmpty()) {
            return CompletableFuture.completedFuture(AiResult.failure("prompt is empty"));
        }
        synchronized (this) {
            long now = System.currentTimeMillis();
            if (prompt.equals(lastPrompt) && (now - lastReplyAt) < CACHE_TTL_MS && !lastReply.isEmpty()) {
                return CompletableFuture.completedFuture(AiResult.success(lastReply));
            }
            long since = now - lastCall.get();
            if (since < MIN_INTERVAL_MS) {
                return CompletableFuture.completedFuture(
                        AiResult.failure("rate limited: wait "
                                + ((MIN_INTERVAL_MS - since + 999) / 1000) + "s"));
            }
            lastCall.set(now);
        }
        AIProvider p = byId(providerId);
        String sys = "You control a Minecraft mining bot. "
                + "Reply in plain text. To request bot actions, append lines like "
                + "ACTION: start | stop | pause | resume | set_targets <blocks> "
                + "| set_radius <4-64> | set_limit <0-10000> | status. "
                + "Never invent other commands. " + (systemPrompt == null ? "" : systemPrompt);
        // Give the model live bot context without scanning the world.
        if (bot != null) {
            sys += " Bot state: " + bot.getState().label()
                    + ", targets=" + bot.targets().asPriorityList().size()
                    + ", mined=" + bot.getMinedCount() + ".";
        }
        final String fSys = sys;
        final String fPrompt = prompt;
        return p.complete(apiKey, model, endpoint, fSys, fPrompt, timeoutMs)
                .thenApply(r -> {
                    synchronized (AiService.this) {
                        if (r.ok()) {
                            lastPrompt = fPrompt;
                            lastReply = r.text();
                            lastReplyAt = System.currentTimeMillis();
                            addHistory("You: " + fPrompt);
                            addHistory("AI: " + r.text());
                        }
                    }
                    return r;
                });
    }

    /** Parse + validate model reply into safe actions only. */
    public List<AIAction> parseActions(String reply) {
        List<AIAction> out = new ArrayList<>();
        if (reply == null) return out;
        for (String raw : reply.split("\\r?\\n")) {
            String line = raw.trim();
            if (!line.toUpperCase(Locale.ROOT).startsWith("ACTION:")) continue;
            String cmd = line.substring(7).trim();
            AIAction a = AIAction.parse(cmd);
            if (a != null) out.add(a);
        }
        return out;
    }
}
