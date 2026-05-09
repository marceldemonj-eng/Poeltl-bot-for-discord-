import discord
from discord.ext import commands
import random
import difflib
from nba_api.stats.static import players as nba_players, teams as nba_teams
from nba_api.stats.endpoints import commonteamroster, commonplayerinfo
import time
import os

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "-"

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ── In-memory game state ───────────────────────────────────────────────────────
active_games = {}   # user_id -> Game instance

# ── Team metadata ─────────────────────────────────────────────────────────────
TEAM_INFO = {
    "ATL": ("East", "Southeast"), "BOS": ("East", "Atlantic"),
    "BKN": ("East", "Atlantic"),  "CHA": ("East", "Southeast"),
    "CHI": ("East", "Central"),   "CLE": ("East", "Central"),
    "DAL": ("West", "Southwest"), "DEN": ("West", "Northwest"),
    "DET": ("East", "Central"),   "GSW": ("West", "Pacific"),
    "HOU": ("West", "Southwest"), "IND": ("East", "Central"),
    "LAC": ("West", "Pacific"),   "LAL": ("West", "Pacific"),
    "MEM": ("West", "Southwest"), "MIA": ("East", "Southeast"),
    "MIL": ("East", "Central"),   "MIN": ("West", "Northwest"),
    "NOP": ("West", "Southwest"), "NYK": ("East", "Atlantic"),
    "OKC": ("West", "Northwest"), "ORL": ("East", "Southeast"),
    "PHI": ("East", "Atlantic"),  "PHX": ("West", "Pacific"),
    "POR": ("West", "Northwest"), "SAC": ("West", "Pacific"),
    "SAS": ("West", "Southwest"), "TOR": ("East", "Atlantic"),
    "UTA": ("West", "Northwest"), "WAS": ("East", "Southeast"),
}

# ── Load all rostered players at startup ──────────────────────────────────────
print("Loading NBA rosters (this takes ~60 seconds on first run)...")
ALL_ROSTERED = []   # list of player dicts
NAME_LIST    = []   # list of player names for fuzzy matching

def load_rosters():
    global ALL_ROSTERED, NAME_LIST
    all_nba_teams = nba_teams.get_teams()
    abbr_to_id    = {t['abbreviation']: t['id'] for t in all_nba_teams}
    all_players   = nba_players.get_players()
    name_to_pid   = {p['full_name']: p['id'] for p in all_players}

    for abbr, (conf, div) in TEAM_INFO.items():
        for attempt in range(3):
            try:
                tid    = abbr_to_id.get(abbr)
                roster = commonteamroster.CommonTeamRoster(team_id=tid, season='2025-26', timeout=60)
                df     = roster.get_data_frames()[0]
                for _, row in df.iterrows():
                    name = row.get('PLAYER', '')
                    if not name:
                        continue
                    pid = name_to_pid.get(name)
                    ht  = row.get('HEIGHT', '-') or '-'
                    age = str(row.get('AGE', '-')).split('.')[0]
                    pos = row.get('POSITION', '-') or '-'
                    num = str(row.get('NUM', '-')) or '-'
                    ALL_ROSTERED.append({
                        'name': name, 'team': abbr, 'conf': conf,
                        'div': div, 'pos': pos, 'height': ht,
                        'age': age, 'number': num, 'pid': pid,
                    })
                print(f"  {abbr} ✓")
                time.sleep(1)
                break
            except Exception as e:
                print(f"  {abbr} attempt {attempt+1} failed: {e}")
                time.sleep(5)

    NAME_LIST = [p['name'] for p in ALL_ROSTERED]
    print(f"Loaded {len(ALL_ROSTERED)} players.")

load_rosters()

# ── Game class ────────────────────────────────────────────────────────────────
class Game:
    MAX_GUESSES = 8

    def __init__(self):
        self.target   = random.choice(ALL_ROSTERED)
        self.guesses  = 0
        self.over     = False
        self.won      = False
        self.lines    = []
        # header
        self.lines.append(
            "`" + "Name".center(22) + " Team  Conf  Div    Pos  Ht    Age  #  `"
        )

    def guess(self, player: dict) -> str:
        self.guesses += 1
        t = self.target
        g = player
        line = f"`{g['name'][:22].center(22)}"

        # Team
        line += f" {g['team']:4}"
        line += "🟩" if g['team'] == t['team'] else "⬜"

        # Conference
        line += f" {g['conf'][:4]:4}"
        line += "🟩" if g['conf'] == t['conf'] else "⬜"

        # Division
        line += f" {g['div'][:6]:6}"
        line += "🟩" if g['div'] == t['div'] else ("🟨" if g['conf'] == t['conf'] else "⬜")

        # Position
        gpos = set(g['pos'].split('-'))
        tpos = set(t['pos'].split('-'))
        line += f" {g['pos'][:3]:3}"
        if gpos == tpos:         line += "🟩"
        elif gpos & tpos:        line += "🟨"
        else:                    line += "⬜"

        # Height
        line += f" {g['height']:5}"
        gh = self._ht(g['height'])
        th = self._ht(t['height'])
        if gh == th:             line += "🟩"
        elif gh != -1 and th != -1 and abs(gh - th) <= 2: line += "🟨⬆️" if gh < th else "🟨⬇️"
        else:                    line += "⬆️" if gh != -1 and th != -1 and gh < th else "⬇️" if gh != -1 and th != -1 else "⬜"

        # Age
        line += f" {g['age']:3}"
        try:
            ga, ta = int(g['age']), int(t['age'])
            if ga == ta:         line += "🟩"
            elif abs(ga - ta) <= 2: line += "🟨⬆️" if ga < ta else "🟨⬇️"
            else:                line += "⬆️" if ga < ta else "⬇️"
        except:                  line += "⬜"

        # Jersey number
        line += f" {g['number']:2}`"

        self.lines.append(line)

        correct = g['name'] == t['name']
        if correct:
            self.over = True
            self.won  = True
        elif self.guesses >= self.MAX_GUESSES:
            self.over = True

        board = "\n".join(self.lines)

        if correct:
            board += f"\n\n🎉 **Correct! {t['name']} in {self.guesses} guess{'es' if self.guesses != 1 else ''}!**"
        elif self.over:
            board += f"\n\n❌ **Game over! The answer was {t['name']} ({t['team']})**"
        else:
            board += f"\n\n_{self.MAX_GUESSES - self.guesses} guess{'es' if self.MAX_GUESSES - self.guesses != 1 else ''} remaining_"

        return board

    def _ht(self, h: str) -> int:
        try:
            parts = h.split('-')
            return int(parts[0]) * 12 + int(parts[1])
        except:
            return -1


# ── Commands ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online!")

@bot.command(name="poeltl")
async def poeltl(ctx):
    """Start a new Poeltl game"""
    uid = ctx.author.id
    if uid in active_games and not active_games[uid].over:
        await ctx.send("⚠️ You already have a game in progress! Use `-guess quit` to quit.")
        return
    if not ALL_ROSTERED:
        await ctx.send("❌ Rosters not loaded yet, try again in a moment.")
        return
    active_games[uid] = Game()
    embed = discord.Embed(
        title="🏀 Poeltl",
        description=(
            "Guess the mystery NBA player!\n\n"
            "Use `-guess [player name]` to make a guess.\n"
            "Use `-guess quit` to give up.\n\n"
            "**Color guide:**\n"
            "🟩 Correct  🟨 Close/Partial  ⬜ Wrong\n"
            "⬆️ Higher  ⬇️ Lower (for height, age)"
        ),
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed)

@bot.command(name="guess")
async def guess(ctx, *, name: str):
    """Guess a player in your Poeltl game"""
    uid = ctx.author.id

    if name.lower() == "quit":
        if uid in active_games:
            answer = active_games[uid].target['name']
            del active_games[uid]
            await ctx.send(f"Game ended. The answer was **{answer}**.")
        else:
            await ctx.send("No game in progress. Start one with `-poeltl`.")
        return

    if uid not in active_games or active_games[uid].over:
        await ctx.send("No active game. Start one with `-poeltl`!")
        return

    # Fuzzy match the name
    matches = difflib.get_close_matches(name, NAME_LIST, n=1, cutoff=0.6)
    if not matches:
        await ctx.send(f"❓ Can't find **{name}** in current rosters. Check the spelling!")
        return

    matched_name = matches[0]
    player = next((p for p in ALL_ROSTERED if p['name'] == matched_name), None)
    if not player:
        await ctx.send(f"❓ Player not found.")
        return

    game   = active_games[uid]
    result = game.guess(player)
    await ctx.send(result)

    if game.over:
        del active_games[uid]

@bot.command(name="players")
async def list_players(ctx, *, search: str = None):
    """Search for a player name"""
    if not search:
        await ctx.send("Usage: `-players [name]`")
        return
    matches = difflib.get_close_matches(search, NAME_LIST, n=5, cutoff=0.4)
    if matches:
        await ctx.send("Did you mean:\n" + "\n".join(f"• {m}" for m in matches))
    else:
        await ctx.send(f"No players found matching **{search}**.")

@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🏀 NBA Bot Commands",
        color=discord.Color.orange()
    )
    embed.add_field(name="`-poeltl`",       value="Start a Poeltl guessing game",         inline=False)
    embed.add_field(name="`-guess [name]`", value="Guess a player in your active game",    inline=False)
    embed.add_field(name="`-guess quit`",   value="Give up your current game",             inline=False)
    embed.add_field(name="`-players [name]`", value="Search for a player name",            inline=False)
    embed.add_field(name="`-help`",         value="Show this help message",                inline=False)
    await ctx.send(embed=embed)

# ── Run ───────────────────────────────────────────────────────────────────────
bot.run(TOKEN)
