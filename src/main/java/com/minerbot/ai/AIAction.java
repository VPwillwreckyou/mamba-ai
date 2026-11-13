package com.minerbot.ai;

import com.minerbot.BotManager;
import com.minerbot.target.BlockRegistrySearch;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.Identifier;
import net.minecraft.world.level.block.Block;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Controlled action layer: ONLY things AI output may trigger. */
public final class AIAction {

    public enum Kind {
        START, STOP, PAUSE, RESUME, SET_TARGETS, SET_RADIUS, SET_LIMIT, STATUS
    }

    private final Kind kind;
    private final String arg;
    private final List<Block> blocks;

    private AIAction(Kind kind, String arg, List<Block> blocks) {
        this.kind = kind;
        this.arg = arg;
        this.blocks = blocks == null ? List.of() : List.copyOf(blocks);
    }

    public Kind kind() {
        return kind;
    }

    public String describe() {
        return switch (kind) {
            case START -> "Start bot";
            case STOP -> "Stop bot";
            case PAUSE -> "Pause bot";
            case RESUME -> "Resume bot";
            case STATUS -> "Report status";
            case SET_RADIUS -> "Set radius to " + arg;
            case SET_LIMIT -> "Set mining limit to " + arg;
            case SET_TARGETS -> "Set targets to " + arg;
        };
    }

    /** Parse one command (without "ACTION:" prefix). Null = rejected. */
    public static AIAction parse(String cmd) {
        if (cmd == null) return null;
        String t = cmd.trim();
        if (t.isEmpty()) return null;
        String low = t.toLowerCase(Locale.ROOT);
        if (low.equals("start")) return new AIAction(Kind.START, "", null);
        if (low.equals("stop")) return new AIAction(Kind.STOP, "", null);
        if (low.equals("pause")) return new AIAction(Kind.PAUSE, "", null);
        if (low.equals("resume")) return new AIAction(Kind.RESUME, "", null);
        if (low.equals("status")) return new AIAction(Kind.STATUS, "", null);
        if (low.startsWith("set_radius")) {
            String num = t.substring("set_radius".length()).trim();
            try {
                int r = Integer.parseInt(num);
                if (r < 4 || r > 64) return null;
                return new AIAction(Kind.SET_RADIUS, String.valueOf(r), null);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        if (low.startsWith("set_limit")) {
            String num = t.substring("set_limit".length()).trim();
            try {
                int n = Integer.parseInt(num);
                if (n < 0 || n > 10000) return null;
                return new AIAction(Kind.SET_LIMIT, String.valueOf(n), null);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        if (low.startsWith("set_targets")) {
            String rest = t.substring("set_targets".length()).trim();
            if (rest.isEmpty()) return null;
            List<Block> found = resolveBlocks(rest);
            if (found.isEmpty()) return null;
            if (found.size() > 12) found = found.subList(0, 12);
            List<String> names = new ArrayList<>();
            for (Block b : found) names.add(BlockRegistrySearch.displayName(b));
            return new AIAction(Kind.SET_TARGETS, String.join(", ", names), found);
        }
        return null;
    }

    /** Resolve comma/space separated names to real blocks. */
    static List<Block> resolveBlocks(String rest) {
        List<Block> out = new ArrayList<>();
        String[] parts = rest.split("[,;]+");
        List<String> tokens = new ArrayList<>();
        for (String p : parts) {
            String s = p.trim();
            if (!s.isEmpty()) tokens.add(s);
        }
        if (tokens.size() == 1 && tokens.get(0).contains(" ")) {
            tokens = splitWords(tokens.get(0));
        }
        for (String tok : tokens) {
            Block b = findBlock(tok);
            if (b != null && !out.contains(b)) out.add(b);
        }
        return out;
    }

    private static List<String> splitWords(String s) {
        List<String> out = new ArrayList<>();
        String[] w = s.trim().split("\\s+");
        for (int i = 0; i < w.length; i++) {
            Block two = null;
            if (i + 1 < w.length) two = findBlock(w[i] + "_" + w[i + 1]);
            if (two != null) {
                out.add(w[i] + " " + w[i + 1]);
                i++;
            } else {
                out.add(w[i]);
            }
        }
        return out;
    }

    private static Block findBlock(String name) {
        String n = name.trim().toLowerCase(java.util.Locale.ROOT).replace(' ', '_');
        if (n.isEmpty()) return null;
        if (!n.contains(":")) n = "minecraft:" + n;
        try {
            Identifier id = Identifier.parse(n);
            Block b = BuiltInRegistries.BLOCK.getValue(id);
            if (b != null && BuiltInRegistries.BLOCK.getKey(b).equals(id)) return b;
            // Unknown id: fall through to fuzzy search instead of accepting air.
        } catch (Exception ignored) {
        }
        List<Block> hits = BlockRegistrySearch.search(n.replace("minecraft:", ""), 1);
        return hits.isEmpty() ? null : hits.get(0);
    }

    /** Execute on the client thread. Returns human-readable outcome. */
    public String apply(BotManager bot, Minecraft client) {
        if (bot == null) return "bot unavailable";
        switch (kind) {
            case START -> {
                bot.start(client);
                return "bot started";
            }
            case STOP -> {
                bot.stop(client);
                return "bot stopped";
            }
            case PAUSE -> {
                bot.togglePause(client);
                return "bot pause toggled";
            }
            case RESUME -> {
                if (bot.getState() == com.minerbot.BotState.PAUSED) bot.togglePause(client);
                else bot.start(client);
                return "bot resumed";
            }
            case STATUS -> {
                return "state=" + bot.getState().label()
                        + " mined=" + bot.getMinedCount()
                        + " targets=" + bot.targets().asPriorityList().size()
                        + (bot.getStatusDetail().isEmpty() ? "" : " (" + bot.getStatusDetail() + ")");
            }
            case SET_RADIUS -> {
                int r = Integer.parseInt(arg);
                int clamped = Math.max(4, Math.min(64, r));
                bot.config().searchRadius = clamped;
                bot.config().save();
                return "search radius set to " + clamped;
            }
            case SET_LIMIT -> {
                int n = Integer.parseInt(arg);
                int clamped = Math.max(0, Math.min(10000, n));
                bot.config().maxBlocksToMine = clamped;
                bot.config().save();
                return "mining limit set to " + clamped;
            }
            case SET_TARGETS -> {
                bot.targets().clear();
                for (Block b : blocks) bot.targets().add(b);
                return "targets set to " + arg;
            }
            default -> {
                return "rejected";
            }
        }
    }
}
