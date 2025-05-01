# Standard libraries
from logging import Logger
from typing import (
    Dict,
    List
)
import asyncio
import os
import tempfile

# 3rd party libraries
from telegram import (
    Chat,
    Update,
    _message,
    File
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CallbackContext
)

# Internal libraries
from lib.chatgpt import (
    GPT,
    Language
)
from lib.x import X


debug = False


async def get_bot_channels(
    application: Application,
    logger: Logger
) -> List:
    bot = application.bot

    try:
        # Initialize the bot
        await bot.initialize()

        # Retrieve bot's updates
        updates = await bot.get_updates()

        channels = []
        members = [
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER
        ]

        # Iterate over updates to find chat IDs
        for update in updates:
            chat = update.effective_chat

            if chat and chat.type == Chat.CHANNEL:
                # Get detailed chat info
                chat_info = await bot.get_chat(chat.id)

                # Check if the bot is a member of the channel
                member = await bot.get_chat_member(chat.id, bot.id)
                if member.status in members:
                    channels.append(
                        {"name": chat_info.title, "id": chat_info.id}
                    )

    except Exception as e:
        logger.error(f"Error fetching updates: {e}")
        return []

    return channels


async def delivery_msg(
    context: CallbackContext,
    delay: int,
    logger: Logger,
    message: _message,
    source_language: Language,
    target_language: Language,
    target_channel_id
):
    try:
        # Wait for x seconds
        await asyncio.sleep(delay)

        if message.text:
            msg = message.text
            # Check if we need a translation
            if source_language != target_language:
                gpt = GPT()
                translation = gpt.translate_text(
                    origin_language=source_language,
                    target_languege=target_language,
                    text=msg
                )
                msg = translation

            response = await context.bot.send_message(
                chat_id=target_channel_id,
                text=msg
            )
            print("response: {}".format(response))
        elif message.photo:
            msg = message.caption
            # Check if we need a translation
            if source_language != target_language:
                gpt = GPT()
                translation = gpt.translate_text(
                    origin_language=source_language,
                    target_languege=target_language,
                    text=msg
                )
                msg = translation

            await context.bot.send_photo(
                chat_id=target_channel_id,
                photo=message.photo[-1].file_id,
                caption=msg
            )

            photo = message.photo[-1]
            file_id = photo.file_id

            # Retrieve the file
            telegram_file: File = await context.bot.get_file(file_id)

            # Create a temporary file to save the photo
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                await telegram_file.download_to_drive(custom_path=tmp_file.name)
                image_path = tmp_file.name
                # Post the photo to X
                x = X()
                x.post_tweet(message=msg, image_path=image_path)

                # Clean up the temporary file
                os.remove(image_path)

        elif message.document:
            await context.bot.send_document(
                chat_id=target_channel_id,
                document=message.document.file_id,
                caption=message.caption
            )
        elif message.video:
            await context.bot.send_video(
                chat_id=target_channel_id,
                video=message.video.file_id,
                caption=message.caption
            )
        elif message.audio:
            await context.bot.send_audio(
                chat_id=target_channel_id,
                audio=message.audio.file_id,
                caption=message.caption
            )
        elif message.voice:
            await context.bot.send_voice(
                chat_id=target_channel_id,
                voice=message.voice.file_id,
                caption=message.caption
            )
        elif message.sticker:
            await context.bot.send_sticker(
                chat_id=target_channel_id,
                sticker=message.sticker.file_id
            )
        elif message.animation:
            await context.bot.send_animation(
                chat_id=target_channel_id,
                animation=message.animation.file_id,
                caption=message.caption
            )
        elif message.video_note:
            await context.bot.send_video_note(
                chat_id=target_channel_id,
                video_note=message.video_note.file_id
            )
        elif message.contact:
            await context.bot.send_contact(
                chat_id=target_channel_id,
                contact=message.contact
            )
        elif message.location:
            await context.bot.send_location(
                chat_id=target_channel_id,
                latitude=message.location.latitude,
                longitude=message.location.longitude
            )
        elif message.poll:
            await context.bot.send_poll(
                chat_id=target_channel_id,
                question=message.poll.question,
                options=[o.text for o in message.poll.options]
            )
        elif message.dice:
            await context.bot.send_dice(
                chat_id=target_channel_id,
                emoji=message.dice.emoji
            )
        # Add more types if needed
        else:
            logger.info("Unsupported message type.")

    except Exception as e:
        logger.error(f"Failed to forward message: {e}")


async def forward_message(
    update: Update,
    context: CallbackContext,
    logger: Logger,
    channel: Dict,
    delay: int
):
    message = update.channel_post
    deleted_message = update.deleted_business_messages
    source_chat_id = message.chat_id
    logger.info("message: {}".format(message.text))
    logger.info("deleted_message: {}".format(deleted_message))

    if channel['source'] != source_chat_id:
        logger.warning(f"Source channel {source_chat_id} not configured.")
        return

    source_language = channel["source_language"]

    # Store tasks to be awaited at the end
    tasks = []

    for target_channel in channel["target_channels"]:
        if not target_channel["enabled"]:
            logger.info("Channel {} is desabled.".format(
                target_channel["target"]
            ))
            continue

        delay = delay * target_channel["with_delay"]  # it will be 0 if false
        target_channel_id = target_channel["target"]
        target_language = target_channel["target_language"]

        task = asyncio.create_task(
            # Forward the message to the target channel
            delivery_msg(
                context=context,
                delay=delay,
                logger=logger,
                message=message,
                source_language=source_language,
                target_language=target_language,
                target_channel_id=target_channel_id
            )
        )

        tasks.append(task)

    # Wait for all tasks to complete
    await asyncio.gather(*tasks)
