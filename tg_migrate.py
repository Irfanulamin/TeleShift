from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()  # reads .env file before anything else runs


from telethon import TelegramClient, errors
from telethon.tl.types import (
    InputMediaPoll,
    MessageMediaWebPage,
    MessageMediaEmpty,
)

try:
    from rich.console import Console
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn,
        TaskProgressColumn, TimeRemainingColumn,
        TransferSpeedColumn, TextColumn,
    )
    from rich.logging import RichHandler
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("⚠  'rich' not installed. Run: pip install rich")
    print("   Falling back to plain logging.\n")


@dataclass
class Config:
    api_id:         int   = int(os.getenv("API_ID", "0"))
    api_hash:       str   = os.getenv("API_HASH", "")
    phone:          str   = os.getenv("PHONE", "")
    source_channel: int   = int(os.getenv("SOURCE_CHANNEL", "0"))
    dest_channel:   int   = int(os.getenv("DEST_CHANNEL", "0"))

    # Tuning
    batch_size:     int   = 50          # messages fetched per API call
    msg_delay:      float = 1.5         # seconds between individual sends
    batch_delay:    float = 3.0         # seconds between batches
    max_retries:    int   = 5           # per-message retry attempts

    # Paths
    progress_file:  str   = "./vault_progress.json"
    log_file:       str   = "./vault.log"
    session_name:   str   = "vault_session"


CFG = Config()

def build_logger(cfg: Config) -> logging.Logger:
    handlers: list[logging.Handler] = [
        logging.FileHandler(cfg.log_file, encoding="utf-8"),
    ]
    if RICH_AVAILABLE:
        handlers.append(RichHandler(rich_tracebacks=True, show_path=False))
    else:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    return logging.getLogger("telegramvault")


logger = build_logger(CFG)
console = Console() if RICH_AVAILABLE else None


@dataclass
class SessionState:
    last_message_id: int   = 0
    total_copied:    int   = 0
    total_skipped:   int   = 0
    total_failed:    int   = 0
    started_at:      str   = field(default_factory=lambda: datetime.now().isoformat())
    last_updated:    str   = ""

    def save(self, path: str) -> None:
        self.last_updated = datetime.now().isoformat()
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        logger.debug("Progress saved → %s", path)

    @classmethod
    def load(cls, path: str) -> "SessionState":
        p = Path(path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return cls(**data)
            except Exception as exc:
                logger.warning("Could not load progress file (%s) — starting fresh.", exc)
        return cls()

    def reset(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            p.unlink()
        self.__init__()
        logger.info("Progress reset.")



class AdaptiveThrottle:
    """
    Tracks flood-wait events and adaptively increases inter-message
    delay to reduce the frequency of future flood waits.
    """

    def __init__(self, base_delay: float = 1.5):
        self.delay        = base_delay
        self._base        = base_delay
        self._flood_count = 0

    async def wait(self) -> None:
        await asyncio.sleep(self.delay)

    def on_flood(self, seconds: int) -> None:
        self._flood_count += 1
        self.delay = min(self.delay * 1.5, 10.0)   # cap at 10 s
        logger.warning(
            "Flood wait %ds hit (total: %d). Delay → %.1fs",
            seconds, self._flood_count, self.delay,
        )

    def on_success(self) -> None:
        if self.delay > self._base:
            self.delay = max(self._base, self.delay * 0.98)



def _is_sendable_media(media) -> bool:
    """Return True only for media types we can re-send."""
    if media is None:
        return False
    if isinstance(media, (InputMediaPoll, MessageMediaWebPage, MessageMediaEmpty)):
        return False
    return True



async def copy_single(
    client: TelegramClient,
    dest,
    msg,
    throttle: AdaptiveThrottle,
    retries: int = 0,
) -> bool:
    """Send one media message to dest, no caption."""
    if not _is_sendable_media(msg.media):
        logger.debug("Skip msg %d (no sendable media)", msg.id)
        return False
    try:
        await client.send_file(dest, file=msg.media, caption=None)
        throttle.on_success()
        return True

    except errors.FloodWaitError as exc:
        throttle.on_flood(exc.seconds)
        await asyncio.sleep(exc.seconds + 5)
        if retries < CFG.max_retries:
            return await copy_single(client, dest, msg, throttle, retries + 1)
        logger.error("Msg %d flood-waited too many times, giving up.", msg.id)
        return False

    except (errors.ChatWriteForbiddenError, errors.ChannelPrivateError) as exc:
        logger.error("Permission error on dest: %s — aborting.", exc)
        raise

    except Exception as exc:
        if retries < CFG.max_retries:
            backoff = 2 ** retries
            logger.warning("Msg %d failed (%s). Retry %d in %ds…", msg.id, exc, retries + 1, backoff)
            await asyncio.sleep(backoff)
            return await copy_single(client, dest, msg, throttle, retries + 1)
        logger.error("Msg %d failed after %d retries: %s", msg.id, CFG.max_retries, exc)
        return False


async def copy_album(
    client: TelegramClient,
    dest,
    album: list,
    throttle: AdaptiveThrottle,
    retries: int = 0,
) -> bool:
    """Send a grouped media album as one post, no captions."""
    files = [m.media for m in album if _is_sendable_media(m.media)]
    if not files:
        return False
    try:
        await client.send_file(dest, file=files, caption=None)
        throttle.on_success()
        return True

    except errors.FloodWaitError as exc:
        throttle.on_flood(exc.seconds)
        await asyncio.sleep(exc.seconds + 5)
        if retries < CFG.max_retries:
            return await copy_album(client, dest, album, throttle, retries + 1)
        logger.error("Album flood-waited too many times, giving up.")
        return False

    except (errors.ChatWriteForbiddenError, errors.ChannelPrivateError):
        raise

    except Exception as exc:
        if retries < CFG.max_retries:
            backoff = 2 ** retries
            logger.warning("Album failed (%s). Retry %d in %ds…", exc, retries + 1, backoff)
            await asyncio.sleep(backoff)
            return await copy_album(client, dest, album, throttle, retries + 1)
        logger.error("Album failed after %d retries: %s", CFG.max_retries, exc)
        return False



async def keepalive(client: TelegramClient) -> None:
    while True:
        try:
            await asyncio.sleep(55)
            await client.get_me()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Keepalive ping failed: %s", exc)



def print_banner() -> None:
    if not RICH_AVAILABLE:
        print("=" * 64)
        print("  TelegramVault — Media Migration Engine")
        print("=" * 64)
        return
    console.print(Panel.fit(
        "[bold]TelegramVault[/bold]  ·  Media Migration Engine\n"
        "[dim]github.com/yourname/telegramvault[/dim]",
        border_style="dim",
    ))


def print_session_info(source_title: str, dest_title: str, total: int, state: SessionState) -> None:
    if not RICH_AVAILABLE:
        logger.info("Source : %s", source_title)
        logger.info("Dest   : %s", dest_title)
        logger.info("Total  : %d messages", total)
        logger.info("Resume : from msg ID %d (%d already copied)", state.last_message_id, state.total_copied)
        return

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column(style="dim", width=12)
    t.add_column()
    t.add_row("Source",  source_title)
    t.add_row("Dest",    dest_title)
    t.add_row("Messages", f"{total:,}")
    t.add_row("Resume",  f"msg ID {state.last_message_id}  ({state.total_copied:,} already done)")
    console.print(t)


def print_summary(state: SessionState, elapsed: float) -> None:
    if not RICH_AVAILABLE:
        logger.info("Done. Copied %d | Skipped %d | Failed %d | %.0fs",
                    state.total_copied, state.total_skipped, state.total_failed, elapsed)
        return

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column(style="dim", width=14)
    t.add_column()
    t.add_row("Copied",  f"[green]{state.total_copied:,}[/green]")
    t.add_row("Skipped", f"{state.total_skipped:,}")
    t.add_row("Failed",  f"[red]{state.total_failed:,}[/red]" if state.total_failed else "0")
    t.add_row("Time",    str(timedelta(seconds=int(elapsed))))
    console.print(Panel(t, title="[bold]Migration complete[/bold]", border_style="green"))


async def migrate(dry_run: bool = False) -> None:
    print_banner()

    state    = SessionState.load(CFG.progress_file)
    throttle = AdaptiveThrottle(CFG.msg_delay)
    t_start  = time.monotonic()

    client = TelegramClient(
        CFG.session_name, CFG.api_id, CFG.api_hash,
        connection_retries=-1,
        retry_delay=5,
        auto_reconnect=True,
        receive_updates=False,
    )

    await client.start(phone=CFG.phone)
    logger.info("Authenticated.")

    ka_task = asyncio.create_task(keepalive(client))

    try:
        source = await client.get_entity(CFG.source_channel)
        dest   = await client.get_entity(CFG.dest_channel)

        source_title = getattr(source, "title", str(CFG.source_channel))
        dest_title   = getattr(dest,   "title", str(CFG.dest_channel))

        total_messages = (await client.get_messages(source, limit=0)).total
        print_session_info(source_title, dest_title, total_messages, state)

        if dry_run:
            logger.info("Dry-run mode — no messages will be sent.")

        total_processed = state.total_copied + state.total_skipped + state.total_failed

        progress_ctx = (
            Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False,
            ) if RICH_AVAILABLE else None
        )
        task_id = None
        if progress_ctx:
            progress_ctx.start()
            task_id = progress_ctx.add_task(
                "Migrating…",
                total=total_messages,
                completed=total_processed,
            )

        offset_id = 0 if state.last_message_id == 0 else state.last_message_id

        try:
            while True:
                messages = await client.get_messages(
                    source,
                    limit=CFG.batch_size,
                    min_id=offset_id,
                    reverse=True,
                )

                if not messages:
                    logger.info("All messages processed.")
                    break

                msg_list       = list(messages)
                batch_copied   = 0
                batch_skipped  = 0
                batch_failed   = 0
                i = 0

                while i < len(msg_list):
                    msg = msg_list[i]
                    gid = getattr(msg, "grouped_id", None)

                    if gid is not None:
                        album = [msg]
                        j = i + 1
                        while (
                            j < len(msg_list)
                            and getattr(msg_list[j], "grouped_id", None) == gid
                        ):
                            album.append(msg_list[j])
                            j += 1

                        if j == len(msg_list) and len(album) < 10:
                            extra = await client.get_messages(
                                source,
                                limit=10,
                                min_id=album[-1].id,
                                reverse=True,
                            )
                            for em in extra:
                                if getattr(em, "grouped_id", None) == gid:
                                    album.append(em)
                                else:
                                    break

                        has_sendable = any(_is_sendable_media(m.media) for m in album)

                        if not dry_run:
                            ok = await copy_album(client, dest, album, throttle)
                        else:
                            ok = has_sendable
                        if ok:
                            batch_copied  += len(album)
                        elif has_sendable:
                            batch_failed  += len(album)
                        else:
                            batch_skipped += len(album)
                        i = j

                    else:
                        sendable = _is_sendable_media(msg.media)

                        if not dry_run:
                            ok = await copy_single(client, dest, msg, throttle)
                        else:
                            ok = sendable
                        if ok:
                            batch_copied  += 1
                        elif sendable:
                            batch_failed  += 1
                        else:
                            batch_skipped += 1
                        i += 1

                    if not dry_run:
                        await throttle.wait()

                last_id = msg_list[-1].id
                state.total_copied  += batch_copied
                state.total_skipped += batch_skipped
                state.total_failed  += batch_failed
                state.last_message_id = last_id
                state.save(CFG.progress_file)

                offset_id = last_id

                total_processed = state.total_copied + state.total_skipped + state.total_failed
                pct = (total_processed / total_messages * 100) if total_messages else 0
                logger.info(
                    "Batch done | copied +%d | skipped +%d | failed +%d | total %d/%d (%.1f%%)",
                    batch_copied, batch_skipped, batch_failed,
                    total_processed, total_messages, pct,
                )

                if progress_ctx and task_id is not None:
                    progress_ctx.update(task_id, completed=total_processed)

                if not dry_run:
                    await asyncio.sleep(CFG.batch_delay)

        finally:
            if progress_ctx:
                progress_ctx.stop()

    except (errors.ChatWriteForbiddenError, errors.ChannelPrivateError) as exc:
        logger.error("Permission error: %s — stopping.", exc)

    except asyncio.CancelledError:
        logger.warning("Cancelled by user.")

    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)

    finally:
        ka_task.cancel()
        try:
            await ka_task
        except asyncio.CancelledError:
            pass

        state.save(CFG.progress_file)
        elapsed = time.monotonic() - t_start
        print_summary(state, elapsed)
        await client.disconnect()

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="TelegramVault — media-only channel migration tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--reset", action="store_true",
        help="Clear saved progress and restart from the beginning",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Count copyable messages without sending anything",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.reset:
        s = SessionState.load(CFG.progress_file)
        s.reset(CFG.progress_file)

    try:
        asyncio.run(migrate(dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("\nStopped. Progress saved — run again to resume.")