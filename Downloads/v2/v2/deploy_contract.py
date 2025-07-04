import argparse
import os
from web3 import Web3
from solcx import compile_source, install_solc

BASE_DIR = os.path.join(os.path.dirname(__file__), 'contracts')
CONTRACTS = {
    'basicnft': 'BasicNFT.sol',
    'layered': 'LayeredControlNFT.sol',
    'marketplace': 'Marketplace.sol',
}


def load_source(contract: str) -> str:
    path = os.path.join(BASE_DIR, CONTRACTS[contract])
    with open(path) as f:
        return f.read()


def deploy_evm(
    chain: str,
    contract: str,
    name: str = 'VoiceNFT',
    symbol: str = 'VNFT',
    pool: str | None = None,
    platform: str | None = None,
    pool_bps: int = 0,
    platform_bps: int = 0,
) -> str:
    chain = chain.lower()
    if chain == 'ethereum':
        rpc = os.getenv('ETH_RPC')
        priv_key = os.getenv('ETH_PRIVATE_KEY')
    elif chain == 'bsc':
        rpc = os.getenv('BSC_RPC')
        priv_key = os.getenv('BSC_PRIVATE_KEY')
    else:
        raise ValueError('Unsupported chain: ' + chain)

    if not rpc or not priv_key:
        raise RuntimeError(f'Missing {chain} configuration')

    install_solc('0.8.20')
    source = load_source(contract)
    compiled = compile_source(
        source,
        output_values=['abi', 'bin'],
        solc_version='0.8.20'
    )
    _, interface = compiled.popitem()
    abi = interface['abi']
    bytecode = interface['bin']

    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        raise RuntimeError(f'Unable to connect to {chain} RPC')
    account = w3.eth.account.from_key(priv_key)
    contract_obj = w3.eth.contract(abi=abi, bytecode=bytecode)

    if contract in {'basicnft', 'layered'}:
        tx = contract_obj.constructor(name, symbol).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 2000000,
        })
    else:
        tx = contract_obj.constructor(pool, platform, pool_bps, platform_bps).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 2000000,
        })

    base_gas_price = w3.eth.gas_price
    if chain == 'ethereum':
        tx.update({
            'maxPriorityFeePerGas': w3.to_wei(2, 'gwei'),
            'maxFeePerGas': base_gas_price + w3.to_wei(2, 'gwei'),
            'chainId': w3.eth.chain_id,
        })
    else:
        tx.update({'gasPrice': base_gas_price, 'chainId': w3.eth.chain_id})

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print('Deploy TX sent:', tx_hash.hex())
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print('Contract deployed at:', receipt.contractAddress)
    return receipt.contractAddress


def main():
    parser = argparse.ArgumentParser(description='Deploy contracts to EVM chains')
    parser.add_argument('--chain', choices=['ethereum', 'bsc'], required=True)
    parser.add_argument('--contract', choices=['basicnft', 'layered', 'marketplace'], default='basicnft')
    parser.add_argument('--name', default='VoiceNFT')
    parser.add_argument('--symbol', default='VNFT')
    parser.add_argument('--pool')
    parser.add_argument('--platform')
    parser.add_argument('--pool-bps', type=int, default=0)
    parser.add_argument('--platform-bps', type=int, default=0)
    args = parser.parse_args()

    addr = deploy_evm(
        args.chain,
        args.contract,
        args.name,
        args.symbol,
        args.pool,
        args.platform,
        args.pool_bps,
        args.platform_bps,
    )
    if args.contract == 'basicnft':
        env_var = 'ETH_NFT_CONTRACT' if args.chain == 'ethereum' else 'BSC_NFT_CONTRACT'
    elif args.contract == 'layered':
        env_var = 'ETH_LAYERED_CONTRACT' if args.chain == 'ethereum' else 'BSC_LAYERED_CONTRACT'
    else:
        env_var = 'ETH_MARKETPLACE_CONTRACT' if args.chain == 'ethereum' else 'BSC_MARKETPLACE_CONTRACT'
    print(f'Set {env_var}={addr} to use the contract')


if __name__ == '__main__':
    main()
