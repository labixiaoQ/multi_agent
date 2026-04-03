// 移除无用的fs模块引入
// const fs = require('fs');
async function runCleanupScenario(bot) {
    bot.chat("starting cleanup scenario...");

    const waste_cutoff = 5;
    const reward_respawn_rate = 0.05;
    const waste_respawn_rate = 0.05;
    const dirty_tick_speed = 0;
    const clean_tick_speed = 100;
    let lastWasteCount = -1;
    let lastRewardCount = -1;
    // 新增：暂停状态标记，初始为未暂停
    let isPaused = false;

    const reward_block = mcData.blocksByName.red_mushroom_block;
    const stem_block = mcData.blocksByName.mushroom_stem; // 保留定义，若后续有用可保留，无用可直接删除
    const waste_block = mcData.blocksByName.slime_block;

    // 仅初始化查询一次基础位置（无需重复查询，提升性能）
    const wasteLocations = bot.findBlocks({
        matching: waste_block.id,
        maxDistance: 64,
        count: 100
    });
    const rewardLocations = bot.findBlocks({
        matching: reward_block.id,
        maxDistance:64,
        count: 100
    });

    let clean = false;
    let intervalId = null; // 定时器ID，用于后续销毁
    // 新增：存储pause指令监听器，方便外部解绑（避免内存泄漏）
    let pauseListener = null;

    // 封装通用放置块函数（复用逻辑，减少冗余代码）
    const placeBlock = async (locations, targetBlockName, chatPrefix) => {
        // 1. 原有逻辑：过滤可用空白位置（保留，避免重复放置）
        const availableLocations = locations.filter(loc => {
            const block = bot.blockAt(loc);
            return block && block.name !== targetBlockName;
        });
        if (availableLocations.length === 0) {
            return false;
        }

        // 2. 原有逻辑：随机选取目标位置（保留）
        const randomLoc = availableLocations[Math.floor(Math.random() * availableLocations.length)];
        const { x, y, z } = randomLoc;

        try {
            // 3. 执行放置指令（原有逻辑，保留）
            bot.chat(`/setblock ${x} ${y} ${z} ${targetBlockName}`);

            // 4. 关键：等待极短时间让游戏处理指令（核心，不可省略）
            // 游戏执行/setblock非即时，100-300ms足够，可根据游戏延迟微调
            await new Promise(resolve => setTimeout(resolve, 200));

            // 5. 核心校验逻辑：主动获取目标坐标的实际方块，验证放置结果
            const placedBlock = bot.blockAt(randomLoc); // 根据原坐标获取方块
            // 双重校验：① 区块已加载（placedBlock非null） ② 方块名匹配目标
            const isPlaceSuccess = placedBlock && placedBlock.name === targetBlockName;

            // 6. 仅放置成功时执行播报（满足你的核心需求）
            if (isPlaceSuccess) {
                bot.chat(`${chatPrefix} ${x} ${y} ${z}`);
            }

            // 7. 返回放置结果（true=成功，false=失败，外部可接收）
            return isPlaceSuccess;
        } catch (error) {
            // 异常捕获：防止指令执行、方块检测时的意外报错
            console.warn(`放置方块异常（位置[${x},${y},${z}]，方块：${targetBlockName}）：`, error);
            return false;
        }
    };
    // 新增：监听/pause聊天指令，实现暂停/恢复切换
    pauseListener = (msg) => {
        if (msg === '/pause') { // 仅响应/pause指令
            isPaused = !isPaused; // 切换暂停状态
            // 给玩家反馈暂停/恢复结果
            // bot.chat(isPaused ? "Cleanup scenario paused! No more block generation." : "Cleanup scenario resumed! Block generation continues.");
        }
    };
    // 绑定chat事件监听器
    bot.on('chat', pauseListener);

    intervalId = setInterval(async () => {
        // 关键：async定时器回调必须加try/catch，捕获所有错误并打印
        try {
            // 核心新增：如果处于暂停状态，直接跳过本次所有操作
            if (isPaused) return;

            // 1. 查询当前块数量（仅一次查询，复用结果，提升性能）
            const currentWasteBlocks = bot.findBlocks({
                matching: waste_block.id,
                maxDistance: 64,
                count: 100
            });
            const currentRewardBlocks = bot.findBlocks({
                matching: reward_block.id,
                maxDistance: 64,
                count: 100
            });
            const currentWasteCount = currentWasteBlocks.length;
            const currentRewardCount = currentRewardBlocks.length;

            // 2. 河流清洁/脏污状态判断
            if (currentWasteCount <= waste_cutoff) {
                if (!clean) {
                    bot.chat("The river is clean!");
                    clean = true;
                }
                // 生成奖励方块（每秒生成1个）
                await placeBlock(rewardLocations, "red_mushroom_block", "setblock_red_mushroom_block");
            } else {
                if (clean) {
                    bot.chat("The river is too dirty!");
                    clean = false;
                }
            }

            // 3. 生成废弃物方块（每秒1个，无条件生成，保留原有逻辑）
            await placeBlock(wasteLocations, "slime_block", "setblock_slime_block");

            // 4. 计数播报（仅数量变化时播报，减少刷屏）
            if (currentWasteCount !== lastWasteCount || currentRewardCount !== lastRewardCount) {
                bot.chat(`Waste blocks count: ${currentWasteCount}, Reward blocks count: ${currentRewardCount}`);
                lastWasteCount = currentWasteCount;
                lastRewardCount = currentRewardCount;
            }

        } catch (error) {
            // 错误捕获：打印错误信息，避免定时器静默失败
            console.error("定时器执行错误：", error);
            // bot.chat(`Cleanup scenario error: ${error.message}`);
        }
    }, 1000);

    // 改造返回值：包含定时器ID和监听器，方便外部完整清理
    return {
        intervalId, // 用于停止定时器
        pauseListener, // 用于解绑chat事件
        bot // 用于外部调用解绑方法
    };
}

// 执行函数（保留原有调用方式，返回清理对象）
const cleanupHandler = await runCleanupScenario(bot);