import os
import json
import uuid
import logging
from web3 import Web3
from solana.rpc.api import Client as SolanaClient
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.client import Token
from solders.keypair import Keypair
from solders.pubkey import Pubkey

try:
    from solders.transaction import Transaction
    from solders.system_program import TransferParams, transfer
except ImportError:  # Fallback for older solana-py versions
    from solana.transaction import Transaction
    from solana.system_program import TransferParams, transfer
import subprocess

from pycardano import (
    BlockFrostChainContext,
    PaymentSigningKey,
    PaymentVerificationKey,
    TransactionBuilder,
    TransactionOutput,
    Value,
    Network,
    ScriptHash,
    AssetName,
    MultiAsset,
    Address,
    AuxiliaryData,
    Metadata,
)

from bitcoin.rpc import RawProxy
from bitcoin.core import COutPoint, CMutableTxIn, CMutableTxOut, CMutableTransaction, b2x, lx
from bitcoin.core.script import CScript, OP_RETURN
from bitcoin.wallet import CBitcoinAddress

logger = logging.getLogger(__name__)
PLATFORM_WALLET = os.getenv("PLATFORM_WALLET", "0xPlatformWallet")
PLATFORM_FEE_RATE = float(os.getenv("PLATFORM_FEE_RATE", "0.01"))
PLATFORM_FEE_BPS = int(os.getenv("PLATFORM_FEE_BPS", "250"))
POOL_FEE_BPS = int(os.getenv("POOL_FEE_BPS", "100"))

def payment_breakdown(amount: float) -> dict:
    """Return expected distribution of a marketplace payment."""
    pool_fee = round(amount * POOL_FEE_BPS / 10000, 8)
    platform_fee = round(amount * PLATFORM_FEE_BPS / 10000, 8)
    seller_amount = round(amount - pool_fee - platform_fee, 8)
    return {
        "pool_fee": pool_fee,
        "platform_fee": platform_fee,
        "seller_amount": seller_amount,
    }


def _load_abi(name: str) -> list | None:
    path = os.path.join(os.path.dirname(__file__), "abi", f"{name}.json")
    try:
        with open(path) as f:
            data = json.load(f)
            return data.get("abi")
    except FileNotFoundError:
        logger.warning("ABI file not found: %s", path)
    except Exception as exc:
        logger.warning("Failed to load ABI %s: %s", name, exc)
    return None

ERC721_ABI = _load_abi("BasicNFT") or [
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "string", "name": "tokenURI", "type": "string"},
        ],
        "name": "mint",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

# Minimal ABI for LayeredControlNFT used when minting layered NFTs
LAYERED_NFT_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "string", "name": "tokenURI", "type": "string"},
        ],
        "name": "mintLayered",
        "outputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

ERC20_ABI = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    }
]

MARKETPLACE_ABI = _load_abi("Marketplace") or [
    {
        "inputs": [
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "address", "name": "seller", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "purchase",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

def _mint_evm(chain: str, wallet: str, token_uri: str) -> str:
    rpc = os.getenv(f"{chain.upper()}_RPC")
    contract_addr = os.getenv(f"{chain.upper()}_NFT_CONTRACT")
    priv_key = os.getenv(f"{chain.upper()}_PRIVATE_KEY")

    if not all([rpc, contract_addr, priv_key]):
        raise RuntimeError(f"Missing {chain} configuration")

    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        raise RuntimeError(f"Unable to connect to {chain} RPC")

    contract = w3.eth.contract(address=Web3.to_checksum_address(contract_addr), abi=ERC721_ABI)
    acct = w3.eth.account.from_key(priv_key)
    nonce = w3.eth.get_transaction_count(acct.address)

    base_gas_price = w3.eth.gas_price
    tx_params = {
        "from": acct.address,
        "nonce": nonce,
        "gas": 500000,
        "chainId": w3.eth.chain_id,
    }

    if chain == "ethereum":
        tx_params.update({
            "maxPriorityFeePerGas": w3.to_wei(2, "gwei"),
            "maxFeePerGas": base_gas_price + w3.to_wei(2, "gwei"),
        })
    else:
        tx_params["gasPrice"] = base_gas_price

    txn = contract.functions.mint(wallet, token_uri).build_transaction(tx_params)
    signed = acct.sign_transaction(txn)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    return tx_hash.hex()

def _mint_layered_evm(chain: str, wallet: str, token_uri: str) -> str:
    rpc = os.getenv(f"{chain.upper()}_RPC")
    contract_addr = os.getenv(f"{chain.upper()}_LAYERED_CONTRACT")
    priv_key = os.getenv(f"{chain.upper()}_PRIVATE_KEY")

    if not all([rpc, contract_addr, priv_key]):
        raise RuntimeError(f"Missing {chain} configuration for layered mint")

    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        raise RuntimeError(f"Unable to connect to {chain} RPC")

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_addr), abi=LAYERED_NFT_ABI
    )
    acct = w3.eth.account.from_key(priv_key)
    nonce = w3.eth.get_transaction_count(acct.address)

    base_gas_price = w3.eth.gas_price
    tx_params = {
        "from": acct.address,
        "nonce": nonce,
        "gas": 500000,
        "chainId": w3.eth.chain_id,
    }
    if chain == "ethereum":
        tx_params.update(
            {
                "maxPriorityFeePerGas": w3.to_wei(2, "gwei"),
                "maxFeePerGas": base_gas_price + w3.to_wei(2, "gwei"),
            }
        )
    else:
        tx_params["gasPrice"] = base_gas_price

    txn = contract.functions.mintLayered(wallet, token_uri).build_transaction(
        tx_params
    )
    signed = acct.sign_transaction(txn)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    return tx_hash.hex()

def _mint_solana(wallet: str, metadata_uri: str) -> str:
    rpc = os.getenv("SOLANA_RPC", "https://solana-mainnet.rpcpool.com")
    priv_key = os.getenv("SOLANA_PRIVATE_KEY")

    if not all([rpc, priv_key]):
        raise RuntimeError("Missing Solana configuration")

    secret = json.loads(priv_key) if priv_key.strip().startswith("[") else [int(x) for x in priv_key.split(",")]
    payer = Keypair.from_bytes(bytes(secret))

    client = SolanaClient(rpc)
    mint = Token.create_mint(client, payer, payer.pubkey(), decimals=0, program_id=TOKEN_PROGRAM_ID)
    dest = Pubkey.from_string(wallet)
    ata = mint.create_associated_token_account(dest)
    resp = mint.mint_to(ata, payer, 1)
    return resp.value

def _mint_cardano(wallet: str, metadata: dict) -> str:
    project = os.getenv("BLOCKFROST_KEY")
    payment_skey = os.getenv("CARDANO_PAYMENT_SKEY")
    payment_vkey = os.getenv("CARDANO_PAYMENT_VKEY")
    policy_skey = os.getenv("CARDANO_POLICY_SKEY")
    policy_vkey = os.getenv("CARDANO_POLICY_VKEY")

    if not all([project, payment_skey, payment_vkey, policy_skey, policy_vkey]):
        raise RuntimeError("Missing Cardano configuration")

    context = BlockFrostChainContext(project_id=project, base_url=os.getenv("CARDANO_API", "https://cardano-mainnet.blockfrost.io/api/v0"), network=Network.MAINNET)
    p_skey = PaymentSigningKey.load(payment_skey)
    p_vkey = PaymentVerificationKey.load(payment_vkey)
    policy_skey = PaymentSigningKey.load(policy_skey)
    policy_vkey = PaymentVerificationKey.load(policy_vkey)

    builder = TransactionBuilder(context)
    policy_id = ScriptHash(policy_vkey.hash().payload)
    asset_name = AssetName(bytes(metadata.get("name", "NFT"), "utf-8"))
    ma = MultiAsset.from_primitive({policy_id.payload: {asset_name.payload: 1}})
    output = TransactionOutput(Address.from_primitive(wallet), Value(1500000, ma))
    builder.add_output(output)
    builder.mint = ma
    builder.required_signers = [policy_vkey.hash()]
    aux = AuxiliaryData()
    aux.metadata = Metadata(metadata)
    builder.auxiliary_data = aux

    tx = builder.build_and_sign([p_skey, policy_skey], change_address=Address.from_primitive(wallet))
    context.submit_tx(tx.to_cbor())
    return tx.id

def _mint_bitcoin(wallet: str, metadata: str) -> str:
    rpc_url = os.getenv("BTC_RPC_URL", "http://127.0.0.1:8332")
    rpc_user = os.getenv("BTC_RPC_USER")
    rpc_pass = os.getenv("BTC_RPC_PASSWORD")

    if not all([rpc_user, rpc_pass]):
        raise RuntimeError("Missing Bitcoin RPC configuration")

    proxy = RawProxy(service_url=rpc_url, username=rpc_user, password=rpc_pass)
    utxos = proxy.listunspent(1)
    if not utxos:
        raise RuntimeError("No UTXO available for minting")

    utxo = utxos[0]
    txin = CMutableTxIn(COutPoint(lx(utxo["txid"]), utxo["vout"]))
    send_value = int(utxo["amount"] * 100000000) - 1000
    txout1 = CMutableTxOut(send_value, CBitcoinAddress(wallet).to_scriptPubKey())
    txout2 = CMutableTxOut(0, CScript([OP_RETURN, metadata.encode()]))
    tx = CMutableTransaction([txin], [txout1, txout2])
    signed = proxy.signrawtransactionwithwallet(b2x(tx.serialize()))
    txid = proxy.sendrawtransaction(signed["hex"])
    return b2x(txid)

def _get_decimals(w3: Web3, token_addr: str) -> int:
    contract = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
    try:
        return contract.functions.decimals().call()
    except Exception:
        return 18

def _build_purchase_tx(chain: str, buyer: str, seller: str, amount: float, token: str) -> tuple[dict, Web3]:
    rpc = os.getenv(f"{chain.upper()}_RPC")
    market_addr = os.getenv(f"{chain.upper()}_MARKETPLACE_CONTRACT")
    token_addr = os.getenv(f"{chain.upper()}_{token.upper()}_ADDRESS") or os.getenv(f"{chain.upper()}_TOKEN_ADDRESS")

    if not all([rpc, market_addr, token_addr]):
        raise RuntimeError(f"Missing {chain} configuration")

    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        raise RuntimeError(f"Unable to connect to {chain} RPC")

    decimals = _get_decimals(w3, token_addr)
    contract = w3.eth.contract(address=Web3.to_checksum_address(market_addr), abi=MARKETPLACE_ABI)
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(buyer))
    value = int(amount * 10 ** decimals)
    tx = contract.functions.purchase(token_addr, seller, value).build_transaction({"from": buyer, "nonce": nonce, "gas": 200000, "chainId": w3.eth.chain_id})
    if chain == "ethereum":
        tx.update({"maxPriorityFeePerGas": w3.to_wei(2, "gwei"), "maxFeePerGas": w3.eth.gas_price + w3.to_wei(2, "gwei")})
    else:
        tx.update({"gasPrice": w3.eth.gas_price})
    return tx, w3

def _process_payment_evm(chain: str, from_wallet: str, to_wallet: str, amount: float, token: str) -> str | dict:
    tx, w3 = _build_purchase_tx(chain, from_wallet, to_wallet, amount, token)
    priv_key = os.getenv(f"{chain.upper()}_PRIVATE_KEY")
    if not priv_key:
        return tx
    acct = w3.eth.account.from_key(priv_key)
    tx["from"] = acct.address
    tx["nonce"] = w3.eth.get_transaction_count(acct.address)
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    return tx_hash.hex()

def _process_payment_solana(from_key: str, to_wallet: str, amount: float) -> str:
    rpc = os.getenv("SOLANA_RPC")
    if not rpc:
        raise RuntimeError("Missing Solana RPC config")

    client = SolanaClient(rpc)
    secret = json.loads(from_key) if from_key.strip().startswith("[") else [int(x) for x in from_key.split(",")]
    sender = Keypair.from_bytes(bytes(secret))
    to_pubkey = Pubkey.from_string(to_wallet)

    lamports = int(amount * 1_000_000_000)

    tx = Transaction()
    tx.add(transfer(TransferParams(from_pubkey=sender.pubkey(), to_pubkey=to_pubkey, lamports=lamports)))

    resp = client.send_transaction(tx, sender)
    return resp.value

def _process_payment_cardano(from_wallet: str, to_wallet: str, amount: float) -> str:
    project = os.getenv("BLOCKFROST_KEY")
    signing_key_path = os.getenv("CARDANO_PAYMENT_SKEY")

    if not all([project, signing_key_path]):
        raise RuntimeError("Missing Cardano payment config")

    context = BlockFrostChainContext(project_id=project)
    builder = TransactionBuilder(context)

    skey = PaymentSigningKey.load(signing_key_path)
    sender_address = skey.to_verification_key().to_address(Network.MAINNET)

    output = TransactionOutput(Address.from_primitive(to_wallet), Value.from_primitive([int(amount * 1_000_000)]))
    builder.add_output(output)

    tx = builder.build_and_sign([skey], change_address=sender_address)
    context.submit_tx(tx.to_cbor())
    return tx.id

def _select_utxos(utxos, target_amount_sats):
    selected = []
    total = 0
    for utxo in sorted(utxos, key=lambda x: x["amount"]):
        selected.append(utxo)
        total += int(utxo["amount"] * 100_000_000)
        if total >= target_amount_sats:
            break
    if total < target_amount_sats:
        raise RuntimeError("Insufficient funds across UTXOs")
    return selected, total

def _process_payment_bitcoin(to_wallet: str, amount: float) -> str:
    rpc_url = os.getenv("BTC_RPC_URL")
    rpc_user = os.getenv("BTC_RPC_USER")
    rpc_pass = os.getenv("BTC_RPC_PASSWORD")

    proxy = RawProxy(service_url=rpc_url, username=rpc_user, password=rpc_pass)
    utxos = proxy.listunspent(1)
    amount_sats = int(amount * 100_000_000)
    fee_sats = 1000

    selected_utxos, total_input = _select_utxos(utxos, amount_sats + fee_sats)

    txins = [CMutableTxIn(COutPoint(lx(u["txid"]), u["vout"])) for u in selected_utxos]
    txouts = [CMutableTxOut(amount_sats, CBitcoinAddress(to_wallet).to_scriptPubKey())]

    change = total_input - amount_sats - fee_sats
    if change > 0:
        change_addr = proxy.getnewaddress()
        txouts.append(CMutableTxOut(change, CBitcoinAddress(change_addr).to_scriptPubKey()))

    tx = CMutableTransaction(txins, txouts)
    signed = proxy.signrawtransactionwithwallet(b2x(tx.serialize()))
    return proxy.sendrawtransaction(signed["hex"])

def _process_spl_payment_solana(mint_address: str, sender_key: str, recipient: str, amount: float) -> str:
    rpc = os.getenv("SOLANA_RPC")
    client = SolanaClient(rpc)

    secret = json.loads(sender_key) if sender_key.strip().startswith("[") else [int(x) for x in sender_key.split(",")]
    sender = Keypair.from_bytes(bytes(secret))
    mint_pubkey = Pubkey.from_string(mint_address)

    token = Token(client, mint_pubkey, TOKEN_PROGRAM_ID, sender)
    recipient_pubkey = Pubkey.from_string(recipient)
    ata = token.get_or_create_associated_account_info(recipient_pubkey)
    sender_ata = token.get_or_create_associated_account_info(sender.pubkey())

    decimals = token.get_mint_info().decimals
    amount_raw = int(amount * (10 ** decimals))
    tx_hash = token.transfer(sender_ata.address, ata.address, sender, amount_raw)
    return tx_hash.value

def _process_cardano_native_asset(to_wallet: str, asset_name: str, policy_id: str, amount: int) -> str:
    project = os.getenv("BLOCKFROST_KEY")
    signing_key_path = os.getenv("CARDANO_PAYMENT_SKEY")

    context = BlockFrostChainContext(project_id=project)
    builder = TransactionBuilder(context)

    skey = PaymentSigningKey.load(signing_key_path)
    sender_address = skey.to_verification_key().to_address(Network.MAINNET)

    asset = {policy_id: {asset_name.encode(): amount}}
    ma = MultiAsset.from_primitive(asset)

    output = TransactionOutput(Address.from_primitive(to_wallet), Value(1500000, ma))
    builder.add_output(output)
    builder.mint = ma

    tx = builder.build_and_sign([skey], change_address=sender_address)
    context.submit_tx(tx.to_cbor())
    return tx.id

def get_evm_tx_status(chain: str, tx_hash: str) -> str:
    rpc = os.getenv(f"{chain.upper()}_RPC")
    w3 = Web3(Web3.HTTPProvider(rpc))
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return "confirmed" if receipt and receipt.status == 1 else "failed"

def get_solana_tx_status(tx_hash: str) -> str:
    rpc = os.getenv("SOLANA_RPC")
    client = SolanaClient(rpc)
    result = client.get_confirmed_transaction(tx_hash)
    return "confirmed" if result and result.value else "pending or failed"

def get_cardano_tx_status(tx_hash: str) -> str:
    project = os.getenv("BLOCKFROST_KEY")
    context = BlockFrostChainContext(project_id=project)
    try:
        tx_info = context.api.transaction(tx_hash)
        return "confirmed" if tx_info else "pending or failed"
    except Exception:
        return "pending or failed"

def get_bitcoin_tx_status(tx_hash: str) -> str:
    rpc_url = os.getenv("BTC_RPC_URL")
    rpc_user = os.getenv("BTC_RPC_USER")
    rpc_pass = os.getenv("BTC_RPC_PASSWORD")
    proxy = RawProxy(service_url=rpc_url, username=rpc_user, password=rpc_pass)
    try:
        tx_data = proxy.gettransaction(tx_hash)
        return "confirmed" if tx_data.get("confirmations", 0) > 0 else "pending"
    except Exception:
        return "unknown"

def mint_ordinal_with_ord_cli(inscription_path: str, taproot_address: str, fee_rate: int = 10) -> str:
    result = subprocess.run([
        "ord", "wallet", "inscribe",
        "--fee-rate", str(fee_rate),
        "--destination", taproot_address,
        "--file", inscription_path
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Ordinal mint failed: {result.stderr}")
    return result.stdout.strip()

def mint_nft(chain: str, wallet: str, token_uri: str, metadata: dict | None = None) -> str:
    chain = chain.lower()
    if chain in {"ethereum", "bsc"}:
        if metadata and metadata.get("nft_type") == "layered_control":
            return _mint_layered_evm(chain, wallet, token_uri)
        return _mint_evm(chain, wallet, token_uri)
    elif chain == "solana":
        return _mint_solana(wallet, token_uri)
    elif chain == "cardano":
        return _mint_cardano(wallet, metadata or {})
    elif chain == "bitcoin":
        return _mint_bitcoin(wallet, token_uri)
    raise ValueError(f"Unsupported chain: {chain}")

def process_payment(chain: str, from_wallet: str, to_wallet: str, amount: float, token: str = "USDT") -> str | dict:
    chain = chain.lower()
    if chain in {"ethereum", "bsc"}:
        return _process_payment_evm(chain, from_wallet, to_wallet, amount, token)
    elif chain == "solana":
        priv_key = os.getenv("SOLANA_PRIVATE_KEY")
        if not priv_key:
            raise RuntimeError("Missing Solana private key for payment")
        if token.upper() in {"SOL", "LAMPORT"}:
            return _process_payment_solana(priv_key, to_wallet, amount)
        return _process_spl_payment_solana(token, priv_key, to_wallet, amount)
    elif chain == "cardano":
        if token.upper() in {"ADA", "LOVELACE"}:
            return _process_payment_cardano(from_wallet, to_wallet, amount)
        if "." not in token:
            raise ValueError("Cardano token must be 'policy_id.asset_name'")
        policy_id, asset_name = token.split(".", 1)
        return _process_cardano_native_asset(to_wallet, asset_name, policy_id, int(amount))
    elif chain == "bitcoin":
        return _process_payment_bitcoin(to_wallet, amount)

    raise ValueError(f"Unsupported chain: {chain}")
