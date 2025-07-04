const { ethers, upgrades } = require("hardhat");

async function main() {
  const Marketplace = await ethers.getContractFactory("MarketplaceUpgradeable");
  const instance = await upgrades.deployProxy(Marketplace, [
    "0xPoolWallet",
    "0xPlatformWallet",
    100,
    250,
  ], {
    initializer: "initialize",
  });
  await instance.waitForDeployment();
  console.log("Marketplace deployed to:", await instance.getAddress());
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
