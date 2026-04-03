const fs = require('fs');

function randomPoisson(lambda) {
    let L = Math.exp(-lambda);
    let k = 0;
    let p = 1;
    
    do {
        k++;
        p *= Math.random();
    } while (p > L);
    
    return k - 1;
}

async function runCleanupScenario(bot) {

    bot.chat("starting cleanup scenario...");

    const waste_cutoff = 5; //7
    const reward_respawn_rate = 0.05;
    const waste_respawn_rate = 0.05;
    const dirty_tick_speed = 0;
    const clean_tick_speed = 100;

    const reward_block = mcData.blocksByName.red_mushroom_block;
    const stem_block = mcData.blocksByName.mushroom_stem;
    const waste_block = mcData.blocksByName.slime_block;

    // Set the tick speed to high to grow berries
    // bot.chat(`/gamerule randomTickSpeed 40000`);
    // await bot.waitForTicks(60);
    // bot.chat(`/gamerule randomTickSpeed ${dirty_tick_speed}`);
  
    // Find the waste and reward blocks
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
    const stemLocations = bot.findBlocks({
        matching: stem_block.id,
        maxDistance: 64,
        count: 100
    });

    var clean = false;
    
    // 添加状态变量来追踪上一次的方块数量
    let lastWasteCount = 0;
    let lastRewardCount = 0;

    const intervalId = setInterval(async () => {

        // Check if there are less than cutoff waste blocks
        if (bot.findBlocks({
            matching: waste_block.id,
            maxDistance: 64,
            count: 100
        }).length <= waste_cutoff) {

            if (!clean) {
                // Set the tick speed to high to grow berries
                bot.chat("The river is clean!");
                // bot.chat(`/gamerule randomTickSpeed ${clean_tick_speed}`);
                clean = true;
            }
        
            // 使用泊松分布生成奖励方块
            // const rewardCount = randomPoisson(1); // 平均每秒生成 1 个
            const rewardCount = 1; // 每秒生成 1 个
            let maxRetries = rewardLocations.length; // 设置最大重试次数
            for (let i = 0; i < rewardCount; ) { // 移除自动 i++，手动控制
                const location = rewardLocations[Math.floor(Math.random() * rewardLocations.length)]; 
                const { x, y, z } = location; 

                const currentBlock = bot.blockAt(location); 
                if (currentBlock && currentBlock.name !== "red_mushroom_block") { 
                    bot.chat(`/setblock ${x} ${y} ${z} red_mushroom_block`); 
                    bot.chat(`setblock_red_mushroom_block ${x} ${y} ${z}`); 
                    i++; // 只有成功放置才增加计数
                } else {
                    maxRetries--;
                    if (maxRetries <= 0) {
                        // console.log("达到最大重试次数，无法放置更多奖励方块");
                        break;
                    }
                } 
            }
        } else {
            if (clean) {
                bot.chat("The river is too dirty!");
                clean = false;
            }
        }

        // 使用泊松分布生成废弃物方块
        // const wasteCount = randomPoisson(2); // 平均每秒生成 2 个
        const wasteCount = 1; // 每秒生成 1 个
        let maxRetries = wasteLocations.length; // 设置最大重试次数
        for (let i = 0; i < wasteCount; ) { // 移除自动 i++，手动控制
            const location = wasteLocations[Math.floor(Math.random() * wasteLocations.length)]; 
            const { x, y, z } = location; 

            const currentBlock = bot.blockAt(location); 
            if (currentBlock && currentBlock.name !== "slime_block") { 
                bot.chat(`/setblock ${x} ${y} ${z} slime_block`); 
                bot.chat(`setblock_slime_block ${x} ${y} ${z}`); 
                i++; // 只有成功放置才增加计数
            } else {
                maxRetries--;
                if (maxRetries <= 0) {
                    // console.log("达到最大重试次数，无法放置更多废弃物方块");
                    break;
                }
            } 
        }
        
        // stemLocations.forEach(location => {
        //     const { x, y, z } = location;
            
        //     // Generate a random number between 0 and 1
        //     const rand = Math.random();

        //     // Respawn the block with probability
        //     if (rand < reward_respawn_rate) {
        //         bot.chat(`/setblock ${x} ${y} ${z} mushroom_stem`);
        //     }
        // });

        //计数
        const wasteCount_result = bot.findBlocks({
            matching: waste_block.id,
            maxDistance: 32,
            count: 100
        });
       const rewardCount_result = bot.findBlocks({
            matching: reward_block.id,
            maxDistance:32,
            count: 100
        });
        
        // 检查数量是否有变化，如果有变化才发送聊天消息
        if (wasteCount_result.length !== lastWasteCount || rewardCount_result.length !== lastRewardCount) {
            bot.chat(`Waste blocks count: ${wasteCount_result.length}, Reward blocks count: ${rewardCount_result.length}`);
            
            // 更新上一次的数量
            lastWasteCount = wasteCount_result.length;
            lastRewardCount = rewardCount_result.length;
        }
        
        // if (wasteCount != bot.findBlocks({
        //     matching: waste_block.id,
        //     maxDistance: 32,
        //     count: 100
        // })) {
        //     wasteCount = bot.findBlocks({
        //         matching: waste_block.id,
        //         maxDistance: 32,
        //         count: 100
        //     });
        //     bot.chat(`Waste blocks count: ${wasteCount.length}`);
        // }
        // if (rewardCount != bot.findBlocks({
        //     matching: reward_block.id,
        //     maxDistance: 32,
        //     count: 100
        // })) {
        //     rewardCount = bot.findBlocks({
        //         matching: reward_block.id,
        //         maxDistance: 32,
        //         count: 100
        //     });
        //     bot.chat(`Reward blocks count: ${rewardCount.length}`);
        // }
    }, 1000);



    
}
await runCleanupScenario(bot);