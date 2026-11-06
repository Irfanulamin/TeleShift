# TeleShift

A command-line tool that copies all media from one Telegram channel to another. It runs on your own Telegram account through Telethon, works through the channel history in batches, and saves its place so a long migration can be stopped and resumed.

## What it does

- Copies photos, videos, documents and other files
- Keeps albums together as one post
- Skips text-only messages, polls and link previews
- Drops captions, so only the media is copied
- Saves progress after every batch and resumes from there
- Waits out Telegram flood limits and backs off on errors
- Shows a live progress bar and writes a log file
- Has a dry run that counts what would be copied without sending anything

## Requirements

- Python 3.9+
- A Telegram account that can read the source channel and post in the destination channel
- An API ID and API hash from [my.telegram.org](https://my.telegram.org) (API development tools → create an app)

## Setup

```bash
git clone https://github.com/Irfanulamin/TeleShift.git
cd TeleShift
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Then fill in `.env`:

| Variable         | Description                                                  |
| ---------------- | ------------------------------------------------------------ |
| `API_ID`         | From my.telegram.org                                         |
| `API_HASH`       | From my.telegram.org                                         |
| `PHONE`          | Your number with country code, e.g. `+8801XXXXXXXXX`         |
| `SOURCE_CHANNEL` | Numeric ID of the channel to copy from, e.g. `-1001234567890` |
| `DEST_CHANNEL`   | Numeric ID of the channel to copy to                         |

Both channel values must be numeric IDs, not usernames. An easy way to find one is to forward a post from the channel to [@userinfobot](https://t.me/userinfobot).

## Usage

```bash
python tg_migrate.py             # start, or continue where it stopped
python tg_migrate.py --dry-run   # count copyable messages, send nothing
python tg_migrate.py --reset     # forget saved progress and start over
```

The first run asks for the login code Telegram sends you. After that the session is saved locally and you won't be asked again.

## Tuning

The defaults in the `Config` class at the top of `tg_migrate.py` are on the safe side for Telegram's rate limits:

| Setting       | Default | Meaning                              |
| ------------- | ------- | ------------------------------------ |
| `batch_size`  | 50      | Messages fetched per request         |
| `msg_delay`   | 1.5 s   | Pause between sends                  |
| `batch_delay` | 3.0 s   | Pause between batches                |
| `max_retries` | 5       | Attempts per message before skipping |

Lowering the delays makes flood waits more likely, which ends up slower.

## Files it creates

| File                    | Purpose                                  |
| ----------------------- | ---------------------------------------- |
| `vault_session.session` | Your Telegram login. Keep it private.    |
| `vault_progress.json`   | Last processed message, used for resume  |
| `vault.log`             | Full log of the run                      |

All three are in `.gitignore`. Anyone with the `.session` file can use your Telegram account, so never share or commit it.

## Troubleshooting

- **The channel specified is private:** your account isn't a member of the source channel.
- **ChatWriteForbiddenError:** your account can't post in the destination channel. Make it an admin there.
- **Long pauses with "flood wait" in the log:** expected. Telegram is rate limiting you and the script continues on its own.
- **It stopped partway:** run the same command again and it continues from the saved position.

## Disclaimer

Only move content you own or have permission to copy.

## License

[MIT](LICENSE)
