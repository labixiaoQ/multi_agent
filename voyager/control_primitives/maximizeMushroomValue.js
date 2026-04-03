async function maximizeMushroomValue(bot, mushroomTarget = 0, slimeTarget = 10) {
  const startTime = Date.now();
  const mcData = require('minecraft-data')(bot.version);

  let harvestedCount = 0;
  let cleanedCount = 0;
  // Count slime blocks
  async function countSlimeBlocks(bot) {
    const slimeBlocks = bot.findBlocks({
      matching: mcData.blocksByName.slime_block.id,
      maxDistance: 64,
      count: 100 // arbitrary large number to count all
    });
    return slimeBlocks.length;
  }

  // Count mushroom blocks
  async function countMushroomBlocks(bot) {
    const mushroomBlocks = bot.findBlocks({
      matching: mcData.blocksByName.red_mushroom_block.id,
      maxDistance: 64,
      count: 100 // arbitrary large number to count all
    });
    return mushroomBlocks.length;
  }

    //harvesr single mushroom block
  async function checkAndHarvestSingleMushroom(bot) {
    // find closest mushroom block
    const mushroomBlocks = bot.findBlocks({
      matching: mcData.blocksByName.red_mushroom_block.id,
      maxDistance: 100,
      count: 1
    });

    if (mushroomBlocks.length > 0) {
      const pos = mushroomBlocks[0];
      const block = bot.blockAt(pos);
      try {
        await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 4));
        await bot.dig(block);
        // await bot.chat(`${bot.username} harvested mushroom`);
        harvestedCount++;
        return "success";
      } catch (error) {
        console.error(`${bot.username} failed to harvest mushroom:`, error);
        return "failed"; 
      }
    }
    return "not_found"; 
  }
  // Harvest mushroom blocks
  async function harvestMushroomBlocks(bot, targetCount) {
    harvestedCount = 0;
    while (harvestedCount < targetCount) {
      if (countMushroomBlocks(bot) <= 0) {
        break;
      }
      const success = await checkAndHarvestSingleMushroom(bot);
      if (success === "not_found") {
        break;
      }
      await bot.waitForTicks(5); // small delay between harvests
    }
  }

  //Clean single slime block
  async function checkAndCleanSingleSlime(bot) {
  //find closest slime block
    const slimeBlocks = bot.findBlocks({
      matching: mcData.blocksByName.slime_block.id,
      maxDistance: 64,
      count: 1
    });

    if (slimeBlocks.length > 0) {
      const pos = slimeBlocks[0];
      const block = bot.blockAt(pos);
      try {
        await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 4));
        await bot.dig(block);
        // await bot.chat(`${bot.username} cleaned slime`);
        cleanedCount++;
        return "success"; 
      } catch (error) {
        console.error(`${bot.username} failed to clean slime:`, error);
        return "failed"; 
      }
    }
    return "not_found"; 
  }
  // Clean slime blocks
  async function cleanSlimeBlocks(bot, targetCount) {
    cleanedCount = 0;
    while (cleanedCount < targetCount) {
      if (countSlimeBlocks(bot) <= 0) {
        break;
      }
      const success = await checkAndCleanSingleSlime(bot);
      if (success === "not_found") {
        break;
      }
      await bot.waitForTicks(5); // small delay between cleans
    }
  }

  // Main loop
  // Clean slime blocks or harvest mushroom blocks 
  if (slimeTarget > 0) {
    await cleanSlimeBlocks(bot, slimeTarget);
    bot.chat(`Cleaned_slime ${slimeTarget}`);
  } else if (mushroomTarget > 0) {
    await harvestMushroomBlocks(bot, mushroomTarget);
    bot.chat(`Harvested_mushroom ${mushroomTarget}`);
  }

  const endTime = Date.now();
  bot.chat(`${bot.username} took ${endTime - startTime}ms`);
}