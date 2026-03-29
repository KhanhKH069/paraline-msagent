"""
Vietnamese Text Cleaners
Chuẩn hóa văn bản tiếng Việt trước khi đưa vào model.
Theo nguyên tắc: máy không tự hiểu số và chữ viết tắt.
"""

import re
import unicodedata
from num2words import num2words


# ─── Từ điển viết tắt tiếng Việt phổ biến ───────────────────────────────────

ABBREVIATIONS_VI = {
    r'\bTP\.HCM\b': 'thành phố Hồ Chí Minh',
    r'\bHN\b': 'Hà Nội',
    r'\bTP\b': 'thành phố',
    r'\bQ\.\s*(\d+)': lambda m: f"quận {num_to_words_vi(m.group(1))}",
    r'\bP\.\s*(\d+)': lambda m: f"phường {num_to_words_vi(m.group(1))}",
    r'\bGS\b': 'giáo sư',
    r'\bPGS\b': 'phó giáo sư',
    r'\bTS\b': 'tiến sĩ',
    r'\bThS\b': 'thạc sĩ',
    r'\bBs\b': 'bác sĩ',
    r'\bkm\b': 'ki-lô-mét',
    r'\bkg\b': 'ki-lô-gam',
    r'\bm\b(?=\s)': 'mét',
    r'\bcm\b': 'xăng-ti-mét',
    r'\bmm\b': 'mi-li-mét',
    r'\bkm/h\b': 'ki-lô-mét trên giờ',
    r'\bVNĐ\b': 'đồng',
    r'\bUSD\b': 'đô la Mỹ',
    r'\bVN\b': 'Việt Nam',
    r'\bCNXHCN\b': 'chủ nghĩa xã hội chủ nghĩa',
    r'\bĐCS\b': 'Đảng Cộng sản',
    r'\bNXB\b': 'nhà xuất bản',
    r'\bPGĐ\b': 'phó giám đốc',
    r'\bGĐ\b': 'giám đốc',
    r'\bBT\b': 'bộ trưởng',
    r'\bTBT\b': 'tổng bí thư',
    r'\bCT\b': 'chủ tịch',
    r'\bPCT\b': 'phó chủ tịch',
    r'\bTT\b': 'thủ tướng',
    r'\bPTT\b': 'phó thủ tướng',
    r'\bSL\b': 'số lượng',
    r'\bDT\b': 'diện tích',
    r'\btầng\s*(\d+)': lambda m: f"tầng {num_to_words_vi(m.group(1))}",
    r'\bĐT\b': 'điện thoại',
    r'\bCTy\b': 'công ty',
    r'\bCty\b': 'công ty',
    r'\bHTX\b': 'hợp tác xã',
}

# ─── Chuyển số → chữ tiếng Việt ─────────────────────────────────────────────

ONES_VI = ['', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín']
TENS_VI = ['', 'mười', 'hai mươi', 'ba mươi', 'bốn mươi', 'năm mươi',
           'sáu mươi', 'bảy mươi', 'tám mươi', 'chín mươi']


def num_to_words_vi(n_str: str) -> str:
    """Chuyển chuỗi số nguyên sang tiếng Việt."""
    try:
        n = int(n_str.replace(',', '').replace('.', ''))
    except ValueError:
        return n_str

    if n == 0:
        return 'không'
    if n < 0:
        return 'âm ' + num_to_words_vi(str(-n))

    # Dùng num2words với ngôn ngữ Vietnamese (fallback sang vi)
    try:
        result = num2words(n, lang='vi')
        return result
    except Exception:
        return str(n)


def normalize_numbers(text: str) -> str:
    """Chuyển tất cả số trong văn bản sang chữ tiếng Việt."""

    # Phần trăm: 100% → một trăm phần trăm
    text = re.sub(
        r'(\d[\d,.]*)%',
        lambda m: num_to_words_vi(m.group(1).replace(',', '')) + ' phần trăm',
        text
    )

    # Tiền VNĐ: 1.000.000đ → một triệu đồng
    text = re.sub(
        r'(\d[\d.,]*)\s*(?:đồng|đ|VNĐ|VND)',
        lambda m: num_to_words_vi(m.group(1).replace('.', '').replace(',', '')) + ' đồng',
        text
    )

    # Năm (4 chữ số riêng lẻ): 2024 → hai nghìn không trăm hai mươi bốn
    text = re.sub(
        r'\b(19|20)\d{2}\b',
        lambda m: num_to_words_vi(m.group(0)),
        text
    )

    # Số thứ tự: thứ 3 → thứ ba
    text = re.sub(
        r'\bthứ\s+(\d+)',
        lambda m: 'thứ ' + num_to_words_vi(m.group(1)),
        text
    )

    # Số chung còn lại
    text = re.sub(
        r'\b\d+(?:[.,]\d+)*\b',
        lambda m: num_to_words_vi(m.group(0)),
        text
    )

    return text


def normalize_abbreviations(text: str) -> str:
    """Mở rộng viết tắt tiếng Việt."""
    for pattern, replacement in ABBREVIATIONS_VI.items():
        if callable(replacement):
            text = re.sub(pattern, replacement, text)
        else:
            text = re.sub(pattern, replacement, text)
    return text


def normalize_punctuation(text: str) -> str:
    """Chuẩn hóa dấu câu."""
    # Dấu chấm lửng
    text = re.sub(r'\.{3,}', '...', text)
    text = re.sub(r'…', '...', text)

    # Khoảng trắng dư
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s([.,;:!?])', r'\1', text)

    # Dấu ngoặc kép
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")

    return text.strip()


def normalize_unicode(text: str) -> str:
    """Chuẩn hóa Unicode NFC cho tiếng Việt có dấu."""
    return unicodedata.normalize('NFC', text)


def remove_special_symbols(text: str) -> str:
    """Xóa ký tự đặc biệt không cần thiết."""
    # Giữ lại chữ, số, dấu câu cơ bản, dấu tiếng Việt
    text = re.sub(r'[^\w\s\u00C0-\u024F\u1E00-\u1EFF.,;:!?\-\'"()/]', ' ', text)
    return text


# ─── Pipeline chính ──────────────────────────────────────────────────────────

def vietnamese_cleaners(text: str) -> str:
    """
    Pipeline chuẩn hóa văn bản tiếng Việt đầy đủ.
    Thứ tự xử lý quan trọng — không đổi chỗ.
    """
    text = normalize_unicode(text)
    text = normalize_abbreviations(text)
    text = normalize_numbers(text)
    text = normalize_punctuation(text)
    text = remove_special_symbols(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def basic_cleaners(text: str) -> str:
    """Cleaner tối giản — chỉ lowercase và trim khoảng trắng."""
    return re.sub(r'\s+', ' ', text).strip().lower()


# ─── Registry ────────────────────────────────────────────────────────────────

CLEANER_MAP = {
    'vietnamese_cleaners': vietnamese_cleaners,
    'basic_cleaners': basic_cleaners,
}


def clean_text(text: str, cleaner_names: list) -> str:
    """Áp dụng nhiều cleaner theo thứ tự."""
    for name in cleaner_names:
        cleaner = CLEANER_MAP.get(name)
        if cleaner is None:
            raise ValueError(f"Cleaner không tồn tại: {name}")
        text = cleaner(text)
    return text


# ─── Test nhanh ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    test_cases = [
        "Giá nhà tại TP.HCM tăng lên 5.000.000.000đ trong năm 2024.",
        "GS.TS Nguyễn Văn A đã đạt 95% kết quả trong thí nghiệm.",
        "Tốc độ tối đa là 120km/h trên quốc lộ.",
        "Trời ơi! Sao hôm nay lại mưa to thế...",
        "P.15, Q.10, TP.HCM là địa chỉ của công ty.",
    ]

    print("=== Vietnamese Text Normalization Test ===\n")
    for t in test_cases:
        result = vietnamese_cleaners(t)
        print(f"IN : {t}")
        print(f"OUT: {result}")
        print()
