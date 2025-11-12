# plane.py
import discord
from discord import app_commands
import random
import io
from PIL import Image, ImageDraw

def setup_plane_commands(tree: app_commands.CommandTree):

    # ===== Messages =====
    upgrade_messages = [
        "💺 {user} has been upgraded to First Class because the pilot lost a bet and no one can stop them.",
        "First Class achieved! Congratulations, {user}, you now have more space than your personality deserves.",
        "{user} has been upgraded for loud whining and an inflated sense of self. Enjoy legroom, champ.",
        "Flight attendants collectively groaned when {user} sat down. Welcome to First Class, {user}.",
        "{user} upgraded! Your ego was too big for economy anyway, {user}.",
        "Seatbelt check: {user} strapped in… but still falling for their own bad ideas, {user}.",
        "First Class unlocked. {user}'s personality still smells like the cargo hold.",
        "{user} upgraded because chaos doesn’t travel coach.",
        "Congratulations {user}! You’re now closer to the snacks and farther from being likable, {user}.",
        "Enjoy First Class, {user} — it’s the only place where people won’t notice how bad you are at life, {user}.",
        "Pilot says: 'If {user} survives this upgrade, miracles exist.'",
        "You now have a seat next to someone who actually understands social cues, {user}. Good luck!",
        "{user} upgraded because the pilot lost a bet… and honestly, nobody else deserves First Class either.",
        "First Class welcomes {user} — try not to scream at the staff about your imaginary problems.",
        "{user} upgraded! Finally, a seat as inflated as your ego.",
        "Congratulations {user}, you now have legroom and zero social skills.",
        "{user} upgraded… the pilot is crying quietly in the cockpit.",
        "First Class unlocked for {user}. Warning: your personality still stinks like luggage.",
        "{user} now has a window seat to watch your dignity fly out the door.",
        "Emergency exit reserved for {user} — not that you’ll ever escape your own bad decisions.",
        "Pilot notes: {user} is dangerous but at least comfortable now.",
        "Upgraded, {user}. Try not to ruin the cabin like you ruin conversations."
    ]

    downgrade_messages = [
        "{user} downgraded to cargo. Enjoy your eternal suffering with the luggage, {user}.",
        "Middle seat eternity activated. Hope you like being elbowed and ignored, {user}.",
        "{user}, your seat has 0 legroom, 100% regret, and a complimentary crying baby.",
        "Pilot just laughed at {user}’s face. Downgrade complete, {user}.",
        "You now sit between someone’s smelly socks and a guy who just sneezed, {user}. Enjoy.",
        "Emergency exit denied. You’re the human pretzel now, {user}.",
        "Congratulations, {user} — your downgrade comes with bonus humiliation.",
        "{user} has been assigned the window that won’t open, the snack cart that won’t stop, and eternal sadness.",
        "Middle seat: where {user}’s dreams go to die. Have fun!",
        "{user}, if you die of boredom, the pilot is not liable.",
        "Seat folds if you cry, {user}. Warning: tears expected.",
        "{user} now travels with 0 dignity and 100% elbow abuse. Literally zero.",
        "Downgraded because the universe hates you, {user}. Don’t fight it.",
        "{user} downgraded to economy… and yes, your life choices are also economy class.",
        "Middle seat horror: {user}, you now sit between people who hate you politely.",
        "{user}, your downgrade includes a crying baby and a window that won’t open.",
        "Downgraded, {user}. No upgrade will save you — just like your personality."
    ]

    turbulence_messages = [
        "⚠️ Mild turbulence: {user} just blinked and broke physics.",
        "Moderate turbulence: {user} sneezed. Cabin lost structural integrity.",
        "Severe turbulence: {user} posted a hot take. Plane is spinning out of orbit.",
        "Extreme turbulence: {user} just typed 'hello'. Everyone panic!",
        "Server shaking! {user} clearly violates the Geneva Conventions of Chat.",
        "Brace yourselves — {user} just hit enter and destroyed 3 servers simultaneously.",
        "Turbulence intensifies: {user} laughed at someone’s misfortune.",
        "{user} activated 'chaotic evil mode.' All seats unsafe.",
        "Cabin crew reports: {user} is on fire. Figuratively, maybe literally.",
        "{user} typed 'oops'. The plane is now orbiting a trash fire."
    ]

    securitycheck_messages = [
        "🛃 Security finds: {user} smuggling 3 lies, 2 bad decisions, and a cursed emoji.",
        "Contraband detected: {user}’s ego and expired personality.",
        "Threat level: {user} is chaotic evil. Boarding allowed at your own risk.",
        "Security confiscated: {user}’s dignity. Flight may proceed.",
        "Pat-down complete: {user} is suspiciously ridiculous.",
        "Found in carry-on: 0 self-awareness, 100% stupidity. Thanks, {user}.",
        "Security flags: {user} may cause turbulence and emotional distress.",
        "Dangerous materials: {user}’s past tweets and bad memes.",
        "{user} failed the personality check. Security recommends permanent grounding.",
        "Contraband includes: sense of direction, sense of humor, and {user}.",
        "{user} attempted to smuggle drama. Detected and roasted.",
        "Warning: {user} laughed at a rule. Immediate emotional destruction incoming."
    ]

    # ===== Slash Commands =====
    @tree.command(name="upgrade", description="Savagely upgrade a member to First Class")
    @app_commands.describe(member="The member to upgrade")
    async def upgrade(interaction: discord.Interaction, member: discord.Member):
        msg = random.choice(upgrade_messages).format(user=member.mention)
        await interaction.response.send_message(msg)

    @tree.command(name="downgrade", description="Savagely downgrade a member to cargo/middle seat")
    @app_commands.describe(member="The member to downgrade")
    async def downgrade(interaction: discord.Interaction, member: discord.Member):
        msg = random.choice(downgrade_messages).format(user=member.mention)
        await interaction.response.send_message(msg)

    @tree.command(name="turbulence", description="Cause chaotic turbulence for a member")
    @app_commands.describe(member="The member to target")
    async def turbulence(interaction: discord.Interaction, member: discord.Member):
        msg = random.choice(turbulence_messages).format(user=member.mention)
        await interaction.response.send_message(msg)

    @tree.command(name="securitycheck", description="Perform a savage security check on a member")
    @app_commands.describe(member="The member to check")
    async def securitycheck(interaction: discord.Interaction, member: discord.Member):
        msg = random.choice(securitycheck_messages).format(user=member.mention)
        await interaction.response.send_message(msg)

    @tree.command(name="wingmates", description="Pair two members together (fun embed)")
    @app_commands.describe(user1="First member", user2="Second member")
    async def wingmates(interaction: discord.Interaction, user1: discord.Member, user2: discord.Member):
        ship_types = ["good", "bad", "chaos"]
        ship_type = random.choice(ship_types)

        good_ships = ["Power Couple of Turbulence","Snack Cart Soulmates","Window Seat Sweethearts"]
        bad_ships = ["Middle Seat Misery","Elbow Battle Partners","Screaming Baby Survivors"]
        chaos_ships = ["Flight Attendant's Worst Nightmare","Oxygen Mask Enthusiasts","Black Hole of Drama"]

        comments = [
            "Pilot says: don't talk to each other ever.",
            "Flight attendants are filing a restraining order.",
            "Brace for turbulence, the cabin fears you."
        ]

        if ship_type == "good":
            result = random.choice(good_ships)
            emoji = "❤️"
            percent = random.randint(70, 100)
        elif ship_type == "bad":
            result = random.choice(bad_ships)
            emoji = "💔"
            percent = random.randint(0, 40)
        else:
            result = random.choice(chaos_ships)
            emoji = "⚡"
            percent = random.randint(30, 80)

        comment = random.choice(comments)

        # Load avatars
        avatar1_bytes = await user1.display_avatar.read()
        avatar2_bytes = await user2.display_avatar.read()
        avatar1 = Image.open(io.BytesIO(avatar1_bytes)).convert("RGBA").resize((256, 256))
        avatar2 = Image.open(io.BytesIO(avatar2_bytes)).convert("RGBA").resize((256, 256))

        combined = Image.new("RGBA", (512, 256), (255, 255, 255, 255))
        combined.paste(avatar1, (0,0))
        combined.paste(avatar2, (256,0))

        draw = ImageDraw.Draw(combined)
        draw.text((256-10, 128-20), emoji, fill=(255,0,0))

        buffer = io.BytesIO()
        combined.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(fp=buffer, filename="wingmates.png")

        embed = discord.Embed(title=f"{emoji} Wingmate Result",
                              description=f"{user1.mention} + {user2.mention}",
                              color=random.randint(0, 0xFFFFFF))
        embed.add_field(name="Ship Name", value=result, inline=False)
        embed.add_field(name="Compatibility", value=f"{percent}%", inline=False)
        embed.add_field(name="In-Flight Commentary", value=comment, inline=False)
        embed.set_image(url="attachment://wingmates.png")
        embed.set_footer(text="Generated by The Pilot 🚀")

        await interaction.response.send_message(embed=embed, file=file)

    @tree.command(name="boardingpass", description="View a passenger's flight details 🛫")
    @app_commands.describe(member="Optional passenger")
    async def boardingpass(interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        join_date = member.joined_at.strftime("%d/%m/%y")
        days_on_board = (discord.utils.utcnow() - member.joined_at).days
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        role_list = ", ".join(roles) if roles else "No roles"

        flight_number = f"PA{random.randint(1000,9999)}"

        embed = discord.Embed(title=f"🎫 Boarding Pass for {member.display_name}",
                              color=discord.Color.purple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="🪪 Passenger", value=str(member), inline=False)
        embed.add_field(name="📅 Joined Flight Crew", value=join_date, inline=True)
        embed.add_field(name="🧭 Days on Board", value=f"{days_on_board} days", inline=True)
        embed.add_field(name="🎟️ Roles", value=role_list, inline=False)
        embed.add_field(name="✈️ Flight Number", value=flight_number, inline=True)
        embed.add_field(name="🛫 Server", value=interaction.guild.name, inline=True)
        embed.set_footer(text="Issued by The Pilot 🛩️")

        await interaction.response.send_message(embed=embed)

    @tree.command(name="pilotadvice", description="Receive the captain's inspirational advice ✈️")
    async def pilotadvice(interaction: discord.Interaction):
        announcements = [
            "⚠️ Please remain seated while we avoid turbulence of the mind.",
            "Keep your tray tables up and your expectations realistic.",
            "Flight attendants recommend smiling — it burns extra calories.",
            "Ladies and gentlemen, enjoy our complimentary chaos today."
        ]
        text = random.choice(announcements)
        embed = discord.Embed(title="✈️ Captain's Advice",
                              description=f"📢 {text}",
                              color=discord.Color.purple())
        embed.set_footer(text="- Captain PA")
        await interaction.response.send_message(embed=embed)