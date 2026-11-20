import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from .config import Problem, binary

EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
INPUT_OPTIONS = ["-protocol_whitelist", "file", "-format_whitelist", "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm"]
PRESETS = {"preview": (540, 960), "720p": (720, 1280), "1080p": (1080, 1920)}


def capture(args, timeout=15):
    return subprocess.run(
        args, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
        stdin=subprocess.DEVNULL, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    ).stdout


def local_source(value):
    candidate = Path(value).expanduser()
    windows_path = str(candidate).replace("/", "\\")
    if not candidate.is_absolute() or windows_path.startswith("\\\\") or candidate.suffix.lower() not in EXTENSIONS:
        raise Problem("INVALID_SOURCE", "Selecione um MP4, MOV, MKV ou WEBM em um disco local.")
    try:
        path = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise Problem("SOURCE_UNAVAILABLE", "O vídeo foi movido ou está indisponível. Localize o arquivo original.") from error
    resolved = str(path).replace("/", "\\")
    if resolved.startswith("\\\\") or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
        raise Problem("PATH_NOT_ALLOWED", "Selecione um arquivo de vídeo em um disco local.")
    return path


def probe(path):
    try:
        raw = json.loads(capture([
            binary("ffprobe"), "-v", "error", *INPUT_OPTIONS,
            "-show_format", "-show_streams", "-of", "json", str(path),
        ]))
        streams, fmt = raw["streams"], raw["format"]
        videos = [s for s in streams if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")]
        video = videos[0]
        audio = next((s for s in streams if s["codec_type"] == "audio"), None)
        duration_ms = round(float(fmt.get("duration") or video["duration"]) * 1000)
        if duration_ms <= 0:
            raise ValueError("duration")
        fps = float(Fraction(video["avg_frame_rate"])) if video.get("avg_frame_rate") not in (None, "0/0") else None
        width, height = video["width"], video["height"]
        sar_value = video.get("sample_aspect_ratio", "1:1").replace(":", "/")
        sar = Fraction(sar_value) if sar_value not in ("N/A", "0/1") else 1
        rotation = next((item["rotation"] for item in video.get("side_data_list", []) if "rotation" in item), 0)
        display_aspect = float(width * sar / height)
        if rotation % 180 == 90:
            width, height = height, width
            display_aspect = 1 / display_aspect
        if not math.isfinite(display_aspect) or not .02 <= display_aspect <= 50:
            raise ValueError("aspect")
        return {
            "duration_ms": duration_ms, "width": width, "height": height, "fps": fps,
            "video_codec": video.get("codec_name"), "has_audio": audio is not None,
            "audio_codec": audio.get("codec_name") if audio else None, "size": path.stat().st_size,
            "video_index": video["index"], "audio_index": audio["index"] if audio else None,
            "display_aspect": display_aspect, "format": fmt.get("format_name"),
        }
    except (subprocess.SubprocessError, ValueError, OverflowError, KeyError, IndexError, OSError, ZeroDivisionError) as error:
        raise Problem("UNSUPPORTED_MEDIA", "O FFprobe não encontrou um vídeo válido com duração conhecida.") from error


def disk(path, required):
    if shutil.disk_usage(path).free < required:
        raise Problem("DISK_FULL", "Espaço livre insuficiente. Libere espaço e tente novamente.")


def discard_cache(path):
    if path is not None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as error:
            # A video player can still have the previous preview open on Windows.
            logging.getLogger("clip-factory").info("cache cleanup skipped: %s", type(error).__name__)


def ffmpeg(*args):
    return [binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", *map(str, args)]


def extract(task, source, metadata, output):
    disk(output.parent, metadata["duration_ms"] * 32 + 32_000_000)
    task.command(ffmpeg(
        *INPUT_OPTIONS, "-copyts", "-start_at_zero", "-i", source, "-map", f"0:{metadata['audio_index']}",
        "-vn", "-af", "aresample=async=1:first_pts=0", "-ar", 16000, "-ac", 1, "-c:a", "pcm_s16le", output,
    ))


def ass_time(ms, round_up=False):
    count = (ms + (9 if round_up else 0)) // 10
    return f"{count // 360000}:{count // 6000 % 60:02}:{count // 100 % 60:02}.{count % 100:02}"


def write_ass(path, cues, color):
    primary = "&H0000FFFF" if color == "yellow" else "&H00FFFFFF"
    highlight = "&HFFFF24&" if color == "yellow" else "&H24DCFF&"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 540
PlayResY: 960
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,29,{primary},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,30,30,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []

    def dialogue(start, end, text):
        left, right = ass_time(start, True), ass_time(end, True)
        if left != right:
            text = r"\N".join(text.splitlines())
            lines.append(f"Dialogue: 0,{left},{right},Default,,0,0,0,,{text}")

    for cue in cues:
        text = cue["text"].upper().replace(chr(92), chr(65340)).replace("{", "｛").replace("}", "｝")
        start, end = cue["start_ms"], cue["end_ms"]
        tokens = list(re.finditer(r"\S+", text))
        timing = cue.get("word_times", [])
        cursor = start
        if len(tokens) == len(timing):
            for token, (left, right) in zip(tokens, timing):
                left, right = max(cursor, left), min(end, right)
                if right <= left:
                    continue
                if cursor < left:
                    dialogue(cursor, left, text)
                colored = text[:token.start()] + r"{\1c" + highlight + "}" + token[0] + r"{\r}" + text[token.end():]
                dialogue(left, right, colored)
                cursor = right
        if cursor < end:
            dialogue(cursor, end, text)
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def encoder_available(name):
    try:
        capture(ffmpeg("-f", "lavfi", "-i", "color=s=256x256:r=30", "-frames:v", 1, "-c:v", name, "-f", "null", "-"))
        return True
    except (Problem, subprocess.SubprocessError, OSError):
        return False


def visual_effects(clip, cues, has_audio, width, height, duration):
    mode = clip["effects"]
    filters = []
    if mode == "motion" or (mode == "auto" and duration >= 8000 and len(cues) >= 2):
        if clip["framing"] == "fit":
            # Start slightly inset and finish at full size to preserve every source edge.
            step = max(2, round(width * .045 / 18) * 2)
            padded_w, padded_h = width + 9 * step, height + 16 * step
            filters.append(f"pad={padded_w}:{padded_h}:(ow-iw)/2:(oh-ih)/2:black")
            zoom = padded_w / width - 1
        else:
            zoom = .045
        ramp_frames = max(1, round(duration * .03) - 1)
        filters.append(f"zoompan=z='1+{zoom:.6f}*min(on/{ramp_frames},1)':"
                       f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps=30")
    if mode in {"auto", "fade"} and duration >= 1500:
        if mode == "fade" or not has_audio:
            lead = tail = 220
        elif cues and all(cue.get("word_times") for cue in cues):
            lead = min(220, min(cue["start_ms"] for cue in cues))
            tail = min(220, duration - max(cue["end_ms"] for cue in cues))
        else:
            lead = tail = 0
        if lead >= 130:
            filters.append(f"fade=t=in:d={lead / 1000:.3f}")
        if tail >= 130:
            filters.append(f"fade=t=out:st={(duration - tail) / 1000:.3f}:d={tail / 1000:.3f}")
    return filters


def render(task, source, metadata, clip, cues, output, preset, prefer_gpu=False):
    width, height = PRESETS[preset]
    duration = clip["end_ms"] - clip["start_ms"]
    aspect = metadata["display_aspect"]
    if clip["framing"] == "fill":
        scaled_w = max(width, math.ceil(height * aspect / 2) * 2)
        scaled_h = max(height, math.ceil(width / aspect / 2) * 2)
        x = round((scaled_w - width) * clip["center_x"] / 2) * 2
        frame = f"crop={width}:{height}:{x}:(ih-oh)/2"
    else:
        scaled_w = max(2, min(width, round(height * aspect / 2) * 2))
        scaled_h = max(2, min(height, round(width / aspect / 2) * 2))
        frame = f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    filters = [f"scale={scaled_w}:{scaled_h}", "setsar=1", frame, "fps=30"]
    filters.extend(visual_effects(clip, cues, metadata["has_audio"], width, height, duration))
    disk(output.parent, max(64_000_000, duration * 1500))
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".clip-render-") as scratch:
        base = Path(scratch)
        if cues:
            write_ass(base / "captions.ass", cues, clip["caption_style"])
            filters.append("ass=captions.ass")
        temp = base / "render.mp4"
        audio = ["-map", f"0:{metadata['audio_index']}", "-c:a", "aac", "-b:a", "160k"] if metadata["has_audio"] else ["-an"]
        base_args = [
            "-progress", "pipe:1", "-filter_threads", "2", *INPUT_OPTIONS, "-ss", f"{clip['start_ms'] / 1000:.3f}",
            "-i", source, "-t", f"{duration / 1000:.3f}", "-map", f"0:{metadata['video_index']}",
            *audio, "-vf", ",".join(filters), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-map_metadata", "-1", "-y",
        ]
        last = -1

        def progress(line):
            nonlocal last
            if not line.startswith("out_time_us=") or not line[12:].lstrip("-").isdigit():
                return
            current = min(99, max(0, int(line[12:]) // (duration * 10)))
            if current > last:
                last = current
                task.update(progress=current / 100)

        accelerated = prefer_gpu and encoder_available("h264_nvenc")
        if accelerated:
            try:
                task.command(ffmpeg(*base_args, "-c:v", "h264_nvenc", "-preset", "p4", "-cq", 22, temp), cwd=base, on_line=progress)
            except Problem as error:
                if error.code != "FFMPEG_FAILED":
                    raise
                accelerated = False
        if not accelerated:
            if prefer_gpu:
                task.update(message="NVENC indisponível. Renderizando em CPU.")
            task.command(ffmpeg(*base_args, "-c:v", "libx264", "-threads", 4, "-preset", "veryfast", "-crf", 22, temp),
                         cwd=base, on_line=progress)
        result = probe(temp)
        if (result["width"], result["height"], result["fps"], result["video_codec"]) != (width, height, 30, "h264"):
            raise Problem("FFMPEG_FAILED", "A saída não passou na validação de formato.")
        if abs(result["duration_ms"] - duration) > 150 or result["audio_codec"] != ("aac" if audio[0] == "-map" else None):
            raise Problem("FFMPEG_FAILED", "A saída não passou na validação de duração ou áudio.")
        task.check()
        if preset == "preview":
            temp.replace(output)
        else:
            try:
                if os.name == "nt":
                    temp.rename(output)
                else:
                    os.link(temp, output)
            except FileExistsError as error:
                raise Problem("OUTPUT_EXISTS", "Já existe um arquivo com esse nome. Escolha outro nome ou pasta.") from error
            except OSError as error:
                raise Problem("OUTPUT_UNAVAILABLE", "Não foi possível gravar o MP4 na pasta escolhida.") from error
        return {"path": str(output), "size": result["size"], "duration_ms": result["duration_ms"],
                "encoder": "h264_nvenc" if accelerated else "libx264"}


def thumbnail(task, source, metadata, output, milliseconds=None):
    at = min(1000, metadata["duration_ms"] // 2) if milliseconds is None else milliseconds
    task.command(ffmpeg(
        *INPUT_OPTIONS, "-ss", f"{at / 1000:.3f}", "-i", source,
        "-map", f"0:{metadata['video_index']}", "-frames:v", 1, "-vf", "scale=480:-2", "-threads", 1,
        "-update", 1, "-y", output,
    ))
