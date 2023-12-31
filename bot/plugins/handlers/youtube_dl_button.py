import asyncio
from contextlib import suppress
import json
import logging
import os
import shutil
import time
from datetime import datetime

from hachoir.metadata import extractMetadata
from hachoir.parser import createParser

from PIL import Image
from pyrogram import enums
from pyrogram.types import InputMediaPhoto

from bot.config import Config
from bot.config import Script as Translation
from bot.plugins.handlers.ffmpeg_helpers import generate_screen_shots
from bot.utils import humanbytes, progress_for_pyrogram


async def youtube_dl_call_back(bot, update):
    cb_data = update.data
    # youtube_dl extractors
    tg_send_type, youtube_dl_format, youtube_dl_ext = cb_data.split("|")
    thumb_image_path = f"{Config.DOWNLOAD_LOCATION}/{str(update.from_user.id)}.jpg"
    save_ytdl_json_path = f"{Config.DOWNLOAD_LOCATION}/{str(update.from_user.id)}.json"
    try:
        with open(save_ytdl_json_path, "r", encoding="utf8") as f:
            response_json = json.load(f)
    except FileNotFoundError as e:
        await bot.delete_messages(
            chat_id=update.message.chat.id,
            message_ids=update.message.id,
            revoke=True,
        )
        return False
    youtube_dl_url = update.message.reply_to_message.text
    custom_file_name = (
        str(response_json.get("title")) + "_" + youtube_dl_format + "." + youtube_dl_ext
    )
    youtube_dl_username = None
    youtube_dl_password = None
    if "|" in youtube_dl_url:
        url_parts = youtube_dl_url.split("|")
        if len(url_parts) == 2:
            youtube_dl_url = url_parts[0]
            custom_file_name = url_parts[1]
        elif len(url_parts) == 4:
            youtube_dl_url = url_parts[0]
            custom_file_name = url_parts[1]
            youtube_dl_username = url_parts[2]
            youtube_dl_password = url_parts[3]
        else:
            for entity in update.message.reply_to_message.entities:
                if entity.type == enums.MessageEntityType.TEXT_LINK:
                    youtube_dl_url = enums.MessageEntityType.URL
                elif entity.type == "url":
                    o = entity.offset
                    l = entity.length
                    youtube_dl_url = youtube_dl_url[o : o + l]
        if youtube_dl_url is not None:
            youtube_dl_url = youtube_dl_url.strip()
        if custom_file_name is not None:
            custom_file_name = custom_file_name.strip()
        # https://stackoverflow.com/a/761825/4723940
        if youtube_dl_username is not None:
            youtube_dl_username = youtube_dl_username.strip()
        if youtube_dl_password is not None:
            youtube_dl_password = youtube_dl_password.strip()
        logging.info(youtube_dl_url)
        logging.info(custom_file_name)
    else:
        for entity in update.message.reply_to_message.entities:
            if entity.type == enums.MessageEntityType.TEXT_LINK:
                youtube_dl_url = entity.url
            elif entity.type == enums.MessageEntityType.URL:
                o = entity.offset
                l = entity.length
                youtube_dl_url = youtube_dl_url[o : o + l]
    await bot.edit_message_text(
        text=Translation.DOWNLOAD_START,
        chat_id=update.message.chat.id,
        message_id=update.message.id,
    )
    user = await bot.get_me()
    mention = user.mention
    description = Translation.CUSTOM_CAPTION_UL_FILE.format(mention)
    if "fulltitle" in response_json:
        description = response_json["fulltitle"][:1021]
        # escape Markdown and special characters
    tmp_directory_for_each_user = (
        f"{Config.DOWNLOAD_LOCATION}/{str(update.from_user.id)}"
    )
    if not os.path.isdir(tmp_directory_for_each_user):
        os.makedirs(tmp_directory_for_each_user)
    download_directory = f"{tmp_directory_for_each_user}/{custom_file_name}"
    command_to_exec = []
    if tg_send_type == "audio":
        command_to_exec = [
            "yt-dlp",
            "-c",
            "--max-filesize",
            str(Config.TG_MAX_FILE_SIZE),
            "--prefer-ffmpeg",
            "--extract-audio",
            "--audio-format",
            youtube_dl_ext,
            "--audio-quality",
            youtube_dl_format,
            youtube_dl_url,
            "-o",
            download_directory,
        ]
    else:
        minus_f_format = youtube_dl_format
        if "youtu" in youtube_dl_url:
            minus_f_format = f"{youtube_dl_format}+bestaudio"
        command_to_exec = [
            "yt-dlp",
            "-c",
            "--max-filesize",
            str(Config.TG_MAX_FILE_SIZE),
            "--embed-subs",
            "-f",
            minus_f_format,
            "--hls-prefer-ffmpeg",
            youtube_dl_url,
            "-o",
            download_directory,
        ]

    if youtube_dl_username is not None:
        command_to_exec.append("--username")
        command_to_exec.append(youtube_dl_username)
    if youtube_dl_password is not None:
        command_to_exec.append("--password")
        command_to_exec.append(youtube_dl_password)
    command_to_exec.append("--no-warnings")
    # command_to_exec.append("--quiet")
    logging.info(command_to_exec)
    start = datetime.now()
    process = await asyncio.create_subprocess_exec(
        *command_to_exec,
        # stdout must a pipe to be accessible as process.stdout
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Wait for the subprocess to finish
    stdout, stderr = await process.communicate()
    e_response = stderr.decode().strip()
    t_response = stdout.decode().strip()
    logging.info(e_response)
    logging.info(t_response)
    ad_string_to_replace = "please report this issue on https://yt-dl.org/bug . Make sure you are using the latest version; see  https://yt-dl.org/update  on how to update. Be sure to call youtube-dl with the --verbose flag and include its complete output."
    if e_response and ad_string_to_replace in e_response:
        error_message = e_response.replace(ad_string_to_replace, "")
        await bot.edit_message_text(
            chat_id=update.message.chat.id,
            message_id=update.message.id,
            text=error_message,
        )
        return False
    if t_response:
        # logging.info(t_response)
        os.remove(save_ytdl_json_path)
        end_one = datetime.now()
        time_taken_for_download = (end_one - start).seconds
        file_size = Config.TG_MAX_FILE_SIZE + 1
        try_ext = [
            "mkv",
            "mp4",
            "webm",
        ]
        og_download_directory = download_directory
        try:
            file_size = os.stat(og_download_directory).st_size
        except FileNotFoundError as exc:
            for ext in try_ext:
                try_phrase = f"f{youtube_dl_format}.{ext}"
                try:
                    download_directory = (
                        f"{os.path.splitext(og_download_directory)[0]}.{ext}"
                    )
                    file_size = os.stat(download_directory).st_size
                    break
                except FileNotFoundError as exc:
                    with suppress(FileNotFoundError):
                        download_directory = (
                            f"{os.path.splitext(og_download_directory)[0]}.{try_phrase}"
                        )
                        file_size = os.stat(download_directory).st_size
                        break

        if file_size > Config.TG_MAX_FILE_SIZE:
            await bot.edit_message_text(
                chat_id=update.message.chat.id,
                message_id=update.message.id,
                text=Translation.RCHD_TG_API_LIMIT.format(
                    time_taken_for_download, humanbytes(file_size)
                ),
            )
            return False

        is_w_f = False

        await bot.edit_message_text(
            text=Translation.UPLOAD_START,
            chat_id=update.message.chat.id,
            message_id=update.message.id,
        )
        # get the correct width, height, and duration for videos greater than 10MB
        # ref: message from @BotSupport
        width = 0
        height = 0
        duration = 0
        if tg_send_type != "file":
            metadata = extractMetadata(createParser(download_directory))
            if metadata is not None and metadata.has("duration"):
                duration = metadata.get("duration").seconds
        # get the correct width, height, and duration for videos greater than 10MB
        if os.path.exists(thumb_image_path):
            width = 0
            height = 0
            metadata = extractMetadata(createParser(thumb_image_path))
            if metadata.has("width"):
                width = metadata.get("width")
            if metadata.has("height"):
                height = metadata.get("height")
            if tg_send_type == "vm":
                height = width
            # resize image
            # ref: https://t.me/PyrogramChat/44663
            # https://stackoverflow.com/a/21669827/4723940
            Image.open(thumb_image_path).convert("RGB").save(thumb_image_path)
            img = Image.open(thumb_image_path)
            # https://stackoverflow.com/a/37631799/4723940
            # img.thumbnail((90, 90))
            if tg_send_type == "file":
                img.resize((320, height))
            else:
                img.resize((90, height))
            img.save(thumb_image_path, "JPEG")
            # https://pillow.readthedocs.io/en/3.1.x/reference/Image.html#create-thumbnails

        else:
            thumb_image_path = None
        start_time = time.time()
        # try to upload file
        if tg_send_type == "audio":
            await bot.send_audio(
                chat_id=update.message.chat.id,
                audio=download_directory,
                caption=description,
                parse_mode=enums.ParseMode.HTML,
                duration=duration,
                # performer=response_json["uploader"],
                # title=response_json["title"],
                # reply_markup=reply_markup,
                thumb=thumb_image_path,
                reply_to_message_id=update.message.reply_to_message.id,
                progress=progress_for_pyrogram,
                progress_args=(
                    Translation.UPLOAD_START,
                    update.message,
                    start_time,
                ),
            )
        elif tg_send_type == "file":
            await bot.send_document(
                chat_id=update.message.chat.id,
                document=download_directory,
                thumb=thumb_image_path,
                caption=description,
                parse_mode=enums.ParseMode.HTML,
                # reply_markup=reply_markup,
                reply_to_message_id=update.message.reply_to_message.id,
                progress=progress_for_pyrogram,
                progress_args=(
                    Translation.UPLOAD_START,
                    update.message,
                    start_time,
                ),
            )
        elif tg_send_type == "vm":
            await bot.send_video_note(
                chat_id=update.message.chat.id,
                video_note=download_directory,
                duration=duration,
                length=width,
                thumb=thumb_image_path,
                reply_to_message_id=update.message.reply_to_message.id,
                progress=progress_for_pyrogram,
                progress_args=(
                    Translation.UPLOAD_START,
                    update.message,
                    start_time,
                ),
            )
        elif tg_send_type == "video":
            await bot.send_video(
                chat_id=update.message.chat.id,
                video=download_directory,
                caption=description,
                parse_mode=enums.ParseMode.HTML,
                duration=duration,
                width=width,
                height=height,
                supports_streaming=True,
                # reply_markup=reply_markup,
                thumb=thumb_image_path,
                reply_to_message_id=update.message.reply_to_message.id,
                progress=progress_for_pyrogram,
                progress_args=(
                    Translation.UPLOAD_START,
                    update.message,
                    start_time,
                ),
            )
        else:
            logging.info("Did this happen? :\\")
        end_two = datetime.now()
        time_taken_for_upload = (end_two - end_one).seconds

        with suppress(Exception):
            shutil.rmtree(tmp_directory_for_each_user)
            os.remove(thumb_image_path)
        await bot.edit_message_text(
            text=Translation.AFTER_SUCCESSFUL_UPLOAD_MSG_WITH_TS.format(
                time_taken_for_download, time_taken_for_upload
            ),
            chat_id=update.message.chat.id,
            message_id=update.message.id,
            disable_web_page_preview=True,
        )
