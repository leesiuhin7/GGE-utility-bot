import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import threading
from flask import Flask, Response
import logging

from server_comm import AttackListener, StormFort, Info, WSComm
from _channel_ids import get_channel_ids


logging.basicConfig(
    level=int(os.environ.get("LOGGING_LEVEL", logging.INFO))
)

TOKEN: str = os.environ.get("DISCORD_TOKEN", "")

SERVER_URL: str = os.environ.get("SERVER_URL", "")
SERVER_WS_URL: str = os.environ.get("SERVER_WS_URL", "")

PORT: int = int(os.environ.get("PORT", 10000))
channel_ids = get_channel_ids()

message_queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()

attack_listener = AttackListener(message_queue)
storm_fort = StormFort()
ws_comm = WSComm(SERVER_WS_URL)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


async def send_message() -> None:
    message, index = await message_queue.get()
    channel = bot.get_channel(channel_ids[index][0])

    if not hasattr(channel, "send"):
        return

    await channel.send(message)  # type: ignore


async def background_msg_loop() -> None:
    while not bot.is_closed():
        await send_message()


@bot.tree.command(
    name="storm_fort",
    description="Find storm forts on the map based on criterias"
)
@app_commands.describe(
    center=(
        "The center of search, "
        "format: {x position}:{y position}"
    ),
    criterias=(
        "Select criterias seperated by spaces, "
        "options: [lvl] 40, 50, 60, 70, 80"
    ),
    search_dist=(
        "Maximum horizontal / vertical distance of search, "
        "max value: 500"
    )
)
async def find_storm_forts(
    interaction: discord.Interaction,
    center: str,
    criterias: str = "",
    search_dist: int = 50
) -> None:

    # Get index from channel id + check authorization
    channel_id = interaction.channel_id

    client_index = -1
    for i, valid_ids in enumerate(channel_ids):
        if channel_id in valid_ids:
            client_index = i
            break

    if client_index == -1:
        await interaction.response.send_message(
            "This channel is not authorized.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    criteria_list = criterias.split(" ")

    searcher = await storm_fort.search(
        client_index,
        center=center,
        dist=min(search_dist, 500),
        criterias=criteria_list
    )

    if searcher is None:
        await interaction.followup.send(
            "Invalid input data.",
            ephemeral=True
        )
        return

    no_result = True

    async for info_text_list in searcher:
        for message in info_text_list:
            no_result = False
            await interaction.followup.send(
                message,
                ephemeral=True
            )

    if no_result:
        await interaction.followup.send("No results were found.")
        return
    else:
        await interaction.followup.send("Search completed.")


@bot.event
async def on_ready() -> None:
    logging.info(f"{bot.user} is online!")

    await bot.tree.sync()

    asyncio.create_task(background_msg_loop())


def start_flask_server() -> None:
    app = Flask(__name__)

    app.add_url_rule(
        "/",
        endpoint="respond",
        view_func=lambda: Response(status=200)
    )
    server_thread = threading.Thread(
        target=app.run,
        kwargs={"host": "0.0.0.0", "port": PORT}
    )
    server_thread.start()


async def main() -> None:
    await Info.bind(SERVER_URL, len(channel_ids))
    Info.ws_bind(ws_comm)

    attack_listener.update()
    storm_fort.update()

    await attack_listener.start()
    await ws_comm.start()

    start_flask_server()

    async with bot:
        await bot.start(TOKEN)

    await attack_listener.cancel()

    while True:
        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
