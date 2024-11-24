import asyncio
import logging
from module.pump import Pump, TradeRoadmap
from lib.utils import Trader

async def main():
    pump = Pump(
        executor_name="sniper1",
        trader_type=Trader.sniper
    )

    tasks = [
        pump.subscribe(steps=TradeRoadmap.sniper_1)
    ]

    await asyncio.gather(*tasks)
    logging.log("Stoping program")


if __name__ == "__main__":
    asyncio.run(main())
