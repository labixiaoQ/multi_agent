async function runVolunteerCaveScenario(bot) {
    bot.chat("starting volunteer cave scenario...");

    // Block types in this scenario
    const gravel_block   = mcData.blocksByName.gravel;
    const diamond_block  = mcData.blocksByName.diamond_ore;

    let lastGravelCount  = -1;
    let lastDiamondCount = -1;
    let isPaused = false;

    // ─── Pause listener ────────────────────────────────────────────────────────
    const pauseListener = (msg) => {
        if (msg === '/pause') {
            isPaused = !isPaused;
        }
    };
    bot.on('chat', pauseListener);

    // ─── Broadcast loop (every 1 second) ───────────────────────────────────────
    // "Waste"  = gravel blocks still blocking the cave entrance
    // "Reward" = diamond_ore blocks remaining inside the cave
    const intervalId = setInterval(async () => {
        try {
            if (isPaused) return;

            const gravelBlocks  = bot.findBlocks({
                matching: gravel_block.id,
                maxDistance: 64,
                count: 50
            });
            const diamondBlocks = bot.findBlocks({
                matching: diamond_block.id,
                maxDistance: 64,
                count: 50
            });

            const gravelCount  = gravelBlocks.length;
            const diamondCount = diamondBlocks.length;

            // Broadcast when counts change (Python parser uses this format)
            if (gravelCount !== lastGravelCount || diamondCount !== lastDiamondCount) {
                bot.chat(`Waste blocks count: ${gravelCount}, Reward blocks count: ${diamondCount}`);
                lastGravelCount  = gravelCount;
                lastDiamondCount = diamondCount;
            }

            // Announce when cave entrance is cleared
            if (gravelCount === 0 && lastGravelCount !== 0) {
                bot.chat("Cave entrance cleared! Both agents can now enter.");
            }

        } catch (err) {
            console.error("Volunteer cave scenario error:", err);
        }
    }, 1000);

    return { intervalId, pauseListener, bot };
}

const caveHandler = await runVolunteerCaveScenario(bot);
