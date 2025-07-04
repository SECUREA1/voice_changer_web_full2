const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deploying contracts with:", deployer.address);

  const NFT = await ethers.getContractFactory("BasicNFT");
  const nft = await NFT.deploy();
  await nft.waitForDeployment();
  console.log("NFT deployed to:", await nft.getAddress());

  const Market = await ethers.getContractFactory("Marketplace");
  const marketplace = await Market.deploy();
  await marketplace.waitForDeployment();
  console.log("Marketplace deployed to:", await marketplace.getAddress());
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
