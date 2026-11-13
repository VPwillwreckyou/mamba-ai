package com.minerbot.ai;

import net.fabricmc.loader.api.FabricLoader;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;

/**
 * Stores AI credentials SEPARATELY from miningbot.json.
 * File: config/miningbot-ai-secret.json (git-ignored).
 * Key is obfuscated (XOR+Base64), never logged. See part 2 below.
 */
public final class AiSecretStore {

    /** Non-secret preferences (provider/model/endpoint). */
    public record AiPrefs(String providerId, String model, String endpoint) {
    }

    static final String FILE = "miningbot-ai-secret.json";
    private static final byte[] PAD =
            "MiningBot-AI-v1-obfuscation-only".getBytes(StandardCharsets.UTF_8);

    private AiSecretStore() {
    }

    public static Path secretPath() {
        return FabricLoader.getInstance().getConfigDir().resolve(FILE);
    }

    public static AiPrefs loadPrefs() {
        return new AiPrefs(readField("provider"), readField("model"), readField("endpoint"));
    }

    public static void savePrefs(String providerId, String model, String endpoint) {
        writeAll(providerId, model, endpoint, readKeyRaw());
    }

    /** Returns stored key or "". Caller must never log it. */
    public static String loadKey() {
        String raw = readKeyRaw();
        if (raw == null) return "";
        String v = deobfuscate(raw);
        return v == null ? "" : v;
    }

    public static void saveKey(String apiKey) {
        AiPrefs p = loadPrefs();
        writeAll(p.providerId(), p.model(), p.endpoint(), apiKey);
    }

    public static void clearKey() {
        AiPrefs p = loadPrefs();
        writeAll(p.providerId(), p.model(), p.endpoint(), "");
    }

    public static boolean hasKey() {
        String raw = readField("key");
        return raw != null && !raw.isEmpty();
    }

    private static void writeAll(String providerId, String model,
            String endpoint, String apiKey) {
        String prov = providerId == null ? "" : providerId;
        String mod = model == null ? "" : model;
        String ep = endpoint == null ? "" : endpoint;
        String key = apiKey == null ? "" : apiKey;
        String json = "{\"provider\":\"" + esc(prov) + "\",\"model\":\"" + esc(mod)
                + "\",\"endpoint\":\"" + esc(ep) + "\",\"key\":\""
                + (key.isEmpty() ? "" : obfuscate(key)) + "\"}";
        try {
            Path path = secretPath();
            Files.createDirectories(path.getParent());
            Files.writeString(path, json, StandardCharsets.UTF_8);
        } catch (IOException e) {
            System.err.println("[MiningBot] Failed to save AI config (key not logged)");
        }
    }

    static String readField(String name) {
        try {
            Path path = secretPath();
            if (!Files.exists(path)) return "";
            String json = Files.readString(path, StandardCharsets.UTF_8);
            String marker = "\"" + name + "\"";
            int i = json.indexOf(marker);
            if (i < 0) return "";
            int colon = json.indexOf(':', i + marker.length());
            if (colon < 0) return "";
            int q1 = json.indexOf('"', colon + 1);
            if (q1 < 0) return "";
            StringBuilder sb = new StringBuilder();
            boolean esc = false;
            for (int k = q1 + 1; k < json.length(); k++) {
                char c = json.charAt(k);
                if (esc) {
                    switch (c) {
                        case 'n' -> sb.append('\n');
                        case 't' -> sb.append('\t');
                        case 'r' -> sb.append('\r');
                        default -> sb.append(c);
                    }
                    esc = false;
                } else if (c == '\\') {
                    esc = true;
                } else if (c == '"') {
                    return sb.toString();
                } else {
                    sb.append(c);
                }
            }
        } catch (IOException ignored) {
        }
        return "";
    }

    private static String readKeyRaw() {
        String v = readField("key");
        return v == null || v.isEmpty() ? null : v;
    }

    static String obfuscate(String key) {
        byte[] b = key.getBytes(StandardCharsets.UTF_8);
        byte[] out = new byte[b.length];
        for (int i = 0; i < b.length; i++) out[i] = (byte) (b[i] ^ PAD[i % PAD.length]);
        return Base64.getEncoder().encodeToString(out);
    }

    static String deobfuscate(String stored) {
        try {
            byte[] b = Base64.getDecoder().decode(stored);
            byte[] out = new byte[b.length];
            for (int i = 0; i < b.length; i++) out[i] = (byte) (b[i] ^ PAD[i % PAD.length]);
            return new String(out, StandardCharsets.UTF_8);
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    private static String esc(String s) {
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> sb.append(c);
            }
        }
        return sb.toString();
    }
}
