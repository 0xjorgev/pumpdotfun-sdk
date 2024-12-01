import asyncio
import logging
from module.pump import Pump, TradeRoadmap
from bot.libs.utils import Trader

async def main():
    pump = Pump(
        executor_name="sniper1",
        trader_type=Trader.sniper
    )

    scanner = Pump(
        executor_name="scanner",
        trader_type=Trader.scanner
    )

    tasks = [
        #pump.subscribe(steps=TradeRoadmap.sniper_1),
        scanner.subscribe(steps=TradeRoadmap.scanner)
    ]

    await asyncio.gather(*tasks)
    print("Stoping program")


if __name__ == "__main__":
    asyncio.run(main())
