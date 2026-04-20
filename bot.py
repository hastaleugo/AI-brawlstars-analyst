import discord
from discord.ext import commands
from discord import app_commands
from groq import Groq
import aiohttp
import os
import asyncio
import base64
import tempfile
import subprocess
import glob

TOKEN = os.environ.get("DISCORD_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

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
        "-q:v", "5",
        "-vf", f"fps=1/{intervalle},scale=640:-1",
        pattern, "-y", "-loglevel", "error"
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

        image_b64 = base64.b64encode(image_data).decode("utf-8")
        client = Groq(api_key=GROQ_KEY)

        response = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{screenshot.content_type};base64,{image_b64}"}
                    },
                    {
                        "type": "text",
                        "text": """Tu es un coach esport professionnel spécialisé en Brawl Stars, expert de la scène compétitive EMEA.

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
                    }
                ]
            }],
            max_tokens=1500
        )

        analysis = response.choices[0].message.content
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
        await interaction.edit_original_response(content="✅ Ton rapport de coaching a été envoyé en DM ! 📬")

    except discord.Forbidden:
        await interaction.edit_original_response(content="❌ Active tes messages privés dans paramètres Discord !")
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
    intervalle="Fréquence d'analyse"
)
@app_commands.choices(intervalle=[
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
        await interaction.response.send_message("❌ Envoie uniquement une vidéo (MP4, MOV) !", ephemeral=True)
        return

    if video.size > 25 * 1024 * 1024:
        await interaction.response.send_message("❌ Vidéo trop lourde ! Maximum 25 Mo.", ephemeral=True)
        return

    await interaction.response.send_message("⏳ **Étape 1/4** — Téléchargement...", ephemeral=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            video_path = os.path.join(tmpdir, "game.mp4")
            async with aiohttp.ClientSession() as session:
                async with session.get(video.url) as resp:
                    with open(video_path, "wb") as f:
                        f.write(await resp.read())

            await interaction.edit_original_response(content="⏳ **Étape 2/4** — Vérification...")

            duree = get_duration(video_path)
            if duree > 240:
                await interaction.edit_original_response(content="❌ Vidéo trop longue ! Maximum 4 minutes.")
                return

            await interaction.edit_original_response(content="⏳ **Étape 3/4** — Extraction des moments clés...")

            frames_dir = os.path.join(tmpdir, "frames")
            os.makedirs(frames_dir)
            frames = extraire_frames(video_path, frames_dir, intervalle_val)

            if not frames:
                await interaction.edit_original_response(content="❌ Impossible d'extraire les frames.")
                return

            await interaction.edit_original_response(
                content=f"⏳ **Étape 4/4** — Analyse IA de {len(frames)} moments... (peut prendre 1-2 min)"
            )

            client = Groq(api_key=GROQ_KEY)
            rapport_complet = []
            rapport_complet.append(f"🎮 **Partie analysée** — {int(duree//60)}:{int(duree%60):02d} min\n")
            rapport_complet.append("📍 **ANALYSE HORODATÉE**\n")

            # Analyse frame par frame
            for frame in frames:
                b64 = image_to_b64(frame["path"])
                try:
                    response = client.chat.completions.create(
                        model="llama-3.2-11b-vision-preview",
                        messages=[{
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                                },
                                {
                                    "type": "text",
                                    "text": f"""Tu es un coach Brawl Stars expert EMEA. 
Cette capture vient d'une partie à [{frame['timestamp']}].
En 2-3 phrases maximum, identifie UNE erreur OU UN point positif OU UNE opportunité manquée visible.
Format STRICT : **[{frame['timestamp']}]** ⚠️/✅/💡 [type] : [description courte et précise]
Si l'image n'est pas claire ou pas de Brawl Stars, écris : **[{frame['timestamp']}]** — Aucun événement notable."""
                                }
                            ]
                        }],
                        max_tokens=150
                    )
                    rapport_complet.append(response.choices[0].message.content)
                    await asyncio.sleep(1)  # évite le rate limit
                except Exception:
                    rapport_complet.append(f"**[{frame['timestamp']}]** — Analyse indisponible")

            # Synthèse finale
            rapport_complet.append("\n─────────────────────────────────")
            rapport_complet.append("🎯 **TOP 3 PRIORITÉS À TRAVAILLER**")

            synthese = client.chat.completions.create(
                model="llama-3.2-90b-vision-preview",
                messages=[{
                    "role": "user",
                    "content": f"""Sur la base de cette analyse horodatée d'une partie Brawl Stars :

{chr(10).join(rapport_complet)}

Donne les 3 priorités les plus importantes à travailler avec des conseils concrets. 
Termine avec :
📊 Niveau estimé : [niveau]
⭐ Note globale : [X/10]"""
                }],
                max_tokens=400
            )
            rapport_complet.append(synthese.choices[0].message.content)

            # Envoi en DM
            texte_final = "\n".join(rapport_complet)
            if len(texte_final) <= 4000:
                embed = discord.Embed(
                    title="🎬 Rapport de Coaching Vidéo — Brawl Stars EMEA",
                    description=texte_final,
                    color=0xFFD700
                )
                embed.set_footer(
                    text=f"Analyse privée de {interaction.user.display_name}",
                    icon_url=interaction.user.display_avatar.url
                )
                await interaction.user.send(embed=embed)
            else:
                parties = [texte_final[i:i+4000] for i in range(0, len(texte_final), 4000)]
                for idx, partie in enumerate(parties):
                    titre = "🎬 Rapport de Coaching Vidéo — Brawl Stars EMEA" if idx == 0 else f"🎬 Suite ({idx+1}/{len(parties)})"
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
            await interaction.edit_original_response(content="❌ Erreur vidéo. Essaie en MP4.")
        except discord.Forbidden:
            await interaction.edit_original_response(content="❌ Active tes messages privés dans paramètres Discord !")
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Erreur : `{str(e)}`")


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
            "→ Rapport horodaté complet envoyé en DM\n"
            "Exemple : **[1:30]** ⚠️ Mauvais positionnement"
        ),
        inline=False
    )
    embed.add_field(
        name="⚠️ Important",
        value=(
            "• Analyses **100% privées** en DM\n"
            "• Active tes **messages privés** Discord\n"
            "• Vidéo en **MP4**, max 25 Mo"
        ),
        inline=False
    )
    embed.set_footer(text="Coach IA EMEA • Powered by Groq AI • 100% Gratuit")
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(TOKEN)
