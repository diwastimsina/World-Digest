# World Digest

A zero-cost news agent. Every 4 hours, GitHub Actions pulls free RSS feeds and
Hacker News, drops anything you've already seen, ranks what's new by keyword
relevance, and sends a digest to your Telegram. If you add a free Gemini API
key, each section gets a short "why this matters" synthesis on top.

Sections: AI Industry, Tech Companies, Financial Services, World.

## Cost

$0. GitHub Actions is free for public repos, RSS and the HN API are free,
Telegram bots are free, and Gemini's free tier (optional) is free.

## Setup (about 10 minutes)

1. **Create the repo.** Push these files to a new public GitHub repo.

2. **Create a Telegram bot.** Message @BotFather on Telegram, send `/newbot`,
   follow the prompts, and copy the bot token.

3. **Get your chat ID.** Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the
   `chat.id` number from the response.

4. **Add repo secrets.** In GitHub: Settings → Secrets and variables →
   Actions → New repository secret. Add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GEMINI_API_KEY` (optional; free key from aistudio.google.com)

5. **Test it.** Go to the Actions tab → World Digest → Run workflow. You
   should get a Telegram message within a minute or two.

## Tuning

Everything lives in `config.yaml`:
- Add or remove feeds per section (any RSS/Atom URL works).
- Keywords drive ranking: `high` words are worth 3 points, `topic` words 1.
- `min_score_to_include` controls noise. Raise it for quieter digests.
- Quiet cycles send nothing at all instead of padding.

## How dedup works

Each item's title is hashed into `seen.json`, which the workflow commits back
to the repo after every run. The same story from two different feeds dedupes
because hashing is on the normalized title, not the URL.
