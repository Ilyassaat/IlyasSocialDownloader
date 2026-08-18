import os
import re
import tempfile
import shutil
from flask import Flask, request, jsonify, send_file, render_template

import yt_dlp


app = Flask(__name__)


# =========================================================
# AYARLAR
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Sunucuda FFmpeg PATH'e ekliyse sadece "ffmpeg" yeterlidir.
# Projede ffmpeg klasörü varsa onu da otomatik arıyoruz.
LOCAL_FFMPEG = os.path.join(BASE_DIR, "ffmpeg", "bin")

if os.path.exists(LOCAL_FFMPEG):
    FFMPEG_LOCATION = LOCAL_FFMPEG
else:
    FFMPEG_LOCATION = None


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================

def clean_filename(filename):
    """
    Windows/Linux/macOS için sorun çıkarabilecek karakterleri temizler.
    """

    if not filename:
        filename = "Ilyas Downloader"

    filename = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '', filename)

    filename = filename.strip()

    if not filename:
        filename = "Ilyas Downloader"

    return filename


def get_common_ydl_options():
    """
    Web sunucusunda kullanılacak ortak yt-dlp ayarları.
    """

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": False,
        "nocheckcertificate": True,
    }

    if FFMPEG_LOCATION:
        options["ffmpeg_location"] = FFMPEG_LOCATION

    return options


def get_video_info(url):
    """
    Videonun bilgilerini getirir.
    """

    options = get_common_ydl_options()

    options["skip_download"] = True

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    return info


# =========================================================
# ANA SAYFA
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


# =========================================================
# VIDEO BİLGİSİ
# =========================================================

@app.route("/api/info", methods=["POST"])
def api_info():

    try:

        data = request.get_json(silent=True) or {}

        url = data.get("url", "").strip()

        if not url:
            return jsonify({
                "error": "Video bağlantısı girilmedi."
            }), 400


        info = get_video_info(url)


        duration = info.get("duration")

        thumbnail = info.get("thumbnail")

        title = info.get("title") or "Başlıksız video"

        uploader = info.get("uploader") or ""


        return jsonify({

            "success": True,

            "title": title,

            "thumbnail": thumbnail,

            "duration": duration,

            "uploader": uploader,

            "webpage_url": info.get("webpage_url"),

        })


    except Exception as e:

        return jsonify({

            "error": str(e)

        }), 500


# =========================================================
# VIDEO İNDİRME
# =========================================================

@app.route("/api/download", methods=["POST"])
def api_download():

    temp_dir = None

    try:

        data = request.get_json(silent=True) or {}

        url = data.get("url", "").strip()

        file_format = data.get("format", "mp4")

        quality = str(data.get("quality", "best"))

        bitrate = str(data.get("bitrate", "192"))


        if not url:

            return jsonify({
                "error": "Video bağlantısı girilmedi."
            }), 400


        # -------------------------------------------------
        # FORMAT KONTROLÜ
        # -------------------------------------------------

        if file_format not in ["mp4", "mp3"]:

            file_format = "mp4"


        # -------------------------------------------------
        # GEÇİCİ KLASÖR
        # -------------------------------------------------

        temp_dir = tempfile.mkdtemp(
            prefix="ilyas_downloader_"
        )


        # -------------------------------------------------
        # DOSYA ADI
        # -------------------------------------------------

        info = get_video_info(url)

        original_title = info.get("title") or "Ilyas Downloader"

        original_title = clean_filename(original_title)


        # =================================================
        # MP3
        # =================================================

        if file_format == "mp3":

            output_template = os.path.join(
                temp_dir,
                "%(title)s.%(ext)s"
            )


            ydl_opts = get_common_ydl_options()

            ydl_opts.update({

                "format": "bestaudio/best",

                "outtmpl": output_template,

                "postprocessors": [

                    {
                        "key": "FFmpegExtractAudio",

                        "preferredcodec": "mp3",

                        "preferredquality": bitrate,

                    }

                ],

            })


        # =================================================
        # MP4
        # =================================================

        else:

            output_template = os.path.join(
                temp_dir,
                "%(title)s.%(ext)s"
            )


            if quality == "best":

                video_format = (
                    "bestvideo+bestaudio/"
                    "best"
                )

            else:

                try:

                    height = int(quality)

                except:

                    height = 1080


                video_format = (
                    f"bestvideo[height<={height}]"
                    "+bestaudio/"
                    f"best[height<={height}]"
                )


            ydl_opts = get_common_ydl_options()

            ydl_opts.update({

                "format": video_format,

                "merge_output_format": "mp4",

                "outtmpl": output_template,

            })


        # =================================================
        # İNDİR
        # =================================================

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            ydl.download([url])


        # =================================================
        # DOSYAYI BUL
        # =================================================

        files = []

        for root, dirs, filenames in os.walk(temp_dir):

            for filename in filenames:

                full_path = os.path.join(
                    root,
                    filename
                )

                if os.path.isfile(full_path):

                    files.append(full_path)


        if not files:

            return jsonify({

                "error": "İndirilen dosya bulunamadı."

            }), 500


        # MP3 / MP4 dosyasını bul
        selected_file = None


        for file_path in files:

            ext = os.path.splitext(file_path)[1].lower()

            if file_format == "mp3" and ext == ".mp3":

                selected_file = file_path

                break

            if file_format == "mp4" and ext == ".mp4":

                selected_file = file_path

                break


        if not selected_file:

            selected_file = files[0]


        # =================================================
        # ORİJİNAL BAŞLIK
        # =================================================

        extension = (
            ".mp3"
            if file_format == "mp3"
            else ".mp4"
        )


        final_filename = (
            clean_filename(original_title)
            + extension
        )


        # =================================================
        # DOSYAYI KULLANICIYA GÖNDER
        # =================================================

        response = send_file(

            selected_file,

            as_attachment=True,

            download_name=final_filename,

            mimetype=(
                "audio/mpeg"
                if file_format == "mp3"
                else "video/mp4"
            )

        )


        # =================================================
        # TEMİZLEME
        # =================================================

        @response.call_on_close
        def cleanup():

            try:

                shutil.rmtree(
                    temp_dir,
                    ignore_errors=True
                )

            except:

                pass


        return response


    except Exception as e:

        if temp_dir:

            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )


        return jsonify({

            "error": str(e)

        }), 500


# =========================================================
# SUNUCU
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
