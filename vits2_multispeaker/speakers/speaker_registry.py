"""
Speaker Registry — quản lý danh sách giọng đọc.

Đây là nguồn sự thật duy nhất (single source of truth) cho tất cả
thông tin về speaker: id, tên, embedding path, metadata.

Dùng ở mọi nơi: training, inference, add_speaker script.
"""

import json
import os
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass, asdict


REGISTRY_PATH = Path(__file__).parent / 'speakers.json'
EMBEDDINGS_DIR = Path(__file__).parent / 'embeddings'


@dataclass
class Speaker:
    id: int
    name: str
    display_name: str
    gender: str           # 'male' | 'female' | 'other'
    region: str           # 'north' | 'central' | 'south'
    description: str
    audio_sample: str     # path đến file audio mẫu (~30s)
    embedding_path: str   # path đến .pt file chứa speaker embedding
    training_hours: float
    added_at: str
    notes: str = ''

    @property
    def is_ready(self) -> bool:
        """Speaker đã có embedding và audio sample chưa."""
        return (
            os.path.exists(self.embedding_path) and
            os.path.exists(self.audio_sample)
        )


class SpeakerRegistry:
    """
    Quản lý danh sách speakers. Load/save từ speakers.json.

    Ví dụ sử dụng:
        registry = SpeakerRegistry()

        # Lấy speaker theo tên
        spk = registry.get('nu_bac')
        print(spk.id, spk.display_name)

        # Lấy speaker theo id
        spk = registry.get_by_id(3)

        # Thêm speaker mới
        registry.add(Speaker(id=6, name='custom', ...))

        # Liệt kê tất cả
        for spk in registry.list_all():
            print(spk.id, spk.display_name, '✓' if spk.is_ready else '✗')
    """

    def __init__(self, registry_path: str = None):
        self._path = Path(registry_path or REGISTRY_PATH)
        self._data = self._load()
        EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self._path.exists():
            return {'speakers': [], 'total_speakers': 0,
                    'embedding_dim': 256, 'model_version': 'vits2-vi-v1'}
        with open(self._path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save(self):
        self._data['total_speakers'] = len(self._data['speakers'])
        with open(self._path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _raw_to_speaker(self, raw: dict) -> Speaker:
        return Speaker(**{k: raw[k] for k in Speaker.__dataclass_fields__})

    # ── Truy vấn ─────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[Speaker]:
        """Lấy speaker theo name (slug)."""
        for s in self._data['speakers']:
            if s['name'] == name:
                return self._raw_to_speaker(s)
        return None

    def get_by_id(self, speaker_id: int) -> Optional[Speaker]:
        """Lấy speaker theo integer id."""
        for s in self._data['speakers']:
            if s['id'] == speaker_id:
                return self._raw_to_speaker(s)
        return None

    def resolve(self, identifier) -> Optional[Speaker]:
        """Chấp nhận cả int id lẫn str name."""
        if isinstance(identifier, int):
            return self.get_by_id(identifier)
        if isinstance(identifier, str):
            # Thử parse số
            if identifier.isdigit():
                return self.get_by_id(int(identifier))
            return self.get(identifier)
        return None

    def list_all(self) -> List[Speaker]:
        return [self._raw_to_speaker(s) for s in self._data['speakers']]

    def list_by_gender(self, gender: str) -> List[Speaker]:
        return [s for s in self.list_all() if s.gender == gender]

    def list_by_region(self, region: str) -> List[Speaker]:
        return [s for s in self.list_all() if s.region == region]

    def total(self) -> int:
        return len(self._data['speakers'])

    def name_to_id(self) -> Dict[str, int]:
        return {s['name']: s['id'] for s in self._data['speakers']}

    def id_to_name(self) -> Dict[int, str]:
        return {s['id']: s['name'] for s in self._data['speakers']}

    # ── Thêm / cập nhật ──────────────────────────────────────────────────────

    def add(self, speaker: Speaker, overwrite: bool = False):
        """Thêm speaker mới. Lỗi nếu name/id đã tồn tại (trừ khi overwrite=True)."""
        existing_names = {s['name'] for s in self._data['speakers']}
        existing_ids = {s['id'] for s in self._data['speakers']}

        if speaker.name in existing_names and not overwrite:
            raise ValueError(f"Speaker name '{speaker.name}' đã tồn tại. Dùng overwrite=True để ghi đè.")
        if speaker.id in existing_ids and not overwrite:
            raise ValueError(f"Speaker id {speaker.id} đã tồn tại. Dùng overwrite=True để ghi đè.")

        # Xóa entry cũ nếu overwrite
        self._data['speakers'] = [
            s for s in self._data['speakers']
            if s['name'] != speaker.name and s['id'] != speaker.id
        ]

        self._data['speakers'].append(asdict(speaker))
        self._data['speakers'].sort(key=lambda x: x['id'])
        self._save()
        print(f"[Registry] ✓ Speaker '{speaker.display_name}' (id={speaker.id}) đã được thêm.")

    def update_embedding_path(self, name: str, path: str):
        """Cập nhật đường dẫn embedding sau khi extract xong."""
        for s in self._data['speakers']:
            if s['name'] == name:
                s['embedding_path'] = path
                self._save()
                return
        raise ValueError(f"Speaker '{name}' không tồn tại.")

    def update_training_hours(self, name: str, hours: float):
        for s in self._data['speakers']:
            if s['name'] == name:
                s['training_hours'] = round(hours, 2)
                self._save()
                return

    def next_available_id(self) -> int:
        """ID tiếp theo chưa bị dùng."""
        ids = {s['id'] for s in self._data['speakers']}
        i = 0
        while i in ids:
            i += 1
        return i

    # ── Hiển thị ─────────────────────────────────────────────────────────────

    def print_table(self):
        """In bảng tóm tắt tất cả speakers."""
        speakers = self.list_all()
        if not speakers:
            print("[Registry] Chưa có speaker nào.")
            return

        header = f"{'ID':>4}  {'Name':<16} {'Giới':>6} {'Vùng':>8} {'Giờ train':>10}  {'Sẵn sàng':>9}  {'Mô tả'}"
        print("\n" + "═" * 80)
        print("  DANH SÁCH GIỌNG ĐỌC")
        print("═" * 80)
        print(header)
        print("─" * 80)
        gender_vi = {'male': 'Nam', 'female': 'Nữ', 'other': 'Khác'}
        region_vi = {'north': 'Bắc', 'central': 'Trung', 'south': 'Nam'}
        for s in speakers:
            ready = '✓' if s.is_ready else '✗ chưa có'
            g = gender_vi.get(s.gender, s.gender)
            r = region_vi.get(s.region, s.region)
            print(f"{s.id:>4}  {s.name:<16} {g:>6} {r:>8} {s.training_hours:>9.1f}h  {ready:>9}  {s.description}")
        print("═" * 80 + "\n")


# Singleton để dùng ở mọi nơi
_registry_instance: Optional[SpeakerRegistry] = None


def get_registry(path: str = None) -> SpeakerRegistry:
    global _registry_instance
    if _registry_instance is None or path:
        _registry_instance = SpeakerRegistry(path)
    return _registry_instance
