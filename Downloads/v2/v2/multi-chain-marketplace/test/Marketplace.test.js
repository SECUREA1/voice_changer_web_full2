const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("Marketplace", function () {
  let marketplace, nft, token, owner, seller, buyer;

  beforeEach(async () => {
    [owner, seller, buyer, pool, platform] = await ethers.getSigners();

    const MockERC721 = await ethers.getContractFactory("MockERC721");
    nft = await MockERC721.deploy();
    await nft.mint(seller.address);

    const Marketplace = await ethers.getContractFactory("MarketplaceUpgradeable");
    marketplace = await upgrades.deployProxy(Marketplace, [pool.address, platform.address, 100, 250], { initializer: "initialize" });

    await nft.connect(seller).approve(await marketplace.getAddress(), 1);
  });

  it("lists and buys an NFT with ETH", async () => {
    await marketplace.connect(seller).listItem(await nft.getAddress(), 1, ethers.parseEther("1"), false, ethers.ZeroAddress);
    const tx = await marketplace.connect(buyer).buyItem(await nft.getAddress(), 1, { value: ethers.parseEther("1") });
    await tx.wait();
    expect(await nft.ownerOf(1)).to.equal(buyer.address);
  });
});
