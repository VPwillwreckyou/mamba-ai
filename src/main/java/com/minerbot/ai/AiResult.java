package com.minerbot.ai;

import java.util.Optional;

/** Result of an AI completion request. */
public record AiResult(boolean ok, String text, String error) {
    public static AiResult success(String text) {
        return new AiResult(true, text == null ? "" : text, "");
    }

    public static AiResult failure(String error) {
        return new AiResult(false, "", error == null ? "unknown error" : error);
    }

    public Optional<String> textOpt() {
        return ok ? Optional.ofNullable(text) : Optional.empty();
    }
}
