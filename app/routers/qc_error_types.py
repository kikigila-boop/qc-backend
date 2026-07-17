# app/routers/qc_error_types.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.qc_result import QCErrorType

router = APIRouter(prefix="/qc-error-types", tags=["QC Error Types"])

QC_ERROR_SEED = [
    ("Video QC", "Wrong Aspect Ratio", "Rasio layar tidak sesuai standar"),
    ("Video QC", "Black Frame/Bar", "Terdapat frame hitam yang tidak seharusnya"),
    ("Video QC", "Wrong Frame Rate", "Frame rate tidak sesuai spesifikasi"),
    ("Video QC", "Interlacing Artifact", "Terdapat efek interlacing pada video"),
    ("Video QC", "Pixelation/Blocking", "Kualitas video terlihat pecah atau blok"),
    ("Video QC", "Frame Drop/Freeze", "Video tersendat atau frame hilang"),
    ("Video QC", "Color Banding", "Gradasi warna tidak mulus"),
    ("Video QC", "Watermark Error", "Watermark tidak sesuai atau salah posisi"),
    ("Video QC", "Wrong Resolution", "Resolusi video tidak sesuai spesifikasi"),
    ("Video QC", "Letterboxing Error", "Letterbox tidak sesuai"),
    ("Video QC", "Motion Blur Berlebihan", "Blur berlebihan pada gerakan"),
    ("Video QC", "Wrong Episode Content", "Konten tidak sesuai episode yang dimaksud"),
    ("Video QC", "Missing Opening/Ending", "Opening atau ending tidak ada"),
    ("Video QC", "Wrong Duration", "Durasi tidak sesuai spesifikasi"),
    ("Video QC", "Video Corrupt/Artifact", "Video rusak atau ada artefak visual"),
    ("Audio QC", "No Audio", "Tidak ada suara sama sekali"),
    ("Audio QC", "Audio Out of Sync", "Suara tidak sinkron dengan gambar"),
    ("Audio QC", "Distortion/Clipping", "Suara terdistorsi atau terpotong"),
    ("Audio QC", "Audio Channel Error", "Channel audio salah (mono/stereo)"),
    ("Audio QC", "Wrong Language Audio", "Bahasa audio tidak sesuai"),
    ("Audio QC", "Audio Level Too Low", "Volume terlalu kecil"),
    ("Audio QC", "Audio Level Too High", "Volume terlalu besar"),
    ("Audio QC", "Noise/Hiss", "Ada suara noise atau hiss"),
    ("Audio QC", "Audio Cut/Gap", "Audio terpotong tiba-tiba"),
    ("Audio QC", "Missing BGM/SFX", "Music latar atau efek suara hilang"),
    ("Subtitle QC", "No Subtitle", "Subtitle tidak ada"),
    ("Subtitle QC", "Wrong Subtitle Language", "Bahasa subtitle tidak sesuai"),
    ("Subtitle QC", "Subtitle Out of Sync", "Subtitle tidak sinkron dengan dialog"),
    ("Subtitle QC", "Missing Subtitle Lines", "Ada baris subtitle yang hilang"),
    ("Subtitle QC", "Wrong Subtitle Format", "Format subtitle tidak sesuai"),
    ("Subtitle QC", "Subtitle Overlap", "Subtitle saling menimpa"),
    ("Subtitle QC", "Wrong Character Encoding", "Karakter subtitle salah encode"),
    ("Subtitle QC", "Spelling/Grammar Error", "Kesalahan ejaan atau grammar"),
    ("Subtitle QC", "Translation Error", "Terjemahan tidak tepat"),
    ("Subtitle QC", "Subtitle Position Error", "Posisi subtitle salah"),
    ("Metadata QC", "Wrong Title", "Judul tidak sesuai"),
    ("Metadata QC", "Wrong Episode Number", "Nomor episode salah"),
    ("Metadata QC", "Wrong Season Number", "Nomor season salah"),
    ("Metadata QC", "Wrong Genre", "Genre tidak sesuai"),
    ("Metadata QC", "Wrong Description", "Deskripsi atau sinopsis tidak sesuai"),
    ("Metadata QC", "Wrong Cast Info", "Informasi pemain salah"),
    ("Metadata QC", "Wrong Director Info", "Informasi sutradara salah"),
    ("Metadata QC", "Wrong Release Year", "Tahun rilis salah"),
    ("Metadata QC", "Wrong Content Rating", "Rating usia tidak sesuai"),
    ("Metadata QC", "Missing Thumbnail", "Thumbnail tidak ada"),
    ("Branding & Logo", "Wrong Logo Position", "Posisi logo tidak sesuai"),
    ("Branding & Logo", "Logo Missing", "Logo tidak ada"),
    ("Branding & Logo", "Logo Flickering", "Logo berkedip"),
    ("Branding & Logo", "Wrong Copyright Info", "Informasi hak cipta salah"),
    ("Branding & Logo", "Wrong Channel Watermark", "Watermark channel salah"),
    ("Branding & Logo", "Incorrect End Card", "End card tidak sesuai"),
    ("Branding & Logo", "Wrong Bumper", "Bumper pembuka atau penutup salah"),
    ("Branding & Logo", "Missing Disclaimer", "Disclaimer tidak ada"),
    ("Technical", "File Corrupt", "File rusak atau tidak bisa diputar"),
    ("Technical", "Wrong File Format", "Format file tidak sesuai"),
    ("Technical", "Wrong Bitrate", "Bitrate tidak sesuai spesifikasi"),
    ("Technical", "Wrong Codec", "Codec video atau audio tidak sesuai"),
    ("Technical", "Wrong Container", "Container format tidak sesuai"),
    ("Technical", "Encoding Error", "Error saat encoding"),
    ("Technical", "Buffering Issue", "Video sering buffering"),
    ("Technical", "Playback Error", "Error saat pemutaran"),
    ("Content", "Uncut Scene", "Adegan yang seharusnya di-cut masih ada"),
    ("Content", "Missing Content Warning", "Peringatan konten tidak ada"),
    ("Content", "Copyright Issue", "Ada konten bermasalah hak cipta"),
    ("Content", "Missing Scenes", "Ada adegan yang hilang"),
    ("Content", "Wrong Playback Speed", "Kecepatan putar tidak normal"),
    ("Content", "Color Grading Issue", "Color grading tidak sesuai"),
    ("Content", "Aspect Ratio Inconsistency", "Rasio layar berubah-ubah dalam konten"),
    ("Content", "Frame Rate Inconsistency", "Frame rate berubah dalam konten"),
]


def seed_error_types(db: Session):
    if db.query(QCErrorType).count() == 0:
        for cat, name, desc in QC_ERROR_SEED:
            db.add(QCErrorType(category=cat, error_name=name, description=desc))
        db.commit()


@router.get("")
def get_error_types(db: Session = Depends(get_db)):
    seed_error_types(db)
    items = db.query(QCErrorType).order_by(QCErrorType.category, QCErrorType.id).all()
    result: dict = {}
    for item in items:
        result.setdefault(item.category, []).append({
            "id": item.id,
            "error_name": item.error_name,
            "description": item.description,
        })
    return result
