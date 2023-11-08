import random
from pysui import handle_result
from pysui.sui.sui_bcs import bcs
from pysui.sui.sui_types import *
from pysui import SuiConfig, SyncClient
from pysui.abstracts import SignatureScheme
from pysui.sui.sui_txn import SyncTransaction
from pysui.sui.sui_types.address import SuiAddress
from pysui.sui.sui_clients.sync_client import SuiClient
from pysui.sui.sui_txn.transaction_builder import PureInput
from pysui.sui.sui_types.bcs import Argument
from loguru import logger
import requests
import time
from pydantic import BaseModel
from typing import Optional

delay = 0.24 * 3600
sui_rpc = 'https://rpc.ankr.com/sui/045a767e1ce5aa38aa0b766337d4bc95963565b155a2f590f387c94e410fef8b'


class Sui8192TransactionResult(BaseModel):
    address: str
    digest: str


class SuiTxResult(Sui8192TransactionResult):
    reason: Optional[str]


def read_file(filename):
    result = []
    with open(filename, 'r') as file:
        for tmp in file.readlines():
            result.append(tmp.replace('\n', ''))

    return result


def write_to_file(filename, text):
    with open(filename, 'a') as file:
        file.write(f'{text}\n')


def generate_suins():
    word = requests.get('https://random-word-api.herokuapp.com/word').json()[0][:random.randint(7, 9)]
    while len(word) < random.randint(10, 14):
        word += str(random.randint(0, 9))

    return word


def get_all_token(client, token):
    while True:
        try:
            """ Возвращает все объекты адреса (если они есть) и их баланс """

            # Создаёт(если его нет) элемент "client"
            client = client if client else SuiClient(SuiConfig.default_config())
            # Достаёт все объекты указанного токена

            all_coin_type = client.get_coin(SuiString(token)).result_data.data

            # Обрабатывает объекты
            gas_objects: list[all_coin_type] = handle_result(
                client.get_gas(
                    client.config.active_address
                )
            ).data

            return all_coin_type

        except:
            time.sleep(5)


def get_sui_configs(mnemonic: str) -> SuiConfig:
    sui_config = SuiConfig.user_config(rpc_url=sui_rpc)
    if '0x' in mnemonic:
        sui_config.add_keypair_from_keystring(keystring={
            'wallet_key': mnemonic,
            'key_scheme': SignatureScheme.ED25519
        })
    else:
        sui_config.recover_keypair_and_address(
            scheme=SignatureScheme.ED25519,
            mnemonics=mnemonic,
            derivation_path="m/44'/784'/0'/0'/0'"
        )
    sui_config.set_active_address(address=SuiAddress(sui_config.addresses[0]))

    return sui_config


def get_sui_coin_objects_for_merge(client):
    all_coin_type = get_all_token(client, "0x2::sui::SUI")

    gas_objects: list[all_coin_type] = handle_result(
        client.get_gas(
            client.config.active_address)
    ).data

    zero_coins = [x for x in gas_objects if int(x.balance) == 0]
    non_zero_coins = [x for x in gas_objects if int(x.balance) > 0]

    richest_coin = max(non_zero_coins, key=lambda x: int(x.balance), default=None)
    gas_amount_coin = min(non_zero_coins, key=lambda x: int(x.balance), default=None)

    if richest_coin:
        non_zero_coins.remove(richest_coin)

    return zero_coins, non_zero_coins, richest_coin, gas_amount_coin


def transaction_run(txb: SyncTransaction):
    """Example of simple executing a SuiTransaction."""
    # Set sender if not done already
    if not txb.signer_block.sender:
        txb.signer_block.sender = txb.client.config.active_address

    # Execute the transaction
    tx_result = txb.execute(gas_budget="55865000")
    if tx_result.is_ok():
        owner = tx_result.result_data.balance_changes[0]['owner']['AddressOwner']
        digest = tx_result.result_data.digest
        logger.success(f"Coinflip Success! {owner} | Transaction success! Digest: {digest}")
        write_to_file('Digests.txt', f'{owner};{digest}')
        return tx_result.result_data

    else:
        logger.error(f"Transaction error {tx_result}")


def coinflip(client):
    txer = SyncTransaction(client)
    spcoin = txer.split_coin(coin=Argument("GasCoin"), amounts=[1_000_000_000])

    txer.move_call(
        target="0x4c2d27c9639362c062148d01ed28cf58430cefadd43267c2e176d93259c258e2::coin_flip_v2::start_game",
        arguments=[
            ObjectID('0x464ea97815fdf7078f8d0358dcc8639afba8c53c587d5ce4217940e9870e8e74'),
            SuiU8(random.randint(0, 1)),
            SuiArray([SuiInteger(random.randint(1, 255)) for _ in range(512)]),
            spcoin,
        ],
        type_arguments=['0x2::sui::SUI']
    )
    # PureInput().as_input(SuiString(f'{name}.sui')),

    return transaction_run(txer)


def create_gas_object(amount, client: SuiClient = None):
    client = client if client else SuiClient(SuiConfig.default_config())
    txer = SyncTransaction(client)

    amount = int(amount * 10 ** 9)
    spcoin = txer.split_coin(coin=bcs.Argument("GasCoin"), amounts=[amount])
    txer.transfer_objects(transfers=[spcoin], recipient=client.config.active_address)

    tx_result = txer.execute(gas_budget="55865000")

    if tx_result.is_ok():
        return logger.success("Create gas object done")
    else:
        return logger.error("Create gas object error")


def init_transaction(client, merge_gas_budget: bool = False) -> SyncTransaction:
    return SyncTransaction(
        client=client,
        initial_sender=client.config.active_address,
        merge_gas_budget=merge_gas_budget)


def build_and_execute_tx(client, transaction: SyncTransaction,
                         gas_object: ObjectID = None) -> SuiTxResult:
    build = transaction.inspect_all()
    if build.error:
        return SuiTxResult(
            address=str(client.active_address),
            digest='',
            reason=build.error
        )
    else:
        try:
            if gas_object:
                rpc_result = transaction.execute(use_gas_object=gas_object, gas_budget="55865000")
            else:
                rpc_result = transaction.execute(gas_budget="55865000")
            if rpc_result.result_data:
                if rpc_result.result_data.status == 'success':
                    try:
                        return SuiTxResult(
                            address=str(client.config.active_address),
                            digest=rpc_result.result_data.digest
                        )
                    except:
                        pass
                else:
                    try:
                        return SuiTxResult(
                            address=str(client.config.active_address),
                            digest=rpc_result.result_data.digest,
                            reason=rpc_result.result_data.status
                        )
                    except:
                        pass
            else:
                try:
                    return SuiTxResult(
                        address=str(client.config.active_address),
                        digest='',
                        reason=str(rpc_result.result_string)
                    )
                except:
                    pass
        except Exception as e:
            logger.exception(e)


def merge_sui_coins_tx(client):
    merge_results = []

    zero_coins, non_zero_coins, richest_coin, _ = get_sui_coin_objects_for_merge(client)
    if len(zero_coins) and len(non_zero_coins):
        logger.info('Попытка to merge zero_coins.')
        transaction = init_transaction(client)
        transaction.merge_coins(merge_to=transaction.gas, merge_from=zero_coins)
        try:
            build_result = build_and_execute_tx(
                client,
                transaction=transaction,
                gas_object=ObjectID(richest_coin.object_id)
            )
        except:
            pass
        if build_result:
            merge_results.append(build_result)
            time.sleep(5)
        zero_coins, non_zero_coins, richest_coin, _ = get_sui_coin_objects_for_merge(client)

    if len(non_zero_coins):
        logger.info('Попытка to merge non_zero_coins.')
        transaction = init_transaction(client)
        transaction.merge_coins(merge_to=transaction.gas, merge_from=non_zero_coins)
        build_result = build_and_execute_tx(
            client,
            transaction=transaction,
            gas_object=ObjectID(richest_coin.object_id)
        )
        if build_result:
            merge_results.append(build_result)


def main():
    mnemonics = read_file('mnemonics.txt')
    avg_sleep = delay / len(mnemonics)
    for mnemonic in mnemonics:
        try:
            config = get_sui_configs(mnemonic)
            client_ = SyncClient(config)
            while len(get_all_token(client_, "0x2::sui::SUI")) not in [0, 1]:
                merge_sui_coins_tx(client_)
            time.sleep(0.2)
            coinflip(client_)
            time.sleep(random.uniform(avg_sleep*0.5, avg_sleep*0.9))
        except Exception as e:
            logger.error(f'{config.active_address} | Error: {e}')
            if mnemonics.count(mnemonic) <= 5:
                mnemonics.append(mnemonic)
            else:
                write_to_file('Error.txt', mnemonic)
        # exit()


if __name__ == '__main__':
    main()
