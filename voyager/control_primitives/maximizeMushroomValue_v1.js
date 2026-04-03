async function maximizeMushroomValue(bot, mushroomTarget = 2, slimeTarget = 3) {
  const mcData = require('minecraft-data')(bot.version);

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

  // Harvest mushroom blocks

  async function harvestMushroomBlocks(bot, targetCount) {
    const currentCount = await countMushroomBlocks(bot);
    if (currentCount === 0) return;
    if (currentCount <= targetCount) {
      targetCount = currentCount;
    }
    const mushroomBlocks = bot.findBlocks({
      matching: mcData.blocksByName.red_mushroom_block.id,
      maxDistance: 100,
      count: targetCount
    });

    const sortedMushroomBlocks = mushroomBlocks.sort((a, b) => {
      const distA = bot.entity.position.distanceTo(a);
      const distB = bot.entity.position.distanceTo(b);
      return distA - distB;
    });

    for (const pos of sortedMushroomBlocks) {
      const block = bot.blockAt(pos);
      await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 4));
      await bot.dig(block);
      await bot.chat(bot.username + `harvested mushroom`);
      await bot.waitForTicks(5); // small delay between harvests
    }
  }

  // Clean slime blocks
  async function cleanSlimeBlocks(bot, targetCount) {
    const currentCount = await countSlimeBlocks(bot);
    if (currentCount === 0) return;
    if (currentCount <= targetCount) {
      targetCount = currentCount;
    }

    const slimeBlocks = bot.findBlocks({
      matching: mcData.blocksByName.slime_block.id,
      maxDistance: 64,
      count: targetCount
    });

    // Sort by distance from nearest to farthest
    const sortedSlimeBlocks = slimeBlocks.sort((a, b) => {
      const distA = bot.entity.position.distanceTo(a);
      const distB = bot.entity.position.distanceTo(b);
      return distA - distB;
    });

    for (const pos of sortedSlimeBlocks) {
      const block = bot.blockAt(pos);
      await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 4));
      await bot.dig(block);
      await bot.chat(bot.username + `cleaned slime`);
      await bot.waitForTicks(5); // small delay between cleanings
    }
  }

  // Main loop
  // Clean slime blocks or harvest mushroom blocks 
  if (slimeTarget > 0) {
    await cleanSlimeBlocks(bot, slimeTarget);
    bot.chat(`Cleaned slime ${slimeTarget}`);
  } else if (mushroomTarget > 0) {
    await harvestMushroomBlocks(bot, mushroomTarget);
    bot.chat(`Harvested mushroom ${mushroomTarget}`);
  }
}