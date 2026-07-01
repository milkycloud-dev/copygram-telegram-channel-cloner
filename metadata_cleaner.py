import os
import shutil
import random
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
    Safely appends random garbage bytes to the end of a file to modify its hash.
    This effectively bypasses duplicate detection in Telegram.
    
    Args:
        filepath (str): The absolute or relative path to the target file.
        
    Returns:
        str: The path to the modified file.
    """
    try:
        with open(filepath, "ab") as f:
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
    # Skip FFmpeg for MP4/MOV to preserve rotation matrices and exact stream structures.
    # The fallback (byte appending) is 100% safe and effective for hash changing.
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
        
    # 3. Fallback (just alter the hash)
    try:
        if os.path.exists(out_path):
            os.remove(out_path)
        out_path_fallback = filepath + "_cleaned_fallback" + ext
        shutil.copyfile(filepath, out_path_fallback)
        os.remove(filepath)
        final_path = append_random_bytes(out_path_fallback)
        return final_path, t('fallback_success', filename), "warning"
    except Exception:
        return filepath, t('process_err', filename), "error"
