require("@nomicfoundation/hardhat-toolbox");
require("@openzeppelin/hardhat-upgrades");
require("dotenv").config();

const config = {
  solidity: "0.8.26",
  networks: { hardhat: {} },
  paths: {
    sources: "../contracts",
  },
};

if (process.env.ETH_RPC && process.env.PRIVATE_KEY) {
  config.networks.mainnet = {
    url: process.env.ETH_RPC,
    accounts: [process.env.PRIVATE_KEY],
  };
}

if (process.env.BSC_RPC && process.env.PRIVATE_KEY) {
  config.networks.bsc = {
    url: process.env.BSC_RPC,
    accounts: [process.env.PRIVATE_KEY],
  };
}

module.exports = config;
