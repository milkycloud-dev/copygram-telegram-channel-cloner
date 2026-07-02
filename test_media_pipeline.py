"""
Comprehensive media pipeline test.
Downloads 34 media files from the source channel, processes through clean_file,
and uploads to Saved Messages for visual verification.
"""
import asyncio
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from telethon import TelegramClient, utils
from telethon.tl.types import (
    DocumentAttributeVideo, DocumentAttributeAudio,
    DocumentAttributeFilename, MessageMediaDocument
)
from metadata_cleaner import clean_file

WORK_DIR = "test_run"
os.makedirs(WORK_DIR, exist_ok=True)

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

API_ID = config.get("api_id", 2040)
API_HASH = config.get("api_hash", "")
SOURCE_ID = int(config["source_channel_ids"][0])
MAX_MSG_ID = 94000


def get_file_ext(msg):
    """Get file extension from message document."""
    if not hasattr(msg.media, 'document') or not msg.media.document:
        return ""
    for attr in msg.media.document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return os.path.splitext(attr.file_name)[1].lower()
    mime = msg.media.document.mime_type or ""
    ext_map = {
        "video/mp4": ".mp4", "video/quicktime": ".mov",
        "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
        "video/x-matroska": ".mkv",
    }
    return ext_map.get(mime, "")


def is_video_note(msg):
    """Check if message is a video circle (round message)."""
    if not hasattr(msg.media, 'document') or not msg.media.document:
        return False
    for attr in msg.media.document.attributes:
        if isinstance(attr, DocumentAttributeVideo) and attr.round_message:
            return True
    return False


def get_video_attrs(msg):
    """Extract video/audio attributes from original message."""
    attrs = []
    if not hasattr(msg.media, 'document') or not msg.media.document:
        return attrs
    for attr in msg.media.document.attributes:
        if isinstance(attr, DocumentAttributeVideo):
            attrs.append(attr)
        elif isinstance(attr, DocumentAttributeAudio):
            attrs.append(attr)
    return attrs


async def find_media(client, channel, media_type, count, searched_offsets=None):
    """
    Find `count` messages of the specified media_type by random sampling.
    media_type: 'mp4', 'mov', 'circle', 'ogg', 'mp3'
    """
    found = []
    attempts = 0
    # Increase max_attempts significantly for rare media types like ogg/mp3
    max_attempts = count * 200 
    used_ids = set()
    
    if searched_offsets is None:
        searched_offsets = set()

    while len(found) < count and attempts < max_attempts:
        attempts += 1
        offset_id = random.randint(1, MAX_MSG_ID)
        
        # Avoid re-searching same area
        bucket = offset_id // 100
        if bucket in searched_offsets:
            continue
        searched_offsets.add(bucket)
        
        try:
            async for msg in client.iter_messages(channel, limit=100, offset_id=offset_id):
                if msg.id in used_ids:
                    continue
                if not msg.media or not isinstance(msg.media, MessageMediaDocument):
                    continue
                if not hasattr(msg.media, 'document') or not msg.media.document:
                    continue
                
                ext = get_file_ext(msg)
                is_circle = is_video_note(msg)
                
                match = False
                if media_type == "mp4" and ext == ".mp4" and not is_circle:
                    match = True
                elif media_type == "mov" and ext == ".mov" and not is_circle:
                    match = True
                elif media_type == "circle" and is_circle:
                    match = True
                elif media_type == "ogg" and ext == ".ogg":
                    match = True
                elif media_type == "mp3" and ext == ".mp3":
                    match = True
                
                if match:
                    used_ids.add(msg.id)
                    found.append(msg)
                    print(f"  [{media_type}] Found #{len(found)}: msg {msg.id} (ext={ext}, circle={is_circle})")
                    if len(found) >= count:
                        break
        except Exception as e:
            # ignore flood wait for read
            pass
    
    return found


async def main():
    client = TelegramClient("session_reader", API_ID, API_HASH)
    await client.start()
    
    channel = await client.get_entity(int(f"-100{SOURCE_ID}"))
    print(f"Connected. Source channel: {channel.title} (ID: {SOURCE_ID})")
    
    searched_offsets = set()
    results = {}
    
    # Search for each type
    for media_type, count in [("mp4", 10), ("mov", 10), ("circle", 10), ("ogg", 2), ("mp3", 2)]:
        print(f"\nSearching for {count} x {media_type}...")
        msgs = await find_media(client, channel, media_type, count, searched_offsets)
        results[media_type] = msgs
        print(f"  -> Found {len(msgs)} {media_type} files")
        if len(msgs) < count:
            print(f"  WARNING: Could not find enough {media_type} files (found {len(msgs)}/{count})")
    
    # Download, process, and upload
    total = sum(len(v) for v in results.values())
    print(f"\n{'='*60}")
    print(f"Total files to process: {total}")
    print(f"{'='*60}\n")
    
    success = 0
    failed = 0
    report = []
    
    for media_type, messages in results.items():
        for i, msg in enumerate(messages):
            label = f"[{media_type} {i+1}/{len(messages)}]"
            ext = get_file_ext(msg)
            if not ext and is_video_note(msg):
                ext = ".mp4"
            
            fname = f"{media_type}_{msg.id}{ext}"
            dl_path = os.path.join(WORK_DIR, fname)
            
            try:
                # 1. Download
                print(f"{label} Downloading msg {msg.id}...")
                await client.download_media(msg, file=dl_path)
                
                if not os.path.exists(dl_path):
                    print(f"{label} SKIP: Download failed")
                    report.append({"type": media_type, "id": msg.id, "status": "dl_failed"})
                    failed += 1
                    continue
                
                file_size = os.path.getsize(dl_path)
                print(f"{label} Downloaded: {file_size / 1024 / 1024:.1f} MB")
                
                # 2. Process through clean_file
                cleaned_path, log_msg, status = clean_file(dl_path)
                print(f"{label} Cleaned: {status} - {log_msg}")
                
                # 3. Get original attributes from the source message
                orig_attrs = get_video_attrs(msg)
                attr_info = ""
                for a in orig_attrs:
                    if isinstance(a, DocumentAttributeVideo):
                        attr_info = f"w={a.w} h={a.h} dur={a.duration} stream={a.supports_streaming} round={a.round_message}"
                    elif isinstance(a, DocumentAttributeAudio):
                        attr_info = f"dur={a.duration} voice={a.voice}"
                
                # 4. Check Telethon auto-detection (with hachoir)
                auto_attrs, auto_mime = utils.get_attributes(cleaned_path)
                auto_info = ""
                for a in auto_attrs:
                    if isinstance(a, DocumentAttributeVideo):
                        auto_info = f"auto: w={a.w} h={a.h} dur={a.duration}"
                
                print(f"{label} Orig attrs: {attr_info}")
                if auto_info:
                    print(f"{label} Auto attrs: {auto_info}")
                
                # 5. Generate thumbnail
                thumb_path = None
                if media_type in ("mp4", "mov", "circle"):
                    # Use duration if available
                    duration = 0
                    for a in orig_attrs:
                        if isinstance(a, DocumentAttributeVideo):
                            duration = a.duration
                    from metadata_cleaner import generate_thumbnail
                    thumb_path = generate_thumbnail(cleaned_path, duration)

                # 6. Upload to Saved Messages
                caption = f"Test {media_type} #{i+1} (msg {msg.id})\nOrig: {attr_info}\nAuto: {auto_info}\nThumb: {'Yes' if thumb_path else 'No'}"
                
                await client.send_file(
                    "me",
                    cleaned_path,
                    caption=caption,
                    attributes=orig_attrs if orig_attrs else None,
                    thumb=thumb_path,
                    supports_streaming=True
                )
                print(f"{label} Uploaded to Saved Messages!")
                
                # Cleanup
                try:
                    os.remove(cleaned_path)
                    if thumb_path and os.path.exists(thumb_path):
                        os.remove(thumb_path)
                except:
                    pass
                
                success += 1
                report.append({
                    "type": media_type, "id": msg.id, "status": "OK",
                    "size_mb": round(file_size / 1024 / 1024, 1),
                    "orig": attr_info, "auto": auto_info
                })
                
                # Small delay to avoid flood
                await asyncio.sleep(2)
                
            except Exception as e:
                print(f"{label} ERROR: {e}")
                report.append({"type": media_type, "id": msg.id, "status": f"error: {e}"})
                failed += 1
                # Cleanup on error
                for p in [dl_path, dl_path + "_cleaned" + ext]:
                    try: os.remove(p)
                    except: pass
    
    # Final report
    print(f"\n{'='*60}")
    print(f"RESULTS: {success} OK / {failed} FAILED / {total} TOTAL")
    print(f"{'='*60}")
    for r in report:
        status_icon = "OK" if r["status"] == "OK" else "FAIL"
        print(f"  [{status_icon}] {r['type']} msg:{r['id']} - {r.get('orig', '')} ({r.get('size_mb', '?')} MB)")
    
    await client.disconnect()
    print("\nDone! Check your Saved Messages in Telegram.")


if __name__ == "__main__":
    asyncio.run(main())
