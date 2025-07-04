# Multi-Chain Marketplace Boilerplate

This package contains an upgradeable NFT marketplace with Hardhat scripts, tests, and a simple frontend hook.

## Setup

```bash
npm install
cp .env.example .env
npx hardhat compile
```

## Testing

```bash
npx hardhat test
```

## Deployment

```bash
npx hardhat run scripts/deploy-upgradeable.js --network mainnet
```

## Upgrade

```bash
PROXY_ADDRESS=0xProxy npx hardhat run scripts/upgrade.js --network mainnet
```
