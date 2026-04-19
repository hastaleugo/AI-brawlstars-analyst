import discord
from discord.ext import commands
from discord import app_commands
import google.generativeai as genai
import aiohttp
import os
import asyncio
import tempfile
import subprocess
import glob
import base64

TOKEN = os.environ.get("DISCORD_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)

intents = discord.Intents.default()
intents.message_content = True

class CoachBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        await self.tree.sync(guild=discord.Object(id=1489266291004149901))
        print("✅ Commandes slash synchronisées !")

bot = CoachBot()

@bot.event
async def on_ready():
    print(f"🤖 Coach IA connecté : {bot.user}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="vos replays Brawl Stars 🎮"
        )
    )

def extraire_frames(video_path, output_dir, intervalle=10):
    pattern = os.path.join(output_dir, "frame_%04d.jpg")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps=1/{intervalle}",
        "-q:v", "2", pattern,
        "-y", "-loglevel", "error"
    ]
    subprocess.run(cmd, check=True)
    frames = []
    for path in sorted(glob.glob(os.path.join(output_dir, "frame_*.jpg"))):
        idx = int(os.path.basename(path).replace("frame_", "").replace(".jpg", "")) - 1
        secondes = idx * intervalle
        minutes = secondes // 60
        secs = secondes % 60
        timestamp = f"{minutes}:{secs:02d}"
        frames.append({"timestamp": timestamp, "path": path})
    return frames

def get_duration(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())

def image_to_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

# ─────────────────────────────────────────────
# /analyse — Screenshot
# ─────────────────────────────────────────────
@bot.tree.command(
    name="analyse",
    description="📸 Analyse un screenshot de ta partie Brawl Stars"
)
@app_commands.describe(screenshot="Ton screenshot de partie Brawl Stars")
async def analyse(interaction: discord.Interaction, screenshot: discord.Attachment):
    if not screenshot.content_type or not screenshot.content_type.startswith("image/"):
        await interaction.response.send_message("❌ Envoie uniquement une image !", ephemeral=True)
        return

    await interaction.response.send_message("⏳ Analyse en cours...", ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(screenshot.url) as resp:
                image_data = await resp.read()

        model = genai.GenerativeModel("gemini-2.0-flash")

        image_part = {
            "inline_data": {
                "mime_type": screenshot.content_type,
                "data": base64.b64encode(image_data).decode("utf-8")
            }
        }

        prompt = """Tu es un coach esport professionnel spécialisé en Brawl Stars, expert de la scène compétitive EMEA.

Analyse ce screenshot et génère un rapport de coaching détaillé et professionnel.

Structure ta réponse EXACTEMENT ainsi :

🗺️ **SITUATION DÉTECTÉE**
Mode de jeu, map, brawlers visibles, score, état de la partie.

⚠️ **ERREURS IDENTIFIÉES**
2-3 erreurs tactiques critiques. Pour chacune : erreur + conséquence.

✅ **POINTS POSITIFS**
1-2 éléments bien exécutés. Sois honnête.

🎯 **CORRECTIONS IMMÉDIATES**
3 actions concrètes à appliquer maintenant.

💡 **CONSEIL EXPERT EMEA**
Un conseil de niveau compétitif qu'un joueur casual ne connaît pas.

📊 **ÉVALUATION**
- Niveau estimé : [Débutant / Intermédiaire / Avancé / Semi-pro / Compétitif]
- Note : [X/10]
- Priorité : [une phrase]"""

        response = model.generate_content([prompt, image_part])
        analysis = response.text

        embed = discord.Embed(
            title="🏆 Rapport de Coaching — Brawl Stars EMEA",
            description=analysis[:4000],
            color=0xFFD700
        )
        embed.set_image(url=screenshot.url)
        embed.set_footer(
            text=f"Analyse privée de {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url
        )

        await interaction.user.send(embed=embed)
        await interaction.edit_original_response(
            content="✅ Ton rapport de coaching a été envoyé en DM ! 📬"
        )

    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Erreur : `{str(e)}`")


# ─────────────────────────────────────────────
# /analyse_video — Vidéo complète horodatée
# ─────────────────────────────────────────────
@bot.tree.command(
    name="analyse_video",
    description="🎬 Analyse une vidéo de partie complète avec coaching horodaté (max 4 min)"
)
@app_commands.describe(
    video="Ta vidéo de partie Brawl Stars (MP4, MOV, max 25 Mo)",
    intervalle="Fréquence d'analyse (défaut: toutes les 10 secondes)"
)
@app_commands.choices(intervalle=[
    app_commands.Choice(name="Toutes les 5 secondes (très détaillé)", value=5),
    app_commands.Choice(name="Toutes les 10 secondes (recommandé)", value=10),
    app_commands.Choice(name="Toutes les 20 secondes (résumé rapide)", value=20),
])
async def analyse_video(
    interaction: discord.Interaction,
    video: discord.Attachment,
    intervalle: app_commands.Choice[int] = None
):
    intervalle_val = intervalle.value if intervalle else 10

    if not video.content_type or not video.content_type.startswith("video/"):
        await interaction.response.send_message(
            "❌ Envoie uniquement une vidéo (MP4, MOV) !", ephemeral=True
        )
        return

    if video.size > 25 * 1024 * 1024:
        await interaction.response.send_message(
            "❌ Vidéo trop lourde ! Maximum 25 Mo.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "⏳ **Étape 1/4** — Téléchargement de la vidéo...", ephemeral=True
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Téléchargement
            video_path = os.path.join(tmpdir, "game.mp4")
            async with aiohttp.ClientSession() as session:
                async with session.get(video.url) as resp:
                    with open(video_path, "wb") as f:
                        f.write(await resp.read())

            await interaction.edit_original_response(
                content="⏳ **Étape 2/4** — Vérification de la vidéo..."
            )

            duree = get_duration(video_path)
            if duree > 240:
                await interaction.edit_original_response(
                    content="❌ Vidéo trop longue ! Maximum 4 minutes."
                )
                return

            await interaction.edit_original_response(
                content="⏳ **Étape 3/4** — Extraction des moments clés..."
            )

            frames_dir = os.path.join(tmpdir, "frames")
            os.makedirs(frames_dir)
            frames = extraire_frames(video_path, frames_dir, intervalle_val)

            if not frames:
                await interaction.edit_original_response(
                    content="❌ Impossible d'extraire les frames."
                )
                return

            await interaction.edit_original_response(
                content=f"⏳ **Étape 4/4** — Analyse IA de {len(frames)} moments... (30-60 secondes)"
            )

            # Préparation du prompt avec toutes les frames
            model = genai.GenerativeModel("gemini-2.0-flash")

            content_parts = []
            content_parts.append(f"""Tu es un coach esport professionnel spécialisé en Brawl Stars, expert de la scène compétitive EMEA.

Je vais t'envoyer {len(frames)} captures extraites d'une vidéo de partie Brawl Stars de {int(duree//60)}:{int(duree%60):02d}.
Les captures sont prises toutes les {intervalle_val} secondes.
Chaque image est accompagnée de son timestamp exact.

Génère un rapport de coaching COMPLET, HORODATÉ et PROFESSIONNEL structuré EXACTEMENT ainsi :

─────────────────────────────────
🎮 **VUE D'ENSEMBLE**
Mode de jeu, map, brawlers des deux équipes, durée totale, résultat si visible.

─────────────────────────────────
📍 **ANALYSE HORODATÉE**
Pour chaque moment important, cite le timestamp exact en gras :

**[Xmin Xsec]** ⚠️ ERREUR : [description précise + pourquoi c'est une erreur]
**[Xmin Xsec]** ✅ BIEN JOUÉ : [ce qui a été bien fait + pourquoi]
**[Xmin Xsec]** 💡 OPPORTUNITÉ MANQUÉE : [ce qui aurait pu être fait]

Identifie MINIMUM 6 moments horodatés répartis sur toute la partie.

─────────────────────────────────
🔄 **PATTERNS RÉCURRENTS**
Erreurs qui se répètent tout au long de la partie.

─────────────────────────────────
🎯 **TOP 3 PRIORITÉS**
Les 3 points les plus importants à travailler avec des exercices concrets.

─────────────────────────────────
💡 **CONSEIL EXPERT EMEA**
Un conseil tactique avancé de niveau compétitif sur cette composition/map.

─────────────────────────────────
📊 **BILAN FINAL**
- Niveau estimé : [Débutant / Intermédiaire / Avancé / Semi-pro / Compétitif]
- Note globale : [X/10]
- Point fort : [une phrase]
- Point faible : [une phrase]
- Progression estimée si ces conseils appliqués : [+X trophées/semaine estimés]""")

            for frame in frames:
                content_parts.append(f"\n⏱️ Timestamp [{frame['timestamp']}] :")
                content_parts.append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_to_b64(frame["path"])
                    }
                })

            response = model.generate_content(content_parts)
            analyse_text = response.text

            # Envoi en DM — split si trop long
            if len(analyse_text) <= 4000:
                embed = discord.Embed(
                    title="🎬 Rapport de Coaching Vidéo — Brawl Stars EMEA",
                    description=analyse_text,
                    color=0xFFD700
                )
                embed.set_footer(
                    text=f"Analyse privée de {interaction.user.display_name} • {int(duree//60)}:{int(duree%60):02d}",
                    icon_url=interaction.user.display_avatar.url
                )
                await interaction.user.send(embed=embed)
            else:
                parties = [analyse_text[i:i+4000] for i in range(0, len(analyse_text), 4000)]
                for idx, partie in enumerate(parties):
                    titre = "🎬 Rapport de Coaching Vidéo — Brawl Stars EMEA" if idx == 0 else f"🎬 Suite du rapport ({idx+1}/{len(parties)})"
                    embed = discord.Embed(title=titre, description=partie, color=0xFFD700)
                    if idx == len(parties) - 1:
                        embed.set_footer(
                            text=f"Analyse privée de {interaction.user.display_name}",
                            icon_url=interaction.user.display_avatar.url
                        )
                    await interaction.user.send(embed=embed)

            await interaction.edit_original_response(
                content="✅ Ton rapport de coaching vidéo complet a été envoyé en DM ! 📬"
            )

        except subprocess.CalledProcessError:
            await interaction.edit_original_response(
                content="❌ Erreur vidéo. Format non supporté ? Essaie en MP4."
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="❌ Je ne peux pas t'envoyer de DM ! Active les messages privés dans tes paramètres Discord."
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Erreur : `{str(e)}`"
            )


# ─────────────────────────────────────────────
# /ping et /aide
# ─────────────────────────────────────────────
@bot.tree.command(name="ping", description="🏓 Vérifie si le bot est en ligne")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    color = 0x00FF00 if latency < 100 else 0xFF9900 if latency < 200 else 0xFF0000
    embed = discord.Embed(
        title="🏓 Pong !",
        description=f"**Latence :** `{latency}ms`\n**Statut :** ✅ En ligne",
        color=color
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="aide", description="📖 Guide d'utilisation du Coach IA")
async def aide(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Coach IA Brawl Stars — Guide",
        description="Le premier coach IA vidéo spécialisé Brawl Stars EMEA.",
        color=0x5865F2
    )
    embed.add_field(
        name="📸 /analyse — Screenshot",
        value="Attache un screenshot → coaching instantané envoyé en DM privé",
        inline=False
    )
    embed.add_field(
        name="🎬 /analyse_video — Partie complète",
        value=(
            "Attache une vidéo MP4 (max 4 min, 25 Mo)\n"
            "→ Rapport horodaté complet envoyé en DM privé\n"
            "Exemple : **[1:37]** ⚠️ Mauvais positionnement sur le gem spawn"
        ),
        inline=False
    )
    embed.add_field(
        name="⚠️ Important",
        value=(
            "• Tes analyses sont **100% privées** — seul toi les vois en DM\n"
            "• Active tes **messages privés** dans paramètres Discord\n"
            "• Vidéo en **MP4** pour meilleurs résultats\n"
            "• Si vidéo trop lourde : compresse sur **handbrake.fr**"
        ),
        inline=False
    )
    embed.set_footer(text="Coach IA EMEA • Powered by Gemini AI • 100% Gratuit")
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(TOKEN)
