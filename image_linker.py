import discord

async def setup(client: discord.Client):

    @client.event
    async def on_message(message: discord.Message):
        # Ignore bots
        if message.author.bot:
            return

        # No attachments = nothing to do
        if not message.attachments:
            return

        links = []
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image"):
                links.append(attachment.url)

        if not links:
            return

        await message.reply(
            "\n".join(links),
            mention_author=False
        )