# TeleShift

Simple tool to move media from one Telegram channel to another.

Built with **Python** and **Telethon**.

## What it does

- Copies photos, videos, files, and other media
- Skips text-only messages
- Removes captions
- Supports albums / grouped media
- Saves progress so you can continue later
- Handles Telegram flood waits automatically
- Shows live progress in terminal
- Supports restart with saved state

---

## Requirements

- Python 3.9+
- Telegram account
- Telegram API ID + API Hash

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/irfanulamin/teleshift.git
cd teleshift
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

### 3. Activate the virtual environment

**Windows:**

```bash
venv\Scripts\activate
```

**Mac / Linux:**

```bash
source venv/bin/activate
```

> You should see `(venv)` at the start of your terminal line after activation.

### 4. Install packages

```bash
pip install telethon rich python-dotenv
```

### 5. Create a `.env` file

```env
API_ID=your_api_id
API_HASH=your_api_hash
PHONE=+8801XXXXXXXXX

SOURCE_CHANNEL=-1001234567890
DEST_CHANNEL=-1009876543210
```

---

## Get API Credentials

Go to:

https://my.telegram.org

Log in with your Telegram account, create an app, and copy:

- `API_ID`
- `API_HASH`

---

## Run

Make sure the virtual environment is active before running any command.

Run the migration:

```bash
python tg_migrate.py
```

Reset saved progress and start over:

```bash
python tg_migrate.py --reset
```

Dry run (counts messages without sending anything):

```bash
python tg_migrate.py --dry-run
```

---

## VS Code Setup

If you are using VS Code and see import errors for `telethon` or `rich`:

1. Press `Ctrl+Shift+P`
2. Select **Python: Select Interpreter**
3. Choose the interpreter inside your `venv` folder:
   - Windows: `.\venv\Scripts\python.exe`
   - Mac/Linux: `./venv/bin/python`

The red underlines will disappear after selecting the correct interpreter.

---

## Files

| File                    | Description                          |
| ----------------------- | ------------------------------------ |
| `tg_migrate.py`         | Main script                          |
| `.env`                  | Your credentials (never share this)  |
| `vault_progress.json`   | Saved progress (auto-created)        |
| `vault.log`             | Logs (auto-created)                  |
| `vault_session.session` | Telegram session file (auto-created) |

---

## Troubleshooting

**`Import "telethon" could not be resolved`**
→ Packages are not installed in the active interpreter. Follow the VS Code Setup section above.

**`No module named 'dotenv'`**
→ Run `pip install python-dotenv` inside your activated venv.

**`The channel specified is private`**
→ Make sure your Telegram account is a member of the source channel.

**`ChatWriteForbiddenError`**
→ Your account does not have permission to post in the destination channel. Make sure you are an admin there.

**Flood wait errors**
→ Normal behavior. The script waits automatically and resumes. Do not interrupt it.

**Script stopped halfway**
→ Just run `python tg_migrate.py` again. It will resume from where it left off.

---

## Notes

- You need access to the source channel
- You need permission to post in the destination channel
- Large transfers may take time because of Telegram rate limits
- Never share your `.env` file or `vault_session.session` file

---

## Disclaimer

Use only for content you own or have permission to move. The author is not responsible for misuse.
