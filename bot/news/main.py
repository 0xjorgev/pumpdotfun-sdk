from functools import partial

import asyncio
import logging

from telegram.ext import (
    Application,
    filters,
    MessageHandler
)

from config import appconfig
from libs.chatgpt import (
    Language
)

from libs.utils import (
    forward_message,
    get_bot_channels
)

environment = "dev"

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Telegram Bot Token
BOT_TOKEN = appconfig.TELEGRAM_BOT_TOKEN
BOT_DEV_TOKEN = appconfig.TELEGRAM_BOT_DEV_TOKEN

if environment == "dev":
    BOT_TOKEN = BOT_DEV_TOKEN

# List of Telegram channels
CHANNELS = [
    {
        "source": -1002199109243,
        "source_language": Language.Spanish,
        "name": "UMOTC - Source",
        "tag": "TEST CHANNEL",
        "env": "dev",
        "target_channels": [
            {
                "target": -1002247367774,
                "target_language": Language.English,
                "with_delay": False,
                "name": "GhostFunds.xyz - Crypto News",
                "enabled": True
            }
        ]
    },
    # {
    #     "source": -1001615771467,
    #     "source_language": Language.Spanish,
    #     "name": "OTC Financial Markets - Último Minuto",
    #     "tag": "PRODUCTION CHANNEL",
    #     "env": "prod",
    #     "target_channels": [
    #         {
    #             "target": -1002225333317,
    #             "target_language": Language.English,
    #             "with_delay": False,
    #             "name": "OTC Financial Markets - Last Minute",
    #             "enabled": True
    #         },
    #     ]
    # },
    # {
    #     "source": -1001791935140,
    #     "source_language": Language.Spanish,
    #     "name": "OTC Financial Markets - Pivot points",
    #     "tag": "PRODUCTION CHANNEL",
    #     "env": "prod",
    #     "target_channels": [
    #         {
    #             "target": -1002196867876,
    #             "target_language": Language.English,
    #             "with_delay": False,
    #             "name": "OTC Financial Markets - Pivot points - English",
    #             "enabled": True
    #         },
    #     ]
    # },
    # {
    #     "source": -1001682562569,
    #     "source_language": Language.Spanish,
    #     "name": "OTC Financial Markets - Forex y Materias primas",
    #     "tag": "PRODUCTION CHANNEL",
    #     "env": "prod",
    #     "target_channels": [
    #         {
    #             "target": -1002175825671,
    #             "target_language": Language.English,
    #             "with_delay": False,
    #             "name": "OTC Financial Markets - Forex and Commodities",
    #             "enabled": True
    #         },
    #     ]
    # },
    {
        "source": -1001755306119,
        "source_language": Language.Spanish,
        "name": "OTC Financial Markets - Crypto",
        "tag": "PRODUCTION CHANNEL",
        "env": "prod",
        "target_channels": [
            {
                "target": -1002247367774,
                "target_language": Language.English,
                "with_delay": False,
                "name": "GhostFunds.xyz - Crypto News",
                "enabled": True
            },
        ]
    },
]

# Delay in seconds (15 minutes)
DELAY_SECONDS = 3 * 1


async def list_chanels():
    application = Application.builder().token(BOT_TOKEN).build()
    channels = await get_bot_channels(
        application=application,
        logger=logger
    )
    print(channels)


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    channel_list = [ch for ch in CHANNELS if ch["env"] == environment]

    for channel in channel_list:
        forward_message_with_parameters = partial(
            forward_message,
            logger=logger,
            channel=channel,
            delay=DELAY_SECONDS
        )

        application.add_handler(
            MessageHandler(
                filters.Chat(channel['source']),
                forward_message_with_parameters
            )
        )

    # application.initialize()
    # application.start()

    # Start polling for updates
    application.run_polling()

    print("Done")


if __name__ == '__main__':
    # asyncio.run(list_chanels())
    asyncio.run(main())
