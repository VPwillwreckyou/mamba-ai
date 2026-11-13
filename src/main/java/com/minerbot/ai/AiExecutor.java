package com.minerbot.ai;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Single bounded pool for ALL AI network work. Never blocks the client /
 * render thread; never spawns an unbounded thread per request.
 */
public final class AiExecutor {
    private static final AtomicInteger SEQ = new AtomicInteger();
    private static final ExecutorService POOL = Executors.newFixedThreadPool(2, new ThreadFactory() {
        @Override
        public Thread newThread(Runnable r) {
            Thread t = new Thread(r, "miningbot-ai-" + SEQ.incrementAndGet());
            t.setDaemon(true);
            return t;
        }
    });

    private AiExecutor() {
    }

    public static ExecutorService pool() {
        return POOL;
    }
}
