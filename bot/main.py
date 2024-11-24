import asyncio
import logging
from module.pump import Pump, TradeRoadmap


async def main():
    pump = Pump(sniper_name="sniper1")

    tasks = [
        pump.subscribe(steps=TradeRoadmap.sniper_1)
    ]

    await asyncio.gather(*tasks)
    logging.log("Stoping program")


if __name__ == "__main__":
    asyncio.run(main())
