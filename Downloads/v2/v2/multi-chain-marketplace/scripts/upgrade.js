const { ethers, upgrades } = require("hardhat");

async function main() {
  const newImplementation = await ethers.getContractFactory("MarketplaceUpgradeable");
  const proxyAddress = process.env.PROXY_ADDRESS;
  if (!proxyAddress) throw new Error("PROXY_ADDRESS not set");
  await upgrades.upgradeProxy(proxyAddress, newImplementation);
  console.log("Marketplace upgraded");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
