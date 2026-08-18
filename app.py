from flask import Flask, request, jsonify, send_from_directory
import yt_dlp
import os
import re
import uuid
import threading

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# =========================================================
# DOSYA ADI TEMİZLEME
# =========================================================

def clean_filename(name):
    if not name:
        name = "SosyalMedyaVideo"

    # Dosya sistemlerinde sorun çıkaran karakterler
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)

    # Fazla boşlukları düzelt
    name = re.sub(r'\s+', ' ', name).strip()

    # Windows'ta 끝 nokta/boşluk sorununu önle
    name = name.rstrip(". ")

    # Çok uzun dosya adlarını sınırla
    if len(name) > 180:
        name = name[:180].rstrip()

    if not name:
        name = "SosyalMedyaVideo"

    return name


# =========================================================
# YT-DLP TEMEL AYARLARI
# =========================================================

def base_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,

        # Dosyanın başlığı/metadata'sı kullanılacak
        "windowsfilenames": True,
        "restrictfilenames": False,
    }


# =========================================================
# DESTEKLENEN PLATFORM KONTROLÜ
# =========================================================

def detect_platform(url):

    url_lower = url.lower()

    if "instagram.com" in url_lower:
        return "Instagram"

    if "tiktok.com" in url_lower:
        return "TikTok"

    if "facebook.com" in url_lower or "fb.watch" in url_lower:
        return "Facebook"

    return None


# =========================================================
# ANA SAYFA
# =========================================================

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


# =========================================================
# SAĞLIK KONTROLÜ
# =========================================================

@app.route("/api/health")
def health():

    return jsonify({
        "success": True,
        "status": "online",
        "service": "Ilyas Social Downloader",
        "yt_dlp": yt_dlp.version.__version__
    })


# =========================================================
# VİDEO BİLGİLERİ
# =========================================================

@app.route("/api/info", methods=["POST"])
def video_info():

    try:

        data = request.get_json(silent=True) or {}

        url = data.get("url", "").strip()

        if not url:
            return jsonify({
                "success": False,
                "error": "Lütfen bir bağlantı gir."
            }), 400

        platform = detect_platform(url)

        if not platform:
            return jsonify({
                "success": False,
                "error": "Şimdilik Instagram, TikTok ve Facebook bağlantıları destekleniyor."
            }), 400

        options = base_options()
        options["skip_download"] = True

        with yt_dlp.YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )

        title = (
            info.get("description")
            or info.get("title")
            or info.get("fulltitle")
            or "Sosyal Medya Videosu"
        )

        # Açıklama aşırı uzunsa ilk anlamlı kısmı kullan
        title = title.strip()

        if len(title) > 180:
            title = title[:180].rstrip()

        title = clean_filename(title)

        formats = []

        for fmt in info.get("formats", []):

            height = fmt.get("height")

            if not height:
                continue

            ext = fmt.get("ext")

            if ext not in ["mp4", "webm", "mkv"]:
                continue

            formats.append({
                "format_id": fmt.get("format_id"),
                "height": height,
                "width": fmt.get("width"),
                "ext": ext,
                "fps": fmt.get("fps"),
                "filesize": (
                    fmt.get("filesize")
                    or fmt.get("filesize_approx")
                ),
                "has_audio": (
                    fmt.get("acodec")
                    not in [None, "none"]
                )
            })

        # Kaliteye göre tekilleştir
        unique = {}

        for fmt in formats:

            key = (
                fmt["height"],
                fmt["ext"],
                fmt["has_audio"]
            )

            if key not in unique:
                unique[key] = fmt

        formats = list(unique.values())

        formats.sort(
            key=lambda x: (
                x.get("height") or 0,
                x.get("fps") or 0
            ),
            reverse=True
        )

        # Kullanıcıya uygun kalite listesi
        qualities = []

        seen_heights = set()

        for fmt in formats:

            height = fmt.get("height")

            if height in seen_heights:
                continue

            seen_heights.add(height)

            qualities.append({
                "height": height,
                "label": f"{height}p",
                "format_id": fmt.get("format_id")
            })

        return jsonify({
            "success": True,
            "platform": platform,
            "title": title,
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "description": info.get("description"),
            "qualities": qualities,
            "formats": formats
        })

    except Exception as e:

        print("INFO ERROR:", repr(e))

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================================================
# İNDİRME
# =========================================================

@app.route("/api/download", methods=["POST"])
def download():

    try:

        data = request.get_json(silent=True) or {}

        url = data.get("url", "").strip()

        media_type = data.get(
            "type",
            "mp4"
        ).lower()

        quality = data.get(
            "quality"
        )

        bitrate = data.get(
            "bitrate",
            "192"
        )

        if not url:
            return jsonify({
                "success": False,
                "error": "Bağlantı bulunamadı."
            }), 400

        platform = detect_platform(url)

        if not platform:
            return jsonify({
                "success": False,
                "error": "Desteklenmeyen platform."
            }), 400

        # -------------------------------------------------
        # ÖNCE METADATA
        # -------------------------------------------------

        info_options = base_options()
        info_options["skip_download"] = True

        with yt_dlp.YoutubeDL(info_options) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )

        # -------------------------------------------------
        # ORİJİNAL BAŞLIK / AÇIKLAMA
        # -------------------------------------------------

        original_title = (
            info.get("description")
            or info.get("title")
            or info.get("fulltitle")
            or "Sosyal Medya Videosu"
        )

        filename = clean_filename(
            original_title
        )

        # -------------------------------------------------
        # AYNI DOSYA ADI VARSA ÇAKIŞMAYI ÖNLE
        # -------------------------------------------------

        job_id = uuid.uuid4().hex[:8]

        if media_type == "mp3":
            extension = "mp3"
        else:
            extension = "mp4"

        output_template = os.path.join(
            DOWNLOAD_DIR,
            f"{filename}_{job_id}.%(ext)s"
        )

        options = base_options()

        options.update({
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "overwrites": False,
            "quiet": False
        })

        # -------------------------------------------------
        # MP3
        # -------------------------------------------------

        if media_type == "mp3":

            options["format"] = "bestaudio/best"

            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(bitrate)
                }
            ]

        # -------------------------------------------------
        # MP4
        # -------------------------------------------------

        else:

            if quality:

                try:
                    height = int(quality)

                    options["format"] = (
                        f"bestvideo[height<={height}]"
                        f"+bestaudio/"
                        f"best[height<={height}]/"
                        f"best"
                    )

                except Exception:

                    options["format"] = (
                        "bestvideo+bestaudio/best"
                    )

            else:

                options["format"] = (
                    "bestvideo+bestaudio/best"
                )

        # -------------------------------------------------
        # İNDİR
        # -------------------------------------------------

        print("")
        print("================================")
        print("DOWNLOAD")
        print("Platform:", platform)
        print("Title:", original_title)
        print("Type:", media_type)
        print("Quality:", quality)
        print("Bitrate:", bitrate)
        print("================================")

        with yt_dlp.YoutubeDL(options) as ydl:

            ydl.download([url])

        # -------------------------------------------------
        # DOSYAYI BUL
        # -------------------------------------------------

        files = os.listdir(DOWNLOAD_DIR)

        matching = []

        for file in files:

            if job_id not in file:
                continue

            if file.endswith(".part"):
                continue

            if file.endswith(".ytdl"):
                continue

            full_path = os.path.join(
                DOWNLOAD_DIR,
                file
            )

            if os.path.isfile(full_path):
                matching.append(file)

        if not matching:

            return jsonify({
                "success": False,
                "error": "İndirilen dosya bulunamadı."
            }), 500

        final_file = matching[0]

        # -------------------------------------------------
        # KULLANICIYA GÖSTERİLECEK İSİM
        # -------------------------------------------------

        if media_type == "mp3":

            visible_filename = (
                filename + ".mp3"
            )

        else:

            visible_filename = (
                filename + ".mp4"
            )

        return jsonify({
            "success": True,
            "platform": platform,
            "title": original_title,
            "filename": visible_filename,
            "download_url": (
                "/download-file/"
                + final_file
            )
        })

    except Exception as e:

        print("DOWNLOAD ERROR:", repr(e))

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================================================
# DOSYA SERVİSİ
# =========================================================

@app.route("/download-file/<path:filename>")
def download_file(filename):

    return send_from_directory(
        DOWNLOAD_DIR,
        filename,
        as_attachment=True
    )


# =========================================================
# UYGULAMA
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
