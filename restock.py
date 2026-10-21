"""
Discord Shop Bot — /restock + joli embed produit + bouton rouge de ticket.

Prérequis :
    py -m pip install -U discord.py python-dotenv

Configuration :
    Crée un fichier .env à côté de ce fichier avec :
    DISCORD_TOKEN=TON_TOKEN
    # Facultatif : ID de la catégorie où créer les tickets privés
    TICKET_CATEGORY_ID=123456789012345678
    # Facultatif : ID du rôle staff qui doit voir les tickets
    STAFF_ROLE_ID=123456789012345678

Active "Server Members Intent" uniquement si nécessaire dans le portail Discord.
Les commandes slash sont synchronisées au démarrage.
"""

import os
import re
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0") or "0")
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0") or "0")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def safe_channel_name(text: str) -> str:
    """Convertit un nom en nom de salon Discord simple."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text[:35] or "client")


def parse_emoji(value: str, guild: discord.Guild | None = None):
    """Accepte un emoji Unicode ou un emoji personnalisé écrit :nom:."""
    value = value.strip()
    if not value:
        return "🛍️"

    match = re.fullmatch(r":([A-Za-z0-9_~]+):", value)
    if match and guild is not None:
        found = discord.utils.get(guild.emojis, name=match.group(1))
        if found:
            return found

    # Formats Discord copiés/collés : <:nom:123> ou <a:nom:123>
    match = re.fullmatch(r"<a?:([A-Za-z0-9_]+):(\\d+)>", value)
    if match and guild is not None:
        found = discord.utils.get(guild.emojis, id=int(match.group(2)))
        if found:
            return found

    return value[:100]


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fermer le ticket",
        style=discord.ButtonStyle.secondary,
        emoji="🔒",
        custom_id="shopbot:close_ticket",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Cette action doit être utilisée dans un salon ticket.", ephemeral=True
            )
            return

        is_staff = False
        if isinstance(interaction.user, discord.Member):
            is_staff = interaction.user.guild_permissions.manage_channels or any(
                role.id == STAFF_ROLE_ID
                for role in interaction.user.roles
            ) if STAFF_ROLE_ID else interaction.user.guild_permissions.manage_channels

        is_ticket = bool(channel.topic and "shop-ticket:" in channel.topic)
        if not is_ticket:
            await interaction.response.send_message(
                "Ce salon ne semble pas être un ticket créé par le bot.", ephemeral=True
            )
            return

        owner_match = re.search(r"shop-ticket:(\d+)", channel.topic or "")
        owner_id = int(owner_match.group(1)) if owner_match else 0
        if interaction.user.id != owner_id and not is_staff:
            await interaction.response.send_message(
                "Seul l'auteur du ticket ou le staff peut le fermer.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🔒 Fermeture du ticket dans quelques secondes…"
        )
        await channel.delete(reason=f"Ticket fermé par {interaction.user}")


class ProductTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ouvrir un ticket",
        style=discord.ButtonStyle.secondary,
        emoji="🎫",
        custom_id="shopbot:open_ticket",
    )
    async def open_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Cette action est disponible uniquement sur un serveur.", ephemeral=True
            )
            return

        # Évite qu'un même membre ouvre plusieurs tickets simultanément.
        for channel in guild.text_channels:
            if channel.topic and f"shop-ticket:{interaction.user.id}" in channel.topic:
                await interaction.response.send_message(
                    f"Tu as déjà un ticket ouvert : {channel.mention}",
                    ephemeral=True,
                )
                return

        category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
        if not isinstance(category, discord.CategoryChannel):
            category = discord.utils.get(guild.categories, name="Tickets")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            ),
        }

        staff_role = guild.get_role(STAFF_ROLE_ID) if STAFF_ROLE_ID else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

        channel_name = f"ticket-{safe_channel_name(interaction.user.display_name)}"
        try:
            ticket = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"shop-ticket:{interaction.user.id} | Ticket de {interaction.user}",
                reason=f"Ticket ouvert par {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Je n'ai pas la permission de créer des salons. "
                "Donne-moi la permission « Gérer les salons ».",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "Impossible de créer le ticket. Réessaie dans un instant.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🎫 Nouveau ticket",
            description=(
                f"Salut {interaction.user.mention} ! Merci de contacter le shop.\n\n"
                "🛍️ **Indique le produit qui t'intéresse** et pose ta question ici.\n"
                "💳 Le staff confirmera le prix, la disponibilité et les moyens de paiement "
                "avant toute transaction.\n\n"
                "🔐 Ne partage jamais ton mot de passe ni tes informations confidentielles."
            ),
            color=discord.Color.from_rgb(235, 65, 75),
        )
        embed.set_footer(text="Shop Support • Merci de rester courtois")
        await ticket.send(
            content=f"{interaction.user.mention}" + (f" {staff_role.mention}" if staff_role else ""),
            embed=embed,
            view=CloseTicketView(),
        )
        await interaction.response.send_message(
            f"✅ Ton ticket privé est créé : {ticket.mention}", ephemeral=True
        )


class RestockModal(discord.ui.Modal, title="Créer une annonce produit"):
    product_name = discord.ui.TextInput(
        label="Nom du produit",
        placeholder="Ex. : Offre Nitro / Décoration serveur",
        max_length=100,
    )
    product_emoji = discord.ui.TextInput(
        label="Emoji du produit",
        placeholder="Ex. : ⚡",
        default="🛍️",
        max_length=100,
        required=False,
    )
    price = discord.ui.TextInput(
        label="Prix",
        placeholder="Ex. : 4,99 €",
        max_length=50,
    )
    payment_methods = discord.ui.TextInput(
        label="Moyens de paiement",
        placeholder="Ex. : PayPal, carte bancaire…",
        max_length=200,
    )
    details = discord.ui.TextInput(
        label="Description / stock / conditions",
        placeholder="Décris l'offre, le stock, la durée, les conditions…",
        style=discord.TextStyle.paragraph,
        max_length=900,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Utilise cette commande dans un salon du serveur.", ephemeral=True
            )
            return

        emoji = parse_emoji(str(self.product_emoji.value), interaction.guild)

        # Annonce très compacte : prix + paiement sur une seule ligne.
        details = self.details.value.strip()
        if len(details) > 160:
            details = details[:157].rstrip() + "..."

        parts = [
            f"**{self.price.value.strip()}**  ·  💳 {self.payment_methods.value.strip()[:80]}",
        ]
        if details:
            parts.append(details)
        parts.append("👇 Clique sur le bouton pour commander.")

        embed = discord.Embed(
            title=f"{emoji} {self.product_name.value.strip()}",
            description="\\n".join(parts),
            color=discord.Color.from_rgb(88, 101, 242),
        )
        embed.set_footer(text="BLUE SHOP")


        try:
            await interaction.channel.send(embed=embed, view=ProductTicketView())
        except discord.Forbidden:
            await interaction.response.send_message(
                "Je ne peux pas envoyer de message dans ce salon. Vérifie mes permissions.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ Annonce produit publiée avec son bouton de ticket !", ephemeral=True
        )


@bot.event
async def on_ready():
    # Enregistre les vues persistantes pour que les boutons continuent de fonctionner
    # après un redémarrage du bot.
    bot.add_view(ProductTicketView())
    bot.add_view(CloseTicketView())
    try:
        synced = await bot.tree.sync()
        print(f"Connecté en tant que {bot.user} — {len(synced)} commande(s) synchronisée(s).")
    except discord.HTTPException as exc:
        print(f"Erreur de synchronisation des commandes : {exc}")


@bot.tree.command(name="restock", description="Publier une annonce produit élégante avec bouton ticket")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
async def restock(interaction: discord.Interaction):
    await interaction.response.send_modal(RestockModal())


@bot.tree.command(name="shophelp", description="Afficher l'aide rapide du bot shop")
@app_commands.guild_only()
async def shophelp(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛍️ Aide du Shop Bot",
        description=(
            "`/restock` — crée une annonce produit en remplissant un formulaire.\n"
            "`/shophelp` — affiche cette aide.\n\n"
            "Le bouton « Ouvrir un ticket » crée un salon privé avec le client."
        ),
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


if not TOKEN:
    raise RuntimeError(
        "Token manquant : crée un fichier .env avec DISCORD_TOKEN=TON_TOKEN"
    )

bot.run(TOKEN)
