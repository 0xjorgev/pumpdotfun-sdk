from bot.config import appconfig
from bot.domain.jito_rpc import JitoJsonRpcSDK

import asyncio
import base64
import json
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.transaction_status import TransactionConfirmationStatus
from solders.signature import Signature
from solders.message import Message
from solders.instruction import Instruction
from solana.rpc.async_api import AsyncClient


async def check_transaction_status(client: AsyncClient, signature_str: str):
    print("Checking transaction status...")
    max_attempts = 60  # 60 seconds
    attempt = 0
    
    signature = Signature.from_string(signature_str)
    
    while attempt < max_attempts:
        try:
            response = await client.get_signature_statuses([signature])
            
            if response.value[0] is not None:
                status = response.value[0]
                slot = status.slot
                confirmations = status.confirmations
                err = status.err
                confirmation_status = status.confirmation_status

                print(f"Slot: {slot}")
                print(f"Confirmations: {confirmations}")
                print(f"Confirmation status: {confirmation_status}")
                
                if err:
                    print(f"Transaction failed with error: {err}")
                    return False
                elif confirmation_status == TransactionConfirmationStatus.Finalized:
                    print("Transaction is finalized.")
                    return True
                elif confirmation_status == TransactionConfirmationStatus.Confirmed:
                    print("Transaction is confirmed but not yet finalized.")
                elif confirmation_status == TransactionConfirmationStatus.Processed:
                    print("Transaction is processed but not yet confirmed or finalized.")
            else:
                print("Transaction status not available yet.")
            
            await asyncio.sleep(1)
            attempt += 1
        except Exception as e:
            print(f"Error checking transaction status: {e}")
            await asyncio.sleep(1)
            attempt += 1
    
    print(f"Transaction not finalized after {max_attempts} attempts.")
    return False

async def send_transaction_with_priority_fee(sdk, solana_client, sender, receiver, amount, jito_tip_amount, priority_fee, compute_unit_limit=100_000):
    try:
        recent_blockhash = await solana_client.get_latest_blockhash()
        
        # Transfer to the known receiver
        transfer_ix = transfer(TransferParams(from_pubkey=sender.pubkey(), to_pubkey=receiver, lamports=amount))
        
        # Jito tip transfer
        jito_tip_account = Pubkey.from_string(sdk.get_random_tip_account())
        jito_tip_ix = transfer(TransferParams(from_pubkey=sender.pubkey(), to_pubkey=jito_tip_account, lamports=jito_tip_amount))
        
        # Priority Fee
        priority_fee_ix = set_compute_unit_price(priority_fee)

        transaction = Transaction.new_signed_with_payer(
            [priority_fee_ix, transfer_ix, jito_tip_ix],
            sender.pubkey(),
            [sender],
            recent_blockhash.value.blockhash
        )

        serialized_transaction = base64.b64encode(bytes(transaction)).decode('ascii')
        
        print(f"Sending transaction with priority fee: {priority_fee} micro-lamports per compute unit")
        print(f"Transfer amount: {amount} lamports to {receiver}")
        print(f"Jito tip amount: {jito_tip_amount} lamports to {jito_tip_account}")
        print(f"Serialized transaction: {serialized_transaction}")
        
        response = sdk.send_txn(params=serialized_transaction, bundleOnly=False)

        if response['success']:
            print(f"Full Jito SDK response: {response}")
            signature_str = response['data']['result']
            print(f"Transaction signature: {signature_str}")

            finalized = await check_transaction_status(solana_client, signature_str)
            
            if finalized:
                print("Transaction has been finalized.")
                solscan_url = f"https://solscan.io/tx/{signature_str}"
                print(f"View transaction details on Solscan: {solscan_url}")
            else:
                print("Transaction was not finalized within the expected time.")
            
            return signature_str
        else:
            print(f"Error sending transaction: {response['error']}")
            return None

    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return None

### BUNDLE ###
async def confirm_landed_bundle(sdk: JitoJsonRpcSDK, bundle_id: str, max_attempts: int = 60, delay: float = 2.0):
    for attempt in range(max_attempts):
        response = sdk.get_bundle_statuses([bundle_id])
        
        if not response['success']:
            print(f"Error confirming bundle status: {response.get('error', 'Unknown error')}")
            await asyncio.sleep(delay)
        
        print(f"Confirmation attempt {attempt + 1}/{max_attempts}:")
        print(json.dumps(response, indent=2))
        
        if 'result' not in response['data']:
            print(f"Unexpected response structure. 'result' not found in response data.")
            await asyncio.sleep(delay)
        
        result = response['data']['result']
        if 'value' not in result or not result['value']:
            print(f"Bundle {bundle_id} not found in confirmation response")
            await asyncio.sleep(delay)
        
        bundle_status = result['value'][0]
        if bundle_status['bundle_id'] != bundle_id:
            print(f"Unexpected bundle ID in response: {bundle_status['bundle_id']}")
            await asyncio.sleep(delay)
        
        status = bundle_status.get('confirmation_status')
        
        if status == 'finalized':
            print(f"Bundle {bundle_id} has been finalized on-chain!")
            # Extract transaction ID and construct Solscan link
            if 'transactions' in bundle_status and bundle_status['transactions']:
                tx_id = bundle_status['transactions'][0]
                solscan_link = f"https://solscan.io/tx/{tx_id}"
                print(f"Transaction details: {solscan_link}")
            else:
                print("Transaction ID not found in the response.")
            return 'Finalized'
        elif status == 'confirmed':
            print(f"Bundle {bundle_id} is confirmed but not yet finalized. Checking again...")
        elif status == 'processed':
            print(f"Bundle {bundle_id} is processed but not yet confirmed. Checking again...")
        else:
            print(f"Unexpected status '{status}' during confirmation for bundle {bundle_id}")
        
        # Check for errors
        err = bundle_status.get('err', {}).get('Ok')
        if err is not None:
            print(f"Error in bundle {bundle_id}: {err}")
            return 'Failed'
        
        await asyncio.sleep(delay)
    
    print(f"Max confirmation attempts reached. Unable to confirm finalization of bundle {bundle_id}")
    return 'Landed'

async def check_bundle_status(sdk: JitoJsonRpcSDK, bundle_id: str, max_attempts: int = 30, delay: float = 2.0):
    for attempt in range(max_attempts):
        response = sdk.get_inflight_bundle_statuses([bundle_id])
        
        if not response['success']:
            print(f"Error checking bundle status: {response.get('error', 'Unknown error')}")
            await asyncio.sleep(delay)
            continue
        
        print(f"Raw response (Attempt {attempt + 1}/{max_attempts}):")
        print(json.dumps(response, indent=2))
        
        if 'result' not in response['data']:
            print(f"Unexpected response structure. 'result' not found in response data.")
            await asyncio.sleep(delay)
            continue
        
        result = response['data']['result']
        if 'value' not in result or not result['value']:
            print(f"Bundle {bundle_id} not found in response")
            await asyncio.sleep(delay)
            continue
        
        bundle_status = result['value'][0]
        status = bundle_status.get('status')
        print(f"Attempt {attempt + 1}/{max_attempts}: Bundle status - {status}")
        
        if status == 'Landed':
            print(f"Bundle {bundle_id} has landed on-chain! Performing additional confirmation...")
            final_status = await confirm_landed_bundle(sdk, bundle_id)
            return final_status
        elif status == 'Failed':
            print(f"Bundle {bundle_id} has failed.")
            return status
        elif status == 'Invalid':
            if attempt < 5:  # Check a few more times before giving up on Invalid(usually on start)
                print(f"Bundle {bundle_id} is currently invalid. Checking again...")
            else:
                print(f"Bundle {bundle_id} is invalid (not in system or outside 5-minute window).")
                return status
        elif status == 'Pending':
            print(f"Bundle {bundle_id} is still pending. Checking again in {delay} seconds...")
        else:
            print(f"Unknown status '{status}' for bundle {bundle_id}")
        
        await asyncio.sleep(delay)
    
    print(f"Max attempts reached. Final status of bundle {bundle_id}: {status}")
    return status

async def confirm_bundle(jito_client, bundle_id, timeout_seconds=60):
    start_time = asyncio.get_event_loop().time()
    
    while asyncio.get_event_loop().time() - start_time < timeout_seconds:
        try:
            status = jito_client.get_bundle_statuses([[bundle_id]])
            print('Bundle status:', status)
            
            if status['success'] and bundle_id in status['data']['result']:
                bundle_status = status['data']['result'][bundle_id]
                if bundle_status['status'] == 'finalized':
                    print('Bundle has been finalized on the blockchain.')
                    return bundle_status
                elif bundle_status['status'] == 'confirmed':
                    print('Bundle has been confirmed but not yet finalized.')
                elif bundle_status['status'] == 'processed':
                    print('Bundle has been processed but not yet confirmed.')
                elif bundle_status['status'] == 'failed':
                    raise Exception(f"Bundle failed: {bundle_status.get('error')}")
                else:
                    print(f"Unknown bundle status: {bundle_status['status']}")
        except Exception as error:
            print('Error checking bundle status:', str(error))

        # Wait for a short time before checking again
        await asyncio.sleep(2)
    
    print(f"Bundle {bundle_id} has not finalized within {timeout_seconds}s, but it may still be in progress.")
    return jito_client.get_bundle_statuses([bundle_id])


async def basic_bundle():
    # Initialize connection to Solana testnet
    solana_client = AsyncClient(appconfig.RPC_URL)

    wallet_keypair = Keypair.from_base58_string(appconfig.PRIVKEY)
    # Initialize JitoJsonRpcSDK
    jito_client = JitoJsonRpcSDK(url="https://mainnet.block-engine.jito.wtf/api/v1")

    #Example using UUID
    #jito_client = JitoJsonRpcSDK(url="https://mainnet.block-engine.jito.wtf/api/v1", uuid_var="YOUR_UUID" )  

    # Set up transaction parameters
    receiver = Pubkey.from_string("EKhLZ5Kcwx6JxePx89sVBknJsyuWmLWC3pPRga2jpump")
    jito_tip_account = Pubkey.from_string(jito_client.get_random_tip_account())
    jito_tip_amount = 1000  # lamports
    transfer_amount = 1000  # lamports

    # Memo program ID
    memo_program_id = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")

    # Create instructions
    transfer_ix = transfer(TransferParams(
        from_pubkey=wallet_keypair.pubkey(),
        to_pubkey=receiver,
        lamports=transfer_amount
    ))

    tip_ix = transfer(TransferParams(
        from_pubkey=wallet_keypair.pubkey(),
        to_pubkey=jito_tip_account,
        lamports=jito_tip_amount
    ))

    memo_ix = Instruction(
        program_id=memo_program_id,
        accounts=[],
        data=bytes("Let's Jito!", "utf-8")
    )

    # Get recent blockhash
    recent_blockhash = await solana_client.get_latest_blockhash()

    # Create the transaction
    message = Message.new_with_blockhash(
        [transfer_ix, tip_ix, memo_ix],
        wallet_keypair.pubkey(),
        recent_blockhash.value.blockhash
    )
    transaction = Transaction.new_unsigned(message)

    # Sign the transaction
    transaction.sign([wallet_keypair], recent_blockhash.value.blockhash)

    # Serialize and base58 encode the entire signed transaction
    serialized_transaction = base64.b64encode(bytes(transaction)).decode('ascii')

    try:
            # Prepare the bundle request
            bundle_request = [serialized_transaction]
            print(f"Sending bundle request: {json.dumps(bundle_request, indent=2)}")

            # Send the bundle using sendBundle method
            result = jito_client.send_bundle(bundle_request)
            print('Raw API response:', json.dumps(result, indent=2))

            if result['success']:
                bundle_id = result['data']['result']
                print(f"Bundle sent successfully. Bundle ID: {bundle_id}")
                
                # Check the status of the bundle
                final_status = await check_bundle_status(jito_client, bundle_id, max_attempts=30, delay=2.0)
                
                if final_status == 'Finalized':
                    print("Bundle has been confirmed and finalized on-chain.")
                elif final_status == 'Landed':
                    print("Bundle has landed on-chain but could not be confirmed as finalized within the timeout period.")
                else:
                    print(f"Bundle did not land on-chain. Final status: {final_status}")
            else:
                print(f"Failed to send bundle: {result.get('error', 'Unknown error')}")

    except Exception as error:
        print('Error sending or confirming bundle:', str(error))

    # Close the Solana client session
    await solana_client.close()


async def basic_txn():
    solana_client = AsyncClient("https://api.mainnet-beta.solana.com")
    sdk = JitoJsonRpcSDK(url=appconfig.RPC_URL)

    sender = Keypair.from_bytes(bytes(appconfig.PRIVKEY))
    receiver = Pubkey.from_string()

    print(f"Sender public key: {sender.pubkey()}")
    print(f"Receiver public key: {receiver}")

    priority_fee = 1000  # Lamport for priority fee
    amount = 1000  # Lamports to transfer to receiver
    jito_tip_amount = 1000  # Lamports for Jito tip

    signature = await send_transaction_with_priority_fee(sdk, solana_client, sender, receiver, amount, jito_tip_amount, priority_fee)
    
    if signature:
        print(f"Transaction process completed. Signature: {signature}")

    await solana_client.close()

asyncio.run(basic_bundle())
