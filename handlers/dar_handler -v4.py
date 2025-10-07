# handlers/dar_handler.py
"""
v4
# handlers/dar_handler.py
komut aciklaması yok (commat_info)> aktif dönemde anlamlı 
# Aiogram 3.x uyumlu
# Proje yedekleme ve komut tarama yardımcı handler
. ile başlayan dosyalar ve __pycache__ gibi klasörler yok sayılır.
/dar → proje ağaç yapısını mesaj olarak gösterir.
/dar k → tüm @router.message(Command(...)) komutlarını bulur
/dar t → proje ağaç yapısı+dosyaların içeriğini birleştirip, her dosya için başlık ekleyerek mesaj halinde gönder.txt dosyası olarak gönderir.
/dar t → Tüm proje (mevcut)
/dar t <dosya> → Sadece belirtilen dosya
/dar t <klasör> → Sadece belirtilen klasördeki .py dosyaları
/dar Z → tüm proje klasörünü .zip dosyası olarak gönderir.
# zaman format: mbot1_0917_2043 (aygün_saaddkika) ESKİ: "%Y%m%d_%H%M%S" = YılAyGün_SaatDakikaSaniye
"""

import logging
import os
import re
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime

from aiogram import Router
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command

logger = logging.getLogger(__name__)

# Router oluştur
router = Router()

# Kök dizin (proje kökü)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = Path(tempfile.gettempdir())
TMP_DIR.mkdir(parents=True, exist_ok=True)
TELEGRAM_NAME = os.getenv("TELEGRAM_NAME", "hbot")
TELEGRAM_MSG_LIMIT = 4000


##----------------------------
# -------------------------------
# 📂 Proje ağaç yapısı üretici
# -------------------------------
def generate_tree(path: Path, prefix: str = "") -> str:
    tree = ""
    entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    for idx, entry in enumerate(entries):
        if entry.name.startswith(".") or entry.name in ["__pycache__"]:
            continue
        connector = "└── " if idx == len(entries) - 1 else "├── "
        tree += f"{prefix}{connector}{entry.name}\n"
        if entry.is_dir():
            extension = "    " if idx == len(entries) - 1 else "│   "
            tree += generate_tree(entry, prefix + extension)
    return tree


# -------------------------------------
# dosya/klasör adını proje içinde tarar /dar t binance
# -------------------------------------
def find_file_or_folder(root_path: Path, target_name: str) -> Path:
    """
    Belirtilen dosya/klasör adını proje içinde arar
    """
    target_name = target_name.lower()
    for path in root_path.rglob("*"):
        if path.name.lower() == target_name and not path.name.startswith("."):
            return path
    return None


# -------------------------------------
# istenilen .py dosyalarını /dar t main.py
# -------------------------------------
def get_py_files_from_path(target_path: Path) -> list:
    """
    Belirtilen yol'daki tüm .py dosyalarını recursive olarak bulur
    """
    py_files = []
    if target_path.is_file() and target_path.suffix == ".py":
        py_files.append(target_path)
    elif target_path.is_dir():
        for py_file in target_path.rglob("*.py"):
            if not py_file.name.startswith(".") and "__pycache__" not in str(py_file):
                py_files.append(py_file)
    return sorted(py_files)



# -------------------------------
# 🔍 handlers içindeki komut tarayıcı
# -------------------------------
def scan_handlers_for_commands():
    commands = {}
    handler_dir = PROJECT_ROOT / "handlers"

    pattern = re.compile(r'@router\.message\(.*Command\(["\'](\w+)["\']')
    for fname in os.listdir(handler_dir):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        fpath = handler_dir / fname
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            matches = pattern.findall(content)
            for cmd in matches:
                commands[f"/{cmd}"] = f"({fname})"
        except Exception:
            continue
    return commands


# -------------------------------
# 🎯 Komut Handler
# -------------------------------
# /dar HANDLER'I
@router.message(Command("dar"))
async def dar_command(message: Message):
    args = message.text.strip().split()[1:]
    mode = args[0].lower() if args else ""
    
    timestamp = datetime.now().strftime("%m%d_%H%M%S")

    # --- Komut Tarama (/dar k)
    if mode == "k":
        scanned = scan_handlers_for_commands()
        lines = [f"{cmd} → {desc}" for cmd, desc in sorted(scanned.items())]
        text = "\n".join(lines) if lines else "❌ Komut bulunamadı."
        await message.answer(f"<pre>{text}</pre>", parse_mode="HTML")
        return


    # --- TXT Kod Birleştir (/dar t) - PROJE AĞAÇ YAPISI EKLENDİ
    # --- TXT Kod Birleştir (/dar t) - YENİ ÖZELLİK EKLENDİ
    if mode == "t":
        target_name = args[1] if len(args) > 1 else None
        
        content_blocks = []

        # Proje ağaç yapısını ekle
        tree_str = generate_tree(PROJECT_ROOT)
        content_blocks.append("📁 PROJE AĞAÇ YAPISI\n")
        content_blocks.append(tree_str)
        content_blocks.append("\n" + "="*50 + "\n")

        if target_name:
            # 🆕 YENİ ÖZELLİK: Belirli dosya/klasör içeriği
            target_path = find_file_or_folder(PROJECT_ROOT, target_name)
            
            if not target_path:
                await message.answer(f"❌ '{target_name}' dosya/klasörü bulunamadı!")
                return
            
            content_blocks.append(f"📁 HEDEF: {target_name}\n")
            content_blocks.append("="*50 + "\n")
            
            py_files = get_py_files_from_path(target_path)
            
            if not py_files:
                await message.answer(f"❌ '{target_name}' içinde .py dosyası bulunamadı!")
                return
            
            for py_file in py_files:
                rel_path = py_file.relative_to(PROJECT_ROOT)
                try:
                    with open(py_file, "r", encoding="utf-8") as f:
                        file_content = f.read()
                    
                    block = (
                        "\n" + "=" * 30 + "\n"
                        f"|| {rel_path.as_posix()} ||\n"
                        + "=" * 30 + "\n"
                        + file_content.strip() + "\n"
                    )
                    content_blocks.append(block)
                except Exception as e:
                    content_blocks.append(f"\n❌ {rel_path} okunamadı: {e}\n")
        
        else:
            # 🎯 MEVCUT: Tüm proje içeriği
            content_blocks.append("📄 TÜM DOSYA İÇERİKLERİ\n")
            content_blocks.append("="*50 + "\n")
            
            for dirpath, _, filenames in os.walk(PROJECT_ROOT):
                for fname in sorted(filenames):
                    if fname.startswith(".") or not fname.endswith(".py"):
                        continue

                    file_path = Path(dirpath) / fname
                    rel_path = file_path.relative_to(PROJECT_ROOT)

                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            file_content = f.read()
                    except Exception:
                        continue

                    block = (
                        "\n" + "=" * 30 + "\n"
                        f"|| {rel_path.as_posix()} ||\n"
                        + "=" * 30 + "\n"
                        + file_content.strip() + "\n"
                    )
                    content_blocks.append(block)

        full_content = "\n".join(content_blocks)

        # Dosya boyutu kontrolü ve gönderim (mevcut kod aynı)
        if len(full_content) > TELEGRAM_MSG_LIMIT:
            txt_path = TMP_DIR / f"{TELEGRAM_NAME}_{timestamp}.txt"
            try:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(full_content)
                await message.answer_document(FSInputFile(str(txt_path)))
            except Exception as e:
                await message.answer(f"Hata oluştu: {e}")
            finally:
                if txt_path.exists():
                    txt_path.unlink()
        else:
            await message.answer(f"<pre>{full_content}</pre>", parse_mode="HTML")
        return
        
        
    # --- ZIP Yedek (/dar Z)
    if mode.upper() == "Z":
        zip_path = TMP_DIR / f"{TELEGRAM_NAME}_{timestamp}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(PROJECT_ROOT):
                    for file in files:
                        if file.startswith(".") or file.endswith((".pyc", ".pyo")):
                            continue
                        file_path = Path(root) / file
                        rel_path = file_path.relative_to(PROJECT_ROOT)
                        try:
                            zipf.write(file_path, rel_path)
                        except Exception:
                            continue
            await message.answer_document(FSInputFile(str(zip_path)))
        except Exception as e:
            await message.answer(f"Hata oluştu: {e}")
        finally:
            if zip_path.exists():
                zip_path.unlink()
        return

    # --- Varsayılan (/dar → ağaç mesaj)
    tree_str = generate_tree(PROJECT_ROOT)
    if len(tree_str) > TELEGRAM_MSG_LIMIT:
        txt_path = TMP_DIR / f"{TELEGRAM_NAME}_{timestamp}.txt"
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(tree_str)
            await message.answer_document(FSInputFile(str(txt_path)))
        except Exception as e:
            await message.answer(f"Hata oluştu: {e}")
        finally:
            if txt_path.exists():
                txt_path.unlink()
    else:
        await message.answer(f"<pre>{tree_str}</pre>", parse_mode="HTML")



