import discord

def resolve_message_role(message: discord.Message, bot_user_id: int) -> str:
    """
    Role classification:
    - model: this bot
    - user: real Discord users
    - bot: external bots
    - webhook: webhook messages (synthetic user-like inputs)
    """
    if message.author.id == bot_user_id:
        return "model"

    if message.webhook_id is not None:
        return "webhook"

    if message.author.bot:
        return "bot"

    return "user"
