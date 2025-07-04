"""Utility to check RPC connectivity for all supported chains."""

import os
import requests
from web3 import Web3
from solana.rpc.api import Client as SolanaClient

CARDANO_API = os.getenv("CARDANO_API", "https://cardano-mainnet.blockfrost.io/api/v0")
BLOCKFROST_KEY = os.getenv("BLOCKFROST_KEY")
ETH_RPC = os.getenv("ETH_RPC")
BSC_RPC = os.getenv("BSC_RPC")
SOLANA_RPC = os.getenv("SOLANA_RPC", "https://solana-mainnet.rpcpool.com")


def check_eth(rpc: str | None) -> bool:
    if not rpc:
        return False
    try:
        w3 = Web3(Web3.HTTPProvider(rpc))
        return w3.is_connected()
    except Exception:
        return False


def check_solana(rpc: str | None) -> bool:
    if not rpc:
        return False
    try:
        client = SolanaClient(rpc)
        client.get_health()
        return True
    except Exception:
        return False


def check_cardano(api: str | None, key: str | None) -> bool:
    if not api or not key:
        return False
    try:
        headers = {"project_id": key}
        resp = requests.get(f"{api}/health", headers=headers, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def check_all() -> dict:
    return {
        "ethereum": check_eth(ETH_RPC),
        "bsc": check_eth(BSC_RPC),
        "solana": check_solana(SOLANA_RPC),
        "cardano": check_cardano(CARDANO_API, BLOCKFROST_KEY),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(check_all(), indent=2))
