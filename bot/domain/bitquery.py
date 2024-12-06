import asyncio
import websockets
import json

# Define the GraphQL query
graphql_query = """
subscription MyQuery {
  Solana {
    DEXTradeByTokens(
      where: {
        Trade: {
          PriceInUSD: {gt: 0.000015, lt: 0.000016}
          Dex: {ProgramAddress: {is: "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"}}
          Side: {
            Currency: {MintAddress: {is: "11111111111111111111111111111111"}}
            AmountInUSD: {ge: "0.007200000"}
          }
        }
        Transaction: {Result: {Success: true}}
        Block: {Time: {since: "2024-12-05T23:30:00Z"}}
        any: {Trade: {}}
      }
      limit: {count: 1}
    ) {
      Block {
        Time
      }
      Trade {
        Currency {
          Name
          Symbol
          Decimals
          MintAddress
        }
        Price
        PriceInUSD
        Dex {
          ProtocolName
          ProtocolFamily
          ProgramAddress
        }
        Side {
          Currency {
            MintAddress
            Name
            Symbol
          }
        }
      }
    }
  }
}
"""

# Define the WebSocket server URL
GRAPHQL_ENDPOINT = "wss://graphql.bitquery.io"  # Replace with the actual endpoint

async def run_query():
    """ TO BE TESTED - UNDER DEVELOPMENT """
    async with websockets.connect(
        GRAPHQL_ENDPOINT,
        extra_headers={"Authorization": "Bearer BQYVFhPCtWWwZVxA6QB8PuvKj0dc5HR5"}
    ) as websocket:
        # Send the subscription request
        payload = {
            "type": "start",
            "id": "1",  # Unique identifier for the query
            "payload": {
                "query": graphql_query
            }
        }
        await websocket.send(json.dumps(payload))
        print("Subscription initiated...")

        # Listen for responses
        try:
            while True:
                response = await websocket.recv()
                data = json.loads(response)
                print("Received response:", json.dumps(data, indent=2))
        except websockets.ConnectionClosed as e:
            print(f"WebSocket closed: {e}")

# Run the async function
asyncio.run(run_query())
