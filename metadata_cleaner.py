import os
import shutil
import random
import struct
import subprocess
from i18n import t

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_PATH = "ffmpeg"

def append_random_bytes(filepath: str) -> str:
    """
    Appends data to the end of a file to modify its hash, bypassing
    Telegram duplicate detection.
    
    For MP4/MOV/M4V/M4A files, appends a valid 'free' atom (an empty
    padding box defined by the ISO BMFF spec). All MP4 parsers,
    including Telethon's internal prober, will simply skip it,
    keeping the container perfectly valid.
    
    For all other formats, appends raw random bytes (harmless for
    non-box-structured containers).
    
    Args:
        filepath (str): The absolute or relative path to the target file.
        
    Returns:
        str: The path to the modified file.
    """
    try:
        ext = os.path.splitext(filepath)[1].lower()
        with open(filepath, "ab") as f:
            if ext in ('.mp4', '.mov', '.m4v', '.m4a'):
                # Write a valid ISO BMFF 'free' atom:
                #   4 bytes — atom size (big-endian uint32)
                #   4 bytes — atom type ('free')
                #   N bytes — random padding data
                padding = os.urandom(random.randint(16, 128))
                atom_size = 8 + len(padding)
                f.write(struct.pack('>I', atom_size) + b'free' + padding)
            else:
                f.write(os.urandom(random.randint(16, 128)))
        return filepath
    except Exception as e:
        print(t('hash_mod_err', str(e)))
        return filepath

def _clean_image(filepath: str, out_path: str) -> bool:
    """
    Cleans EXIF metadata from an image using Pillow.
    
    Args:
        filepath (str): The path to the original image.
        out_path (str): The path where the cleaned image should be saved.
        
    Returns:
        bool: True if cleaning was successful, False otherwise.
    """
    if not Image: return False
    try:
        with Image.open(filepath) as img:
            image_without_exif = Image.new(img.mode, img.size)
            image_without_exif.paste(img)
            
            # Save preserving format, if RGBA but saving as JPEG, convert to RGB
            save_format = img.format if img.format else "JPEG"
            if save_format == "JPEG" and image_without_exif.mode in ("RGBA", "P"):
                image_without_exif = image_without_exif.convert("RGB")
                
            image_without_exif.save(out_path, format=save_format)
        return True
    except Exception as e:
        print(t('pillow_err', str(e)))
        return False

def clean_file(filepath: str) -> tuple:
    """
    Applies lossless metadata cleaning for media files.
    Tries Pillow for images, FFmpeg for videos/audio, and falls back to byte appending.
    
    Args:
        filepath (str): The path to the file to clean.
        
    Returns:
        tuple: (cleaned_path, log_message, status)
    """
    ext = os.path.splitext(filepath)[1].lower()
    out_path = filepath + "_cleaned" + ext
    filename = os.path.basename(filepath)
    
    # 1. Attempt to clean photo via Pillow
    is_image = ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')
    if is_image and _clean_image(filepath, out_path):
        os.remove(filepath)
        final_path = append_random_bytes(out_path)
        return final_path, t('pillow_success', filename), "success"
    
    # 2. Clean video/audio via FFmpeg (limited to 1 thread for low RAM usage)
    # Skip FFmpeg for MP4/MOV to preserve rotation matrices, stream structure,
    # and moov atom layout. Instead, we append a valid 'free' atom (see step 3)
    # which safely changes the hash without touching the container.
    if ext not in ('.mp4', '.mov'):
        try:
            import uuid
            import subprocess
            import re
            
            # Probe the real format of the file to prevent muxer errors on wrong extensions
            probe_cmd = [FFMPEG_PATH, "-i", filepath]
            probe_res = subprocess.run(probe_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
            match = re.search(r"Input #0, ([^,]+),", probe_res.stderr)
            
            cmd = [
                FFMPEG_PATH,
                "-y",
                "-threads", "1",
                "-i", filepath,
                "-map", "0",
                "-map_metadata", "-1",
                "-c", "copy",
                "-metadata", f"comment={uuid.uuid4().hex}"
            ]
            
            # Ensure faststart for video files so Telegram can stream them
            if ext in ('.mp4', '.mov'):
                cmd.extend(["-movflags", "+faststart"])
                
            cmd.append(out_path)
    
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # If it fails, try to force the probed format (fixes OGG inside MP3 issues)
            if result.returncode != 0 and match:
                fmt_list = match.group(1)
                fmt = "mp4" if "mp4" in fmt_list else "ogg" if "ogg" in fmt_list else fmt_list.split(",")[0].strip()
                
                cmd_fallback = [
                    FFMPEG_PATH, "-y", "-threads", "1", "-i", filepath,
                    "-map", "0", "-map_metadata", "-1", "-c", "copy",
                    "-metadata", f"comment={uuid.uuid4().hex}",
                    "-f", fmt
                ]
                if ext in ('.mp4', '.mov'):
                    cmd_fallback.extend(["-movflags", "+faststart"])
                cmd_fallback.append(out_path)
                
                result = subprocess.run(cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
            if result.returncode == 0 and os.path.exists(out_path):
                os.remove(filepath)
                # FFMPEG already changes hash securely, no need to append random bytes
                return out_path, t('ffmpeg_success', filename), "success"
                
        except Exception as e:
            pass
        
    # 3. Direct hash alteration (primary method for MP4/MOV)
    # For MP4/MOV this is the INTENDED path, not a fallback.
    # append_random_bytes uses a valid 'free' atom for these formats.
    try:
        if os.path.exists(out_path):
            os.remove(out_path)
        final_path = append_random_bytes(filepath)
        is_video_direct = ext in ('.mp4', '.mov')
        status = "success" if is_video_direct else "warning"
        msg = t('ffmpeg_success', filename) if is_video_direct else t('fallback_success', filename)
        return final_path, msg, status
    except Exception:
        return filepath, t('process_err', filename), "error"


def generate_thumbnail(video_path: str) -> str | None:
    """
    Extracts a single frame from a video at ~1 second mark and saves it as
    a JPEG thumbnail. This is used to provide Telegram with a preview image
    during upload, preventing the "no preview / white flash" issue.
    
    Args:
        video_path (str): Path to the video file.
        
    Returns:
        str | None: Path to the generated thumbnail JPEG, or None on failure.
    """
    thumb_path = video_path + "_thumb.jpg"
    try:
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-i", video_path,
            "-ss", "00:00:01",       # seek to 1 second
            "-vframes", "1",         # extract 1 frame
            "-q:v", "5",             # JPEG quality (lower = better, 2-5 is good)
            "-vf", "scale='min(320,iw)':-1",  # max 320px wide, keep aspect ratio
            thumb_path
        ]
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15
        )
        if result.returncode == 0 and os.path.exists(thumb_path):
            return thumb_path
    except Exception:
        pass
    
    # Cleanup on failure
    try:
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
    except Exception:
        pass
    return None
