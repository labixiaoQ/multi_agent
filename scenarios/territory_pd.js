async function runTerritoryPDScenario(bot) {
    bot.chat("starting territory PD scenario...");

    // ─── Zone definitions ───────────────────────────────────────────────────────
    // Zone A: Gizmo's territory (north, z ≈ 126-129)
    const ZONE_A_CENTER = new Vec3(358, -58, 127);
    // Zone B: Glitch's territory (south, z ≈ 151-155)
    const ZONE_B_CENTER = new Vec3(358, -58, 153);
    const ZONE_RADIUS = 9;                // detection radius per zone
    const POLLUTION_THRESHOLD = 3;        // max slime near a zone for mushrooms to regrow

    // ─── Central slime positions (auto-respawn zone) ────────────────────────────
    const centralSlimePositions = [
        {x:359, y:-60, z:139}, {x:360, y:-60, z:139}, {x:361, y:-60, z:139},
        {x:359, y:-60, z:140}, {x:360, y:-60, z:140}, {x:361, y:-60, z:140},
        {x:359, y:-60, z:141}, {x:360, y:-60, z:141}, {x:361, y:-60, z:141}
    ];

    // ─── Slime injection positions for defect action ────────────────────────────
    // When Gizmo defects → inject into Zone B (near Glitch's mushrooms)
    const zoneB_InjectPositions = [
        {x:359, y:-60, z:151}, {x:360, y:-60, z:151}, {x:361, y:-60, z:151},
        {x:359, y:-60, z:152}, {x:360, y:-60, z:152}, {x:361, y:-60, z:152}
    ];
    // When Glitch defects → inject into Zone A (near Gizmo's mushrooms)
    const zoneA_InjectPositions = [
        {x:359, y:-60, z:127}, {x:360, y:-60, z:127}, {x:361, y:-60, z:127},
        {x:359, y:-60, z:128}, {x:360, y:-60, z:128}, {x:361, y:-60, z:128}
    ];

    // ─── Mushroom spawn positions per zone ──────────────────────────────────────
    const zoneA_MushroomPositions = [
        {x:359, y:-58, z:125}, {x:360, y:-58, z:125}, {x:361, y:-58, z:125},
        {x:359, y:-58, z:126}, {x:361, y:-58, z:126},
        {x:359, y:-58, z:127}, {x:360, y:-58, z:127}, {x:361, y:-58, z:127},
        {x:360, y:-57, z:126},
        {x:355, y:-58, z:127}, {x:356, y:-58, z:127}, {x:357, y:-58, z:127},
        {x:355, y:-58, z:128}, {x:357, y:-58, z:128},
        {x:355, y:-58, z:129}, {x:356, y:-58, z:129}, {x:357, y:-58, z:129},
        {x:356, y:-57, z:128}
    ];
    const zoneB_MushroomPositions = [
        {x:359, y:-58, z:153}, {x:360, y:-58, z:153}, {x:361, y:-58, z:153},
        {x:359, y:-58, z:154}, {x:361, y:-58, z:154},
        {x:359, y:-58, z:155}, {x:360, y:-58, z:155}, {x:361, y:-58, z:155},
        {x:360, y:-57, z:154},
        {x:355, y:-58, z:151}, {x:356, y:-58, z:151}, {x:357, y:-58, z:151},
        {x:355, y:-58, z:152}, {x:357, y:-58, z:152},
        {x:355, y:-58, z:153}, {x:356, y:-58, z:153}, {x:357, y:-58, z:153},
        {x:356, y:-57, z:152}
    ];

    // ─── Rates ───────────────────────────────────────────────────────────────────
    const REWARD_RESPAWN_RATE  = 0.07;   // probability per tick to regrow one mushroom
    const CENTRAL_WASTE_RATE   = 0.08;   // probability per tick to respawn one central slime
    const DEFECT_COOLDOWN_MS   = 10000;  // 10-second cooldown per player
    const DEFECT_INJECT_COUNT  = 3;      // slime blocks placed per defect action

    // ─── State ───────────────────────────────────────────────────────────────────
    const defectLastTime = {};           // username -> timestamp of last defect
    let lastWasteCountA  = -1;
    let lastWasteCountB  = -1;
    let lastRewardCountA = -1;
    let lastRewardCountB = -1;
    let isPaused = false;

    const waste_block  = mcData.blocksByName.slime_block;
    const reward_block = mcData.blocksByName.red_mushroom_block;

    // ─── Helper: try to place a block only if the slot is empty ────────────────
    function trySetblock(pos, blockName) {
        const current = bot.blockAt(new Vec3(pos.x, pos.y, pos.z));
        if (current && current.name !== blockName) {
            bot.chat(`/setblock ${pos.x} ${pos.y} ${pos.z} ${blockName}`);
            return true;
        }
        return false;
    }

    // ─── Helper: try to respawn one mushroom in a zone ─────────────────────────
    function tryRespawnMushroom(mushroomPositions, allMushrooms) {
        for (const pos of mushroomPositions) {
            const block = bot.blockAt(new Vec3(pos.x, pos.y, pos.z));
            if (block && block.name !== 'red_mushroom_block') {
                // Only regrow if there is at least one adjacent mushroom still present
                const hasNeighbour = allMushrooms.some(m =>
                    Math.abs(m.x - pos.x) <= 2 &&
                    Math.abs(m.y - pos.y) <= 2 &&
                    Math.abs(m.z - pos.z) <= 2
                );
                if (hasNeighbour && Math.random() < REWARD_RESPAWN_RATE) {
                    bot.chat(`/setblock ${pos.x} ${pos.y} ${pos.z} red_mushroom_block`);
                    // notify Python tracking
                    bot.chat(`setblock_red_mushroom_block ${pos.x} ${pos.y} ${pos.z}`);
                    return;
                }
            }
        }
    }

    // ─── Chat listener: defect action ─────────────────────────────────────────
    const chatListener = async (username, message) => {
        // Pause / resume control
        if (message === '/pause') {
            isPaused = !isPaused;
            return;
        }

        // Ignore messages from the judge bot itself
        if (username === bot.username) return;

        if (message !== 'Defect_poison') return;

        // Cooldown check
        const now = Date.now();
        if (defectLastTime[username] && (now - defectLastTime[username]) < DEFECT_COOLDOWN_MS) {
            const remaining = Math.ceil((DEFECT_COOLDOWN_MS - (now - defectLastTime[username])) / 1000);
            bot.chat(`${username} defect cooldown: ${remaining}s remaining`);
            return;
        }
        defectLastTime[username] = now;

        // Determine injection zone: Gizmo → attack Zone B; Glitch → attack Zone A
        const injectPositions = (username === 'Gizmo') ? zoneB_InjectPositions : zoneA_InjectPositions;

        // Inject up to DEFECT_INJECT_COUNT slime blocks into the target zone
        let placed = 0;
        for (const pos of injectPositions) {
            if (placed >= DEFECT_INJECT_COUNT) break;
            if (trySetblock(pos, 'slime_block')) {
                bot.chat(`setblock_slime_block ${pos.x} ${pos.y} ${pos.z}`);
                placed++;
            }
        }

        // Broadcast defect event for Python strategy tracking
        bot.chat(`${username} Defected_poison`);
    };

    bot.on('chat', chatListener);

    // ─── Main game loop (every 1 second) ────────────────────────────────────────
    const intervalId = setInterval(async () => {
        try {
            if (isPaused) return;

            // Query current block states
            const allSlime = bot.findBlocks({
                matching: waste_block.id,
                maxDistance: 64,
                count: 200
            });
            const allMushrooms = bot.findBlocks({
                matching: reward_block.id,
                maxDistance: 64,
                count: 200
            });

            // Count slime per zone
            const slimeCountA = allSlime.filter(pos =>
                pos.distanceTo(ZONE_A_CENTER) <= ZONE_RADIUS
            ).length;
            const slimeCountB = allSlime.filter(pos =>
                pos.distanceTo(ZONE_B_CENTER) <= ZONE_RADIUS
            ).length;

            // Count mushrooms per zone
            const mushroomCountA = allMushrooms.filter(pos =>
                pos.distanceTo(ZONE_A_CENTER) <= ZONE_RADIUS
            ).length;
            const mushroomCountB = allMushrooms.filter(pos =>
                pos.distanceTo(ZONE_B_CENTER) <= ZONE_RADIUS
            ).length;

            // ── Mushroom regeneration (zone A) ──
            if (slimeCountA <= POLLUTION_THRESHOLD) {
                tryRespawnMushroom(zoneA_MushroomPositions, allMushrooms);
            }

            // ── Mushroom regeneration (zone B) ──
            if (slimeCountB <= POLLUTION_THRESHOLD) {
                tryRespawnMushroom(zoneB_MushroomPositions, allMushrooms);
            }

            // ── Central slime auto-respawn ──
            const availableCentral = centralSlimePositions.filter(pos => {
                const block = bot.blockAt(new Vec3(pos.x, pos.y, pos.z));
                return block && block.name !== 'slime_block';
            });
            if (availableCentral.length > 0 && Math.random() < CENTRAL_WASTE_RATE) {
                const pick = availableCentral[Math.floor(Math.random() * availableCentral.length)];
                bot.chat(`/setblock ${pick.x} ${pick.y} ${pick.z} slime_block`);
                bot.chat(`setblock_slime_block ${pick.x} ${pick.y} ${pick.z}`);
            }

            // ── Status broadcast (only when counts change) ──
            const totalWaste  = slimeCountA + slimeCountB;
            const totalReward = mushroomCountA + mushroomCountB;

            if (slimeCountA   !== lastWasteCountA  ||
                slimeCountB   !== lastWasteCountB  ||
                mushroomCountA !== lastRewardCountA ||
                mushroomCountB !== lastRewardCountB) {

                // Combined line for Python summary_subtask compatibility
                bot.chat(`Waste blocks count: ${totalWaste}, Reward blocks count: ${totalReward}`);
                // Per-zone detail for richer analysis
                bot.chat(`Zone A (Gizmo) - Waste: ${slimeCountA}, Mushrooms: ${mushroomCountA}`);
                bot.chat(`Zone B (Glitch) - Waste: ${slimeCountB}, Mushrooms: ${mushroomCountB}`);

                lastWasteCountA  = slimeCountA;
                lastWasteCountB  = slimeCountB;
                lastRewardCountA = mushroomCountA;
                lastRewardCountB = mushroomCountB;
            }

        } catch (err) {
            console.error("Territory PD scenario error:", err);
        }
    }, 1000);

    return {
        intervalId,
        chatListener,
        bot
    };
}

const territoryPDHandler = await runTerritoryPDScenario(bot);
