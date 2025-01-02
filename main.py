import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import threading
from flask import Flask, Response

from server_comm import AttackListener, StormFort, Info
from _channel_ids import get_channel_ids



TOKEN: str = os.environ.get("DISCORD_TOKEN", "")
SERVER_URL: str = os.environ.get("SERVER_URL", "")
PORT: int = int(os.environ.get("PORT", 10000))
channel_ids = get_channel_ids()

message_queue: list[tuple[str, int]] = []

attack_listener = AttackListener(message_queue)
storm_fort = StormFort()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

async def send_message() -> None:
    message, index = message_queue.pop(0)
    channel = bot.get_channel(channel_ids[index][0])

    if not hasattr(channel, "send"):
        return
    
    await channel.send(message) # type: ignore


async def background_msg_loop() -> None:
    while not bot.is_closed():
        if len(message_queue) > 0:
            await send_message()

        await asyncio.sleep(1)


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
        "max value: 100"
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

    info_text_list = await storm_fort.search(
        client_index, 
        center=center,
        dist=min(search_dist, 100),
        criterias=criteria_list
    )

    if info_text_list == []:
        await interaction.followup.send(
            "No results were found.", 
            ephemeral=True
        )
        return
    
    for message in info_text_list:
        await interaction.followup.send(
            message, 
            ephemeral=True
        )


@bot.event
async def on_ready() -> None:
    print(f"{bot.user} is online!")

    await bot.tree.sync()
    
    asyncio.create_task(background_msg_loop())



def start_flask_server() -> None:
    print("st")
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
    attack_listener.update()
    storm_fort.update()

    await attack_listener.start()

    start_flask_server()

    async with bot:
        await bot.start(TOKEN)

    await attack_listener.cancel()


if __name__ == "__main__":
    asyncio.run(main())