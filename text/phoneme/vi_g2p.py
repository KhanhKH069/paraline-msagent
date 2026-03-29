"""
Vietnamese G2P — Grapheme-to-Phoneme Conversion
Chuyển văn bản tiếng Việt → chuỗi âm vị + thanh điệu.

Tiếng Việt là ngôn ngữ đơn lập, mỗi âm tiết = 1 từ tố.
Cấu trúc âm tiết: (âm đầu) + (âm đệm) + âm chính + (âm cuối) + thanh điệu
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ─── Bảng thanh điệu ─────────────────────────────────────────────────────────

TONE_MAP = {
    # (ký tự có dấu) → (ký tự gốc, mã thanh)
    # Thanh ngang (0): không dấu
    # Thanh huyền (1): dấu huyền `
    # Thanh sắc (2): dấu sắc ´
    # Thanh hỏi (3): dấu hỏi ?
    # Thanh ngã (4): dấu ngã ~
    # Thanh nặng (5): dấu nặng .

    'à': ('a', 1), 'á': ('a', 2), 'ả': ('a', 3), 'ã': ('a', 4), 'ạ': ('a', 5),
    'ầ': ('â', 1), 'ấ': ('â', 2), 'ẩ': ('â', 3), 'ẫ': ('â', 4), 'ậ': ('â', 5),
    'ằ': ('ă', 1), 'ắ': ('ă', 2), 'ẳ': ('ă', 3), 'ẵ': ('ă', 4), 'ặ': ('ă', 5),
    'è': ('e', 1), 'é': ('e', 2), 'ẻ': ('e', 3), 'ẽ': ('e', 4), 'ẹ': ('e', 5),
    'ề': ('ê', 1), 'ế': ('ê', 2), 'ể': ('ê', 3), 'ễ': ('ê', 4), 'ệ': ('ê', 5),
    'ì': ('i', 1), 'í': ('i', 2), 'ỉ': ('i', 3), 'ĩ': ('i', 4), 'ị': ('i', 5),
    'ò': ('o', 1), 'ó': ('o', 2), 'ỏ': ('o', 3), 'õ': ('o', 4), 'ọ': ('o', 5),
    'ồ': ('ô', 1), 'ố': ('ô', 2), 'ổ': ('ô', 3), 'ỗ': ('ô', 4), 'ộ': ('ô', 5),
    'ờ': ('ơ', 1), 'ớ': ('ơ', 2), 'ở': ('ơ', 3), 'ỡ': ('ơ', 4), 'ợ': ('ơ', 5),
    'ù': ('u', 1), 'ú': ('u', 2), 'ủ': ('u', 3), 'ũ': ('u', 4), 'ụ': ('u', 5),
    'ừ': ('ư', 1), 'ứ': ('ư', 2), 'ử': ('ư', 3), 'ữ': ('ư', 4), 'ự': ('ư', 5),
    'ỳ': ('y', 1), 'ý': ('y', 2), 'ỷ': ('y', 3), 'ỹ': ('y', 4), 'ỵ': ('y', 5),
}

TONE_NAMES = ['ngang', 'huyen', 'sac', 'hoi', 'nga', 'nang']

# ─── Bảng âm đầu (initial consonants) ───────────────────────────────────────

INITIALS = {
    'ngh': 'NG',   # phải kiểm tra trước 'ng'
    'gh': 'G',
    'gi': 'Z',     # gi- đọc như /z/
    'ch': 'C',
    'kh': 'KH',
    'ng': 'NG',
    'nh': 'NH',
    'ph': 'F',
    'qu': 'KW',
    'th': 'TH',
    'tr': 'TR',
    'b': 'B',
    'c': 'K',
    'd': 'Z',      # d- (miền Nam) / /j/ miền Bắc — dùng Z cho phổ thông
    'đ': 'DD',
    'g': 'G',
    'h': 'H',
    'k': 'K',
    'l': 'L',
    'm': 'M',
    'n': 'N',
    'p': 'P',
    'r': 'R',
    's': 'S',
    't': 'T',
    'v': 'V',
    'x': 'S',      # x đọc như s (phổ thông)
}

# ─── Bảng âm chính (nuclei) ──────────────────────────────────────────────────

NUCLEI = {
    'uya': 'UYA', 'uye': 'UYE', 'uyu': 'UYU',
    'ươu': 'UROU', 'ươi': 'UROI', 'ươ': 'URO',
    'ưou': 'UROU',
    'uôi': 'UOI', 'uô': 'UO',
    'iêu': 'IEU', 'iê': 'IE',
    'yêu': 'IEU', 'yê': 'IE',
    'âu': 'AU2', 'âm': 'AM2', 'ân': 'AN2', 'âng': 'ANG2',
    'ăm': 'AM3', 'ăn': 'AN3', 'ăng': 'ANG3', 'ăp': 'AP3', 'ăt': 'AT3', 'ăc': 'AC3',
    'oa': 'OA', 'oe': 'OE', 'oi': 'OI', 'oo': 'OO',
    'ôi': 'OI2',
    'au': 'AU', 'ai': 'AI', 'ao': 'AO', 'am': 'AM', 'an': 'AN',
    'ang': 'ANG', 'anh': 'ANH', 'ap': 'AP', 'at': 'AT', 'ach': 'ACH', 'ac': 'AC',
    'em': 'EM', 'en': 'EN', 'eng': 'ENG', 'ep': 'EP', 'et': 'ET',
    'êm': 'EM2', 'ên': 'EN2', 'ênh': 'ENH', 'êp': 'EP2', 'êt': 'ET2', 'êch': 'ECH',
    'im': 'IM', 'in': 'IN', 'inh': 'INH', 'ip': 'IP', 'it': 'IT', 'ich': 'ICH',
    'om': 'OM', 'on': 'ON', 'ong': 'ONG', 'op': 'OP', 'ot': 'OT', 'oc': 'OC',
    'ôm': 'OM2', 'ôn': 'ON2', 'ông': 'ONG2', 'ôp': 'OP2', 'ôt': 'OT2', 'ôc': 'OC2',
    'ơm': 'ORM', 'ơn': 'ORN', 'ơi': 'ORI', 'ơp': 'ORP',
    'um': 'UM', 'un': 'UN', 'ung': 'UNG', 'up': 'UP', 'ut': 'UT', 'uc': 'UC',
    'ưm': 'URM', 'ưn': 'URN', 'ưng': 'URNG', 'ưt': 'URT',
    'ui': 'UI', 'ua': 'UA',
    'ưi': 'URI', 'ưa': 'URA',
    'ya': 'YA', 'ye': 'YE', 'yi': 'YI',
    'iu': 'IU', 'ia': 'IA',
    'eu': 'EU', 'eo': 'EO',
    'a': 'A', 'ă': 'AA', 'â': 'AX', 'e': 'E', 'ê': 'EE',
    'i': 'I', 'o': 'O', 'ô': 'OO2', 'ơ': 'OR',
    'u': 'U', 'ư': 'UR', 'y': 'Y',
}


# ─── Dataclass cho kết quả ───────────────────────────────────────────────────

@dataclass
class Syllable:
    """Đại diện một âm tiết tiếng Việt đã phân tích."""
    original: str
    initial: Optional[str]   # Âm đầu (phiên âm)
    nucleus: str              # Âm chính (phiên âm)
    tone: int                 # 0-5
    tone_name: str

    def to_phoneme_str(self) -> str:
        """Xuất dạng chuỗi âm vị."""
        parts = []
        if self.initial:
            parts.append(self.initial)
        parts.append(self.nucleus)
        parts.append(str(self.tone))
        return '_'.join(parts)


# ─── Phân tích âm tiết ───────────────────────────────────────────────────────

def extract_tone(syllable: str) -> Tuple[str, int]:
    """Tách thanh điệu ra khỏi âm tiết, trả về (âm tiết không dấu, mã thanh)."""
    syllable = unicodedata.normalize('NFC', syllable.lower())
    tone = 0
    result = []
    for ch in syllable:
        if ch in TONE_MAP:
            base, t = TONE_MAP[ch]
            result.append(base)
            tone = t
        else:
            result.append(ch)
    return ''.join(result), tone


def parse_syllable(syllable: str) -> Syllable:
    """Phân tích một âm tiết thành initial + nucleus + tone."""
    stripped, tone = extract_tone(syllable)

    # Tách âm đầu
    initial_found = None
    rest = stripped

    # Kiểm tra các âm đầu dài trước (ưu tiên ngh > ng > n)
    sorted_initials = sorted(INITIALS.keys(), key=len, reverse=True)
    for init in sorted_initials:
        if stripped.startswith(init):
            # Đặc biệt: 'gi' chỉ là âm đầu nếu không phải 'giê','gia','giô'...
            if init == 'gi' and len(stripped) > 2 and stripped[2] == 'i':
                continue  # 'gii' không hợp lệ
            initial_found = INITIALS[init]
            rest = stripped[len(init):]
            break

    # Tìm nucleus
    nucleus_found = None
    sorted_nuclei = sorted(NUCLEI.keys(), key=len, reverse=True)
    for nuc in sorted_nuclei:
        if rest.startswith(nuc) or rest == nuc:
            nucleus_found = NUCLEI[nuc]
            break

    if nucleus_found is None:
        # Fallback: dùng chính chuỗi đó
        nucleus_found = rest.upper() if rest else 'A'

    return Syllable(
        original=syllable,
        initial=initial_found,
        nucleus=nucleus_found,
        tone=tone,
        tone_name=TONE_NAMES[tone],
    )


# ─── G2P chính ───────────────────────────────────────────────────────────────

def tokenize_vi(text: str) -> List[str]:
    """Tách văn bản thành danh sách âm tiết/từ đơn giản."""
    # Tách theo khoảng trắng và dấu câu
    tokens = re.findall(r'[a-záàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]+|[.,!?;:…\-]', text.lower())
    return tokens


def g2p_syllable(syllable: str) -> str:
    """Chuyển 1 âm tiết → chuỗi phoneme."""
    syl = parse_syllable(syllable)
    return syl.to_phoneme_str()


def g2p_text(text: str, return_tones: bool = True) -> List[str]:
    """
    Chuyển toàn bộ văn bản tiếng Việt → danh sách phoneme tokens.

    Args:
        text: Văn bản tiếng Việt đã chuẩn hóa
        return_tones: Có kèm mã thanh điệu không

    Returns:
        Danh sách chuỗi phoneme
    """
    tokens = tokenize_vi(text)
    phonemes = []

    for token in tokens:
        # Dấu câu giữ nguyên như special token
        if re.match(r'^[.,!?;:\-…]+$', token):
            phonemes.append(f'<PUNCT_{token}>')
            continue

        # Phân tích âm tiết
        syllable = parse_syllable(token)
        if return_tones:
            phonemes.append(syllable.to_phoneme_str())
        else:
            parts = []
            if syllable.initial:
                parts.append(syllable.initial)
            parts.append(syllable.nucleus)
            phonemes.append('_'.join(parts))

    return phonemes


# ─── VnCoreNLP wrapper (nếu có) ──────────────────────────────────────────────

class VnCoreNLPG2P:
    """
    G2P sử dụng VnCoreNLP để tách từ chính xác hơn.
    Yêu cầu: pip install py_vncorenlp và Java 8+
    """

    def __init__(self, save_dir: str = './vncorenlp'):
        self._nlp = None
        self._save_dir = save_dir

    def _load(self):
        if self._nlp is None:
            try:
                import py_vncorenlp
                self._nlp = py_vncorenlp.VnCoreNLP(
                    annotators=["wseg"],
                    save_dir=self._save_dir
                )
                print("[G2P] VnCoreNLP loaded successfully.")
            except ImportError:
                print("[G2P] Warning: py_vncorenlp not installed. Using simple tokenizer.")
            except Exception as e:
                print(f"[G2P] Warning: VnCoreNLP failed to load: {e}. Using fallback.")

    def segment(self, text: str) -> List[str]:
        """Tách từ bằng VnCoreNLP."""
        self._load()
        if self._nlp is None:
            return tokenize_vi(text)

        try:
            result = self._nlp.word_segment(text)
            words = []
            for sent in result:
                words.extend(sent.split())
            return words
        except Exception:
            return tokenize_vi(text)

    def text_to_phonemes(self, text: str) -> List[str]:
        """Full pipeline: text → tách từ → phoneme."""
        words = self.segment(text)
        phonemes = []
        for word in words:
            syllables = word.split('_')  # VnCoreNLP nối từ ghép bằng _
            for syl in syllables:
                if re.match(r'^[.,!?;:\-]+$', syl):
                    phonemes.append(f'<PUNCT_{syl}>')
                else:
                    phonemes.append(g2p_syllable(syl))
        return phonemes


# ─── Test ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    test_sentences = [
        "xin chào",
        "tôi yêu tiếng Việt",
        "hôm nay trời đẹp quá",
        "ông ấy đi làm bằng xe máy",
        "chúng ta sẽ thành công",
    ]

    print("=== Vietnamese G2P Test ===\n")
    for sent in test_sentences:
        phonemes = g2p_text(sent)
        print(f"IN : {sent}")
        print(f"OUT: {' | '.join(phonemes)}")
        print()
