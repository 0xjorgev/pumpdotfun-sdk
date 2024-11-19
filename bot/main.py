import asyncio
import logging
from module.pump import Pump, TradeRoadmap


async def main():
    pump = Pump()

    tasks = [
        pump.subscribe(steps=TradeRoadmap.test)
    ]

    await asyncio.gather(*tasks)
    logging.log("Stoping program")


if __name__ == "__main__":
    asyncio.run(main())
