# 🎵 Multi-Chain Music NFT Marketplace

This is a full-stack, multi-chain decentralized application (DApp) for uploading, viewing, and purchasing music NFTs using Ethereum (MetaMask), Solana (Phantom), and Cardano (Nami).

## 🌐 Live Demo
Deployed on [Render](https://render.com) – auto-deploy from GitHub.

---

## 🚀 Features

- 🔌 Connect wallets: MetaMask, Phantom, Nami
- 📤 Upload MP3/WAV files as music NFTs
- 🔊 Uploaded audio is stored and retrievable per wallet via `/api/user-audio`
- 🎧 View NFT listings with audio/3D/visual preview
- 🛒 On-chain purchase flow by chain
- 💱 Choose payment token per listing
- 📊 Purchase response includes payment breakdown
- 📂 In-memory listing store (extendable to DB)
- 🎯 Flask + Blueprint architecture
- 👥 Real-time active user dashboard

---

## 📦 Tech Stack

- Python 3.11 (Flask)
- HTML5 + JS + CSS
- Web3.py / Solana Web3 / Cardano Serialization
- Render Deployment (Dockerized)

---

## 🛠️ Getting Started

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/voice3-marketplace.git
cd voice3-marketplace
pip install -r requirements.txt
```

Before using the app, create an account at `/signup`. Once registered, log in
via `/login`. After signing in you can connect a wallet from the header on any
page using the **Connect Wallet** button. A linked wallet is no longer required
to simply browse pages.

### Persistent user database

By default the application stores credentials in `database/admin.db` inside the
container. To keep user accounts when the service is redeployed, set the
`APP_DB_PATH` environment variable to a location on a persistent volume, e.g.

```bash
export APP_DB_PATH=/data/admin.db
```

When this variable is present the app will read and write the database at that
path instead of recreating `database/admin.db` on each deploy.


### Ethereum RPC Endpoint

The backend uses the `ETH_RPC` environment variable for Ethereum access. By
default it points to the Infura mainnet endpoint below. Override it to use a
different provider:

```bash
export ETH_RPC=https://mainnet.infura.io/v3/e252a3114f6f48a6aa8376e2e5b9dbfb
```

### Ethereum Minting Setup

Specify the ERC-721 contract used for minting and the private key that will sign
transactions:

```bash
export ETH_NFT_CONTRACT=0xYourContractAddress
export ETH_PRIVATE_KEY=0xYourPrivateKey
```

The repository includes `contracts/BasicNFT.sol`, a minimal ERC-721
implementation compatible with this backend.

### BSC RPC Endpoint

Set the Binance Smart Chain provider with the `BSC_RPC` variable:

```bash
export BSC_RPC=https://bsc-rpc.publicnode.com
```

### BSC Minting Setup

Specify your deployed BEP-721 contract and the private key that signs BSC
transactions:

```bash
export BSC_NFT_CONTRACT=0xYourBscContract
export BSC_PRIVATE_KEY=0xYourBscPrivateKey
```

### Marketplace Contract

For demo purposes a simple fixed-price marketplace smart contract is
provided at `contracts/Marketplace.sol`. It lets sellers list any ERC‑721
token, collects a platform fee (default example: 1%) and optionally pays
ERC‑2981 royalties on each sale.

### Deploying the BasicNFT Contract

Run `deploy_contract.py` to deploy the contract to your desired network.
The script expects the corresponding RPC URL and private key to be set via
environment variables (`ETH_RPC`/`ETH_PRIVATE_KEY` for Ethereum or
`BSC_RPC`/`BSC_PRIVATE_KEY` for BSC).

```bash
python deploy_contract.py --chain ethereum
# or
python deploy_contract.py --chain bsc
```

After deployment set `ETH_NFT_CONTRACT` or `BSC_NFT_CONTRACT` to the printed
address so minting works.

### Deploying the LayeredControlNFT Contract

Use the same script with `--contract layered` to deploy the advanced
`LayeredControlNFT.sol` contract. Set the resulting address using
`ETH_LAYERED_CONTRACT` or `BSC_LAYERED_CONTRACT` depending on your target chain.

### Hardhat Compilation & Deployment

A Hardhat project is included under `multi-chain-marketplace`. Install
dependencies and compile the contracts to generate ABI artifacts:

```bash
cd multi-chain-marketplace
npm install
npx hardhat compile
```

Deploy the contracts to your configured network:

```bash
npx hardhat run scripts/deploy.js --network <network>
```

Copy the resulting ABI JSON files from `artifacts/contracts/` into the
`abi/` folder so the Flask app can interact with the deployed contracts.

### Deploying the Marketplace Contract

Use `deploy_contract.py` with the `--contract marketplace` flag. Provide the pool
and platform addresses along with their fee percentages in basis points:

```bash
python deploy_contract.py --contract marketplace --chain ethereum \
    --pool 0xPoolAddress --platform 0xPlatformAddress \
    --pool-bps 100 --platform-bps 250
```

Set `ETH_MARKETPLACE_CONTRACT` or `BSC_MARKETPLACE_CONTRACT` to the deployed
address depending on the chain.

### Marketplace Contract

Deploy `contracts/Marketplace.sol` to enable automatic payment distribution. Set
the deployed address using `ETH_MARKETPLACE_CONTRACT` or
`BSC_MARKETPLACE_CONTRACT` depending on the chain:

```bash
export ETH_MARKETPLACE_CONTRACT=0xYourMarketplace
export BSC_MARKETPLACE_CONTRACT=0xYourBscMarketplace
```

The constructor accepts the pool and platform addresses along with their fee percentages in basis points.


### Solana RPC Endpoint

The backend uses the `SOLANA_RPC` environment variable to contact the Solana
network. If not provided, it defaults to
`https://solana-mainnet.rpcpool.com`. Set this variable to point to your
preferred RPC provider:

```bash
export SOLANA_RPC=https://solana-mainnet.rpcpool.com
```

### Cardano Blockfrost

Provide your Blockfrost project ID via `BLOCKFROST_KEY`. The API base defaults
to `https://cardano-mainnet.blockfrost.io/api/v0` and can be overridden using
`CARDANO_API`:

```bash
export BLOCKFROST_KEY=mainneterVI0Jo3p2fj4MRSVewR8I5dhLKsKNAI
export CARDANO_API=https://cardano-mainnet.blockfrost.io/api/v0
```

### USDT Token Addresses

Set the token contracts used when verifying balances. Defaults point to the
official USDT contracts on each chain.

```bash
export ETH_USDT_ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7
export BSC_USDT_ADDRESS=0x55d398326f99059fF775485246999027B3197955
# Legacy names are also supported:
export ETH_TOKEN_ADDRESS=$ETH_USDT_ADDRESS
export BSC_TOKEN_ADDRESS=$BSC_USDT_ADDRESS
# For Cardano specify the asset ID (policy ID + hex name)
export ADA_USDT_ASSET=
```

### Platform Fee Settings

Configure the pool and platform wallets used by the Marketplace contract and the
percentage of each payment they receive. These values are also used when
simulating payments on unsupported chains:

```bash
export POOL_WALLET=0xPoolWallet
export PLATFORM_WALLET=0xPlatformWallet
export POOL_FEE_BPS=100      # 1%
export PLATFORM_FEE_BPS=250  # 2.5%
export PLATFORM_FEE_RATE=0.01  # Used for simulated payments
```

### RPC Health Check

The app includes a health endpoint to verify blockchain connectivity. Configure
your RPC URLs and Blockfrost project key via environment variables:

- `ETH_RPC` – Ethereum endpoint
- `BSC_RPC` – BSC endpoint
- `SOLANA_RPC` – Solana RPC URL (defaults to https://solana-mainnet.rpcpool.com)
- `BLOCKFROST_KEY` – Blockfrost key for Cardano
- `PLATFORM_WALLET` – address receiving marketplace fees
- `PLATFORM_FEE_RATE` – portion of each sale sent to the platform (default 0.01)

Then call `/api/rpc-health` to check connectivity status for all chains.

### Running the App

Launch the Flask server using Socket.IO so that features like live chat work
correctly. Start the app directly with Python during development:

```bash
python main.py
```

For production deployments use Gunicorn with the Eventlet worker:

```bash
gunicorn -k eventlet -w 1 main:app
```

Starting the app with `flask run` will disable Socket.IO and the chat interface.

### Socket.IO Client Compatibility

The backend includes Flask‑SocketIO 5.3.6 which implements the Socket.IO
protocol v4/v5. When using the chat or active users dashboard, load the client
script from the official CDN:

```html
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
```

Using an outdated or cached copy of `socket.io.js` will trigger the error
"The client is using an unsupported version of the Socket.IO or Engine.IO
protocols." Clear your browser cache if you previously loaded another version.
The bundled templates now reference the CDN path to ensure compatibility with
the server, restoring real‑time features such as the voice changer and chat.

### Troubleshooting

#### Binary argument error

If you encounter `TypeError: Server.emit() got an unexpected keyword argument
"binary"` during live audio streaming, ensure that both `flask-socketio` and
`python-socketio` are at least version 5.0.0. Install compatible versions with:

```bash
pip install "flask-socketio>=5.3.6" "python-socketio>=5.7.0"
```

To upgrade all packages in one step, you can also run:

```bash
pip install --upgrade -r requirements.txt
```

Verify the installed versions with:

```bash
pip show flask-socketio python-socketio
```

Ensure `flask_socketio` is at least `5.3.6` and `python-socketio` is `5.7.0` or newer.
The server now checks these versions at startup and exits with an error if they
are older. Update the packages and redeploy if you see the version mismatch
message.

This resolves a mismatch where Flask‑SocketIO 5.x expects the underlying
`python-socketio` implementation to accept the `binary` parameter when emitting
events.

### Recommended Browsers

Modern browsers like Chrome and Safari handle the live audio features best on mobile devices.
Other browsers may lack support for `MediaSource` and will fall back to basic playback.

### Docker Deployment on Render

The repository includes a Dockerfile configured for Render deployments with SSH
access. It installs `openssh-server` and the `ffmpeg` utility required by
`pydub`, then starts `sshd` alongside Gunicorn:

```Dockerfile
FROM python:3.11
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y \
    openssh-server \
    ffmpeg \
    && mkdir /var/run/sshd
EXPOSE 22
EXPOSE 8000
CMD service ssh start && \
    gunicorn -k eventlet -w 1 --bind 0.0.0.0:$PORT main:app
```

Set `env: docker` in `render.yaml` to have Render build this image.

> **Note:** ffmpeg is required for features like the voice changer and token
> mixer. If it isn't available the backend logs a warning
> `Couldn't find ffmpeg or avconv`. The provided Dockerfile installs ffmpeg so
> these features work out of the box.

### Payment APIs

Two endpoints power on-chain payments and transaction logging:

**POST /marketplace/api/purchase**

 codex/prepare-multi-chain-marketplace-with-full-test-suite
- Executes an on-chain transaction for purchasing an NFT.
- Supports Ethereum, BSC, Solana, and Cardano chains.
- Automatically handles:
  - 💸 Royalty payment via ERC-2981 (if supported)
  - 🏛 Platform fee routing to `PLATFORM_WALLET`
  - 🎁 Reward pool fee routing to `POOL_WALLET`
  - 🧑 Seller payout

Fallback Behavior:
If the backend lacks a private key for the target chain it returns an unsigned transaction payload (EVM compatible) for the wallet to sign and broadcast.

**POST /api/record-payment**

- Logs a transaction already broadcast by a wallet (e.g. MetaMask, Phantom, Nami).
- Useful for purchases initiated and signed client-side.

### On-Chain Purchase Flow (Multi-Chain)

| Chain    | Purchase Mode               | Wallet          | Notes |
|----------|----------------------------|-----------------|-------|
| Ethereum | Marketplace Contract       | MetaMask        | ERC-20 or ETH payments, ERC-2981 royalties |
| BSC      | Marketplace Contract       | MetaMask        | Same as Ethereum (BEP-20 support) |
| Solana   | Instruction Set (unsigned) | Phantom Wallet  | Transaction built on backend, signed by wallet |
| Cardano  | Tx Body (unsigned)         | Nami Wallet     | Built via Blockfrost API, signed by wallet |

### Marketplace Fees

Fees are distributed as follows when an NFT is purchased:

- 🏛 Platform Fee → sent to `PLATFORM_WALLET`
- 🎁 Pool Fee → sent to `POOL_WALLET` (optional)
- 🧑 Seller Receives → sale amount minus platform, pool and royalty fees
- 🎓 Royalty Fee → paid if the NFT implements ERC-2981

All percentages are defined in basis points (bps) where 100 bps = 1%.

Configurable via:

```
export PLATFORM_WALLET=0xPlatformWallet
export POOL_WALLET=0xPoolWallet
export PLATFORM_FEE_BPS=250      # 2.5%
export POOL_FEE_BPS=100          # 1%
export PLATFORM_FEE_RATE=0.01    # Fallback for simulated chains
```

Note: `PLATFORM_FEE_RATE` is used only for fallback/simulated payments on unsupported chains.
Both endpoints expect the wallet address, chain, token symbol, and amount. The
`/marketplace/api/purchase` endpoint executes an on-chain transaction via the `Marketplace` contract, returning the transaction hash and a JSON payment breakdown.
