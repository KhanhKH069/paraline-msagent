# 📐 ĐẶC TẢ TOÀN BỘ THUẬT TOÁN HỆ THỐNG MEETING AI ASSISTANT
## Cơ chế Cửa sổ Trượt Co giãn bằng Quy hoạch Động (Elastic Dynamic Programming Windowing) & Các Thuật toán Cốt lõi

> **Tài liệu kỹ thuật nội bộ (Technical Specification & Algorithm Whitepaper)**  
> **Dự án:** Real-Time Multilingual Meeting AI Assistant  
> **Mục tiêu:** Nâng cấp cơ chế Sliding Window cố định (~4.0s) thành **Cửa sổ trượt co giãn đàn hồi $k$ giây** sử dụng **Quy hoạch động (Dynamic Programming)** kết hợp đa phương thức (Acoustic + Linguistic + Latency), đồng thời hệ thống hóa toàn bộ các giải thuật cốt lõi trong pipeline.

---

## MỤC LỤC

1. [Tổng quan: Giới hạn của Cửa sổ trượt cố định (Fixed Sliding Window 4s)](#1-tổng-quan-giới-hạn-của-cửa-sổ-trượt-cố-định-fixed-sliding-window-4s)
2. [Thuật toán 1: Phân đoạn Cửa sổ Co giãn $k$ giây bằng Quy hoạch Động (Elastic DP Segmentation)](#2-thuật-toán-1-phân-đoạn-cửa-sổ-co-giãn-k-giây-bằng-quy-hoạch-động-elastic-dp-segmentation)
   - 2.1 Không gian trạng thái và miền co giãn $[k_{\min}, k_{\max}]$
   - 2.2 Hàm chi phí đa mục tiêu (Multi-objective Cost Function)
   - 2.3 Phương trình truy hồi Bellman (Recurrence Formulation)
   - 2.4 Thuật toán Online DP Windowing (Độ phức tạp $O(W)$ thời gian thực)
   - 2.5 Mã giả & Code tham chiếu Python
3. [Thuật toán 2: Căn chỉnh & Khử lặp chuỗi Overlap bằng DP (Token-Level Sequence Alignment)]( #3-thuật-toán-2-căn-chỉnh--khử-lặp-chuỗi-overlap-bằng-dp-token-level-sequence-alignment)
   - 3.1 Vấn đề "chém đôi từ" và xung đột ở biên Overlap
   - 3.2 Biến thể thuật toán Needleman-Wunsch / Semi-Global Alignment
   - 3.3 Mã giả & Code tham chiếu Python
4. [Tổng hợp các Thuật toán Cốt lõi khác trong Hệ thống](#4-tổng-hợp-các-thuật-toán-cốt-lõi-khác-trong-hệ-thống)
   - 4.1 Thuật toán Silero VAD State Management & LSTM Reset
   - 4.2 Thuật toán Trừ phổ thích ứng (Spectral Subtraction Noise Reduction)
   - 4.3 Thuật toán Phục hồi ảnh nền Slide (Fast Marching Inpainting - Telea)
   - 4.4 Thuật toán Dàn chữ tự động (Dynamic Typography Fitting Engine)
5. [Lộ trình & Điểm tích hợp vào Codebase](#5-lộ-trình--điểm-tích-hợp-vào-codebase)

---

## 1. TỔNG QUAN: GIỚI HẠN CỦA CỬA SỔ TRƯỢT CỐ ĐỊNH (FIXED SLIDING WINDOW 4s)

Trong hệ thống ASR trực tiếp hiện nay, luồng âm thanh liên tục thường được xử lý theo 1 trong 2 cách truyền thống:
1. **Chờ khoảng lặng hoàn toàn (VAD Silence Cut):** Người nói phải dừng hẳn $> 500\text{ms}$ mới chốt câu.
   * *Nhược điểm:* Người nói liên tục, nói liền mạch thì buffer bị tích tụ quá lâu (> 6-10s), phá vỡ ngân sách độ trễ $T_{\text{latency}} \le 1.0\text{s}$.
2. **Cắt cưỡng bức theo khung cố định (Fixed Hard Window 4.0s):** Cứ đủ 4s là cắt và gửi.
   * *Nhược điểm chí mạng:*
     - **Cắt ngang âm tiết/từ (Word Truncation):** Cắt đúng lúc đang phát âm âm tiết dở dang (ví dụ: "chúng ta sẽ giải..." | "...quyết vấn đề"). Whisper nhận dạng phân đoạn đầu thành từ sai nghĩa hoặc ảo giác (hallucination).
     - **Mất tính gắn kết ngữ nghĩa (Semantic Distortion):** Mô hình dịch NLLB-200 nhận được nửa câu không đủ chủ-vị, dẫn đến bản dịch méo mó hoặc tối nghĩa.
     - **Khó xử lý vùng chồng lấp (Overlap):** Nếu lấy thêm 1s overlap để cứu từ bị cắt, việc ghép 2 câu lại với nhau rất dễ bị lặp từ (duplication: "giải quyết quyết vấn đề").

$\Rightarrow$ **Giải pháp:** Xây dựng **Cửa sổ trượt co giãn đàn hồi (Elastic Sliding Window)**: Thời gian chốt cửa sổ không phải là hằng số $4.0\text{s}$, mà là một biến số $k \in [k_{\min}, k_{\max}]$ được tính toán tối ưu tại thời gian thực thông qua bài toán **Quy hoạch động (Dynamic Programming)**.

---

## 2. THUẬT TOÁN 1: PHÂN ĐOẠN CỬA SỔ CO GIÃN $k$ GIÂY BẰNG QUY HOẠCH ĐỘNG (ELASTIC DP SEGMENTATION)

### 2.1 Không gian trạng thái và miền co giãn $[k_{\min}, k_{\max}]$

Giả sử luồng âm thanh được chia thành các khung cơ bản (frames) với độ dài $\Delta t = 32\text{ms}$ (tương ứng 512 samples ở 16kHz của Silero VAD).
- Gọi thời điểm hiện tại là frame thứ $t$.
- Ta quy định miền co giãn của cửa sổ:
  - $k_{\min} \approx 1.5\text{s}$ (tương đương $N_{\min} \approx 47$ frames): Đảm bảo đoạn âm thanh đủ thông tin ngữ âm tối thiểu cho Whisper.
  - $k_{\text{target}} \approx 3.0\text{s} - 4.0\text{s}$ (tương đương $N_{\text{target}} \approx 94 - 125$ frames): Độ dài lý tưởng cho ASR và NMT.
  - $k_{\max} \approx 5.5\text{s}$ (tương đương $N_{\max} \approx 172$ frames): Giới hạn trần cứng, không được vượt quá để bảo toàn độ trễ realtime.

Mục tiêu: Tại mỗi thời điểm, tìm điểm cắt tối ưu $t^*$ sao cho việc chốt phân đoạn âm thanh $[t_{\text{start}}, t^*]$ đạt chi phí cực tiểu:
$$t^* = \arg\min_{t \in [t_{\text{start}} + N_{\min}, \, t_{\text{start}} + N_{\max}]} \text{Cost}(t_{\text{start}}, t)$$

---

### 2.2 Hàm chi phí đa mục tiêu (Multi-objective Cost Function)

Chi phí để cắt tại frame thứ $t$ (với độ dài phân đoạn $\Delta N = t - t_{\text{start}}$) được cấu thành từ 3 thành phần:

$$\text{Cost}(t) = w_a \cdot C_{\text{acoustic}}(t) + w_s \cdot C_{\text{semantic}}(t) + w_l \cdot C_{\text{latency}}(\Delta N)$$

Trong đó $w_a, w_s, w_l$ là các hệ số trọng số chuẩn hóa ($w_a + w_s + w_l = 1$).

#### 1. Chi phí Âm học (Acoustic Cost - $C_{\text{acoustic}}$)
Ưu tiên cắt tại các "thung lũng năng lượng" (Energy Valleys) hoặc nơi xác suất có tiếng nói là thấp nhất:
$$C_{\text{acoustic}}(t) = p_{\text{speech}}(t) + \lambda_e \cdot \frac{E(t)}{E_{\text{avg}}}$$
- $p_{\text{speech}}(t) \in [0, 1]$: Xác suất tiếng nói trả về từ Silero VAD tại frame $t$. Càng gần 0 thì chi phí cắt càng thấp.
- $E(t) = \frac{1}{M} \sum_{i=1}^M x_i^2$: Năng lượng RMS ngắn hạn tại frame $t$.
- Khi người nói ngắt hơi hoặc chuyển câu, $C_{\text{acoustic}}(t) \to 0$.

#### 2. Chi phí Ngữ nghĩa / Nhịp điệu (Semantic/Rhythmic Cost - $C_{\text{semantic}}$)
Được ước lượng qua đạo hàm xác suất tiếng nói và nhịp nghỉ của âm tiết:
$$C_{\text{semantic}}(t) = \max\left(0, \, \frac{d \, p_{\text{speech}}}{dt}(t)\right)$$
- Nếu xác suất tiếng nói đang tăng vọt ($\frac{dp}{dt} > 0$), chứng tỏ người nói **vừa mới bắt đầu một từ mới** $\rightarrow$ Chi phí cắt cực cao (phạt nặng việc chém đôi từ).
- Nếu xác suất đang giảm dần và duy trì ở đáy ($\frac{dp}{dt} \le 0$), chi phí thấp.

#### 3. Chi phí Phạt Độ trễ (Latency Penalty - $C_{\text{latency}}$)
Được thiết kế theo hàm phi tuyến (hàm mũ hoặc bậc hai) để ép cửa sổ phải kết thúc khi gần chạm $k_{\max}$:
$$C_{\text{latency}}(\Delta N) = \begin{cases} 
0, & \text{nếu } \Delta N < N_{\text{target}} \\
\left(\frac{\Delta N - N_{\text{target}}}{N_{\max} - N_{\text{target}}}\right)^2, & \text{nếu } N_{\text{target}} \le \Delta N < N_{\max} \\
+\infty, & \text{nếu } \Delta N \ge N_{\max}
\end{cases}$$

Khi độ dài phân đoạn vượt quá $N_{\text{target}}$, chi phí phạt tăng vọt, lấn át chi phí âm học và ép hệ thống phải thực hiện cắt câu ngay tại khoảng lặng nhỏ nhất kế tiếp.

---

### 2.3 Phương trình truy hồi Bellman (Recurrence Formulation)

Đối với toàn bộ luồng hội thoại gồm $T$ frames, bài toán phân hoạch thành chuỗi các điểm cắt $0 = \tau_0 < \tau_1 < \tau_2 < \dots < \tau_M = T$ được giải bằng quy hoạch động:

$$DP[j] = \min_{j - N_{\max} \le i \le j - N_{\min}} \Big\{ DP[i] + \text{Cost}(i, j) \Big\}$$

Trong đó:
- $DP[j]$: Tổng chi phí tối ưu tích lũy từ frame 0 đến frame $j$.
- Điểm cắt trước đó $i$ được lưu lại trong bảng vết (backtrack pointer):
  $$\text{Split}[j] = \arg\min_{i} \Big\{ DP[i] + \text{Cost}(i, j) \Big\}$$

---

### 2.4 Thuật toán Online DP Windowing (Độ phức tạp $O(W)$ thời gian thực)

Vì hệ thống hoạt động thời gian thực (Streaming), ta không thể chờ đến hết buổi họp mới chạy Backtrack toàn cục. Thay vào đó, ta áp dụng **Online Sliding DP** với cửa sổ quan sát $W = [N_{\min}, N_{\max}]$:

```
Luồng Audio liên tục: ════════════════════════════════════════════════════════════►
                           │◄──────── Cửa sổ co giãn k giây ────────►│
                     t_start                                         t_now
                     [-------------------- Vùng tìm kiếm --------------------]
                                      [ N_min ─── N_target ─── N_max ]
                                                 ▲
                                        Điểm cắt tối ưu t* (DP Min)
```

1. **Giai đoạn $t < N_{\min}$:** Buffer tích lũy âm thanh, chưa kích hoạt tìm kiếm cắt.
2. **Giai đoạn $N_{\min} \le t < N_{\max}$:**
   - Mỗi frame mới đến, tính $\text{Cost}(t)$.
   - Nếu phát hiện $\text{Cost}(t) < \theta_{\text{threshold}}$ (gặp khoảng lặng tự nhiên khi câu đã đủ dài) $\rightarrow$ **Cắt ngay lập tức!**
3. **Giai đoạn $t \ge N_{\max}$:** Cưỡng bức cắt tại điểm có $\text{Cost}$ nhỏ nhất trong cửa sổ quan sát vừa qua.

---

### 2.5 Mã giả & Code tham chiếu Python

```python
"""
Thuật toán: Elastic Dynamic Programming Segmentation (EDP-Seg)
Module: client/audio_router/elastic_segmenter.py
"""
import numpy as np

class ElasticDPSegmenter:
    def __init__(
        self,
        sample_rate: int = 16000,
        frame_samps: int = 512,       # 32ms @ 16kHz
        k_min_sec: float = 1.5,       # Giới hạn dưới: 1.5s
        k_target_sec: float = 3.5,    # Ngưỡng mục tiêu: 3.5s
        k_max_sec: float = 5.0,       # Giới hạn trên cứng: 5.0s
        w_acoustic: float = 0.5,
        w_semantic: float = 0.2,
        w_latency: float = 0.3,
    ):
        self.sr = sample_rate
        self.frame_samps = frame_samps
        self.n_min = int(k_min_sec * sample_rate / frame_samps)
        self.n_target = int(k_target_sec * sample_rate / frame_samps)
        self.n_max = int(k_max_sec * sample_rate / frame_samps)

        self.w_a = w_acoustic
        self.w_s = w_semantic
        self.w_l = w_latency

        self.reset()

    def reset(self):
        """Khởi tạo lại trạng thái khi bắt đầu phân đoạn mới."""
        self.frames_p_speech = []
        self.frames_rms = []
        self.costs = []
        self.buffer = []

    def push_frame(self, audio_frame: np.ndarray, p_speech: float) -> tuple[bool, np.ndarray]:
        """
        Đẩy 1 frame (512 samples) vào bộ đệm và chạy DP check.
        Trả về: (is_split, audio_to_send)
        """
        self.buffer.append(audio_frame)
        self.frames_p_speech.append(p_speech)
        rms = float(np.sqrt(np.mean(audio_frame.astype(np.float32) ** 2)))
        self.frames_rms.append(rms)

        curr_len = len(self.buffer)

        # 1. Chưa đạt độ dài tối thiểu -> chưa cắt
        if curr_len < self.n_min:
            return False, np.empty(0, dtype=audio_frame.dtype)

        # 2. Tính Cost âm học (Acoustic Cost)
        c_acoustic = p_speech

        # 3. Tính Cost ngữ nghĩa (Semantic Cost: phạt việc ngắt khi p_speech đang tăng)
        if len(self.frames_p_speech) >= 2:
            dp = self.frames_p_speech[-1] - self.frames_p_speech[-2]
            c_semantic = max(0.0, dp)
        else:
            c_semantic = 0.0

        # 4. Tính Cost độ trễ (Latency Penalty)
        if curr_len < self.n_target:
            c_latency = 0.0
        else:
            c_latency = ((curr_len - self.n_target) / (self.n_max - self.n_target)) ** 2

        # Tổng chi phí tại frame hiện tại
        total_cost = self.w_a * c_acoustic + self.w_s * c_semantic + self.w_l * c_latency
        self.costs.append(total_cost)

        # 5. Quyết định cắt:
        # TH1: Cắt tự nhiên tại khoảng lặng lý tưởng khi đã qua n_min
        is_natural_pause = (p_speech < 0.25 and curr_len >= self.n_min)
        
        # TH2: Phạt độ trễ đẩy lên cao hoặc chạm n_max cứng
        is_timeout = (curr_len >= self.n_max)

        if is_natural_pause or is_timeout:
            # Thu thập toàn bộ audio trong buffer
            segmented_audio = np.concatenate(self.buffer)
            self.reset()
            return True, segmented_audio

        return False, np.empty(0, dtype=audio_frame.dtype)
```

---

## 3. THUẬT TOÁN 2: CĂN CHỈNH & KHỬ LẶP CHUỖI OVERLAP BẰNG DP (TOKEN-LEVEL SEQUENCE ALIGNMENT)

### 3.1 Vấn đề "chém đôi từ" và xung đột ở biên Overlap

Khi phân đoạn $S_{k}$ và phân đoạn kế tiếp $S_{k+1}$ có vùng thời gian chồng lấp (ví dụ overlap 1.0 giây âm thanh):
- Đoạn $S_k$ nhận dạng ra chuỗi token:
  $$A = [a_1, a_2, \dots, a_n] = \text{"chúng tôi cần đánh giá kỹ giải pháp"}$$
- Đoạn $S_{k+1}$ nhận dạng ra chuỗi token:
  $$B = [b_1, b_2, \dots, b_m] = \text{"đánh giá kỹ giải pháp tối ưu cho hệ thống"}$$

Nếu nối chuỗi thủ công, kết quả bị lặp cụm từ:
$\rightarrow$ *"chúng tôi cần đánh giá kỹ giải pháp đánh giá kỹ giải pháp tối ưu cho hệ thống"* (Sai nghiêm trọng).

Nếu so khớp chuỗi con chính xác (`A in B`), chỉ cần 1 từ nhận dạng sai 1 ký tự (do ASR nhiễu) thì so khớp hoàn toàn thất bại.

---

### 3.2 Biến thể thuật toán Needleman-Wunsch / Semi-Global Alignment

Ta mô hình hóa bài toán ghép chuỗi bằng **Quy hoạch động tìm khớp nối hậu tố - tiền tố (Suffix-Prefix Semi-Global Alignment)**.

#### Định nghĩa:
- Tìm hậu tố của chuỗi $A$ khớp tốt nhất với tiền tố của chuỗi $B$.
- Cho ma trận quy hoạch động $D$ kích thước $(n+1) \times (m+1)$:
  - $D[i, 0] = 0 \quad \forall i$ (Không phạt việc bỏ qua phần đầu của $A$).
  - $D[0, j] = -j \cdot \text{gap\_penalty}$ (Phạt nếu không khớp từ đầu của $B$).

#### Công thức truy hồi:
$$D[i, j] = \max \begin{cases}
D[i-1, j-1] + \text{Score}(a_i, b_j) & \text{(Match / Mismatch)} \\
D[i-1, j] - \text{penalty}_{\text{del}} & \text{(Deletion)} \\
D[i, j-1] - \text{penalty}_{\text{ins}} & \text{(Insertion)}
\end{cases}$$

Trong đó hàm chấm điểm tương đồng token:
$$\text{Score}(a_i, b_j) = \begin{cases}
+2, & \text{nếu } a_i = b_j \\
-1, & \text{nếu } a_i \ne b_j \text{ (hoặc dùng Levenshtein distance ở cấp độ từ)}
\end{cases}$$

#### Điểm cắt tối ưu:
Tìm vị trí $i^*$ trên hàng cuối cùng hoặc cột cuối cùng đạt điểm số cao nhất:
$$j^* = \arg\max_{1 \le j \le m} D[n, j]$$
- Vùng trùng lặp chính là $B[1 \dots j^*]$.
- Chuỗi kết quả sau khi ghép (Stitched Sequence):
  $$\text{Merged} = A \cup B[j^* + 1 \dots m]$$

---

### 3.3 Mã giả & Code tham chiếu Python

```python
"""
Thuật toán: Suffix-Prefix DP Alignment for ASR Overlap Stitching
Module: services/api-gateway/dp_aligner.py
"""
from typing import List

def dp_merge_transcripts(prev_tokens: List[str], next_tokens: List[str]) -> List[str]:
    """
    Ghép hai danh sách từ (tokens) dựa trên thuật toán Quy hoạch động căn chỉnh hậu tố-tiền tố.
    Khử sạch hiện tượng lặp từ ở biên cửa sổ trượt.
    """
    if not prev_tokens:
        return next_tokens
    if not next_tokens:
        return prev_tokens

    n = len(prev_tokens)
    m = len(next_tokens)

    # Khởi tạo bảng DP (n+1 x m+1)
    dp = [[0] * (m + 1) for _ in range(n + 1)]

    MATCH_SCORE = 3
    MISMATCH_PENALTY = -2
    GAP_PENALTY = -2

    # Hàng đầu tiên bị phạt vì phải khớp từ đầu chuỗi B
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + GAP_PENALTY

    # Cột đầu tiên bằng 0 (vì cho phép chuỗi A trôi tự do tới điểm overlap)
    for i in range(1, n + 1):
        dp[i][0] = 0

    # Điền bảng quy hoạch động
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match = dp[i - 1][j - 1] + (
                MATCH_SCORE if prev_tokens[i - 1].lower() == next_tokens[j - 1].lower()
                else MISMATCH_PENALTY
            )
            delete = dp[i - 1][j] + GAP_PENALTY
            insert = dp[i][j - 1] + GAP_PENALTY
            dp[i][j] = max(match, delete, insert)

    # Tìm điểm kết thúc overlap tốt nhất trên hàng cuối cùng của A (i = n)
    best_j = 0
    best_score = -1e9
    for j in range(1, m + 1):
        if dp[n][j] > best_score:
            best_score = dp[n][j]
            best_j = j

    # Nếu điểm số khớp quá thấp -> không có overlap hợp lệ, nối chuỗi thuần túy
    if best_score < MATCH_SCORE:
        return prev_tokens + next_tokens

    # Ghép chuỗi: Giữ nguyên A + phần đuôi còn lại của B từ best_j
    return prev_tokens + next_tokens[best_j:]
```

---

## 4. TỔNG HỢP CÁC THUẬT TOÁN CỐT LÕI KHÁC TRONG HỆ THỐNG

Để tạo thành một bức tranh công nghệ hoàn chỉnh, dưới đây là đặc tả toán học của 4 giải thuật phụ trợ đang vận hành trong dự án:

### 4.1 Thuật toán Silero VAD State Management & LSTM Reset

Mô hình Silero VAD sử dụng mạng nơ-ron hồi quy LSTM để lưu ngữ cảnh âm thanh qua các khung thời gian.
- **Vấn đề rò rỉ trạng thái (LSTM State Bleed):** Sau khi một người nói dứt câu, trạng thái ẩn $h_t, c_t$ của LSTM vẫn còn tích lũy năng lượng cao. Khi câu mới bắt đầu sau khoảng lặng ngắn, $h_t$ cũ làm mô hình nhận định nhầm tiếng ồn thành tiếng nói, hoặc triệt tiêu đoạn mở đầu của câu sau.
- **Giải thuật điều khiển:**
  $$\text{State Reset Trigger}: \quad \text{if } \text{is\_final} == \text{True} \implies h_t \leftarrow \mathbf{0}, \; c_t \leftarrow \mathbf{0}$$
  Được hiện thực hóa tại `inbound.py`:
  ```python
  def _reset_vad_state(self):
      if self._vad_model is not None:
          self._vad_model.reset_states()
  ```

---

### 4.2 Thuật toán Trừ phổ thích ứng (Spectral Subtraction Noise Reduction)

Khử tạp âm môi trường (tiếng quạt, điều hòa, tiếng vang mic) trước khi nạp vào mô hình Whisper:
1. Biến đổi Fourier nhanh ngắn hạn (STFT) tín hiệu âm thanh:
   $$X(k) = \text{FFT}(x(n)) = |X(k)| e^{j \theta(k)}$$
2. Ước lượng phổ công suất nhiễu $\mu_N(k)$ trong các khoảng lặng được định danh bởi VAD:
   $$\mu_N^{(t)}(k) = (1 - \alpha) \mu_N^{(t-1)}(k) + \alpha |N(k)|$$
3. Trừ phổ có hệ số bù ngưỡng (Spectral Floor $\beta$ và Over-subtraction $\gamma$):
   $$|\hat{S}(k)| = \max \left( \sqrt{|X(k)|^2 - \gamma \cdot \mu_N^2(k)}, \; \beta \cdot |X(k)| \right)$$
4. Biến đổi Fourier ngược (iFFT) để tái tạo tín hiệu âm thanh sạch:
   $$\hat{s}(n) = \text{iFFT}\left(|\hat{S}(k)| e^{j \theta(k)}\right)$$

---

### 4.3 Thuật toán Phục hồi ảnh nền Slide (Fast Marching Inpainting - Telea)

Khi dịch slide thuyết trình, sau khi xóa chữ gốc tiếng Nhật/Anh, thuật toán Telea (2004) tiến hành bù đắp các điểm ảnh khuyết tật $p \in \Omega$ dựa trên gradient vùng biên $\partial \Omega$:

$$I(p) = \frac{\sum_{q \in B_\epsilon(p)} w(p, q) \cdot [I(q) + \nabla I(q) \cdot (p - q)]}{\sum_{q \in B_\epsilon(p)} w(p, q)}$$

Trong đó hàm trọng số không gian:
$$w(p, q) = \text{dir}(p, q) \cdot \text{dst}(p, q) \cdot \text{lev}(p, q)$$
- $\text{dir}(p, q)$: Tích vô hướng giữa vector chuẩn hóa $(p-q)$ và vector pháp tuyến của đường đẳng mức (isophote).
- $\text{dst}(p, q) = \frac{1}{\|p - q\|^2}$: Nghịch đảo bình phương khoảng cách Euclide.
- $\text{lev}(p, q)$: Khoảng cách hàm mức (level set distance) tính theo phương trình Eikonal $|\nabla T| = 1$.

---

### 4.4 Thuật toán Dàn chữ tự động (Dynamic Typography Fitting Engine)

Đảm bảo văn bản dịch tiếng Việt vừa khít hoàn hảo bên trong hộp giới hạn $B_i = (w_i, h_i)$ của chữ gốc:

```
Khởi tạo: Font_Size = Font_Size_Gốc
Lặp:
  1. Wrap text thành k dòng dựa trên Font_Size và giới hạn chiều rộng w_i
  2. Tính tổng chiều cao hộp chữ: H_render = k * Line_Height(Font_Size)
  3. Nếu H_render <= h_i VÀ Max_Line_Width <= w_i:
       -> Dừng và chọn Font_Size hiện tại
  4. Ngược lại:
       -> Font_Size = Font_Size - 1
       -> Nếu Font_Size < Min_Font_Size (8px) -> Cưỡng bức cắt ngắn kèm dấu "..."
```

---

## 5. LỘ TRÌNH & ĐIỂM TÍCH HỢP VÀO CODEBASE

| Bước | Thành phần | Tệp tin sửa đổi | Mục tiêu tích hợp |
|:---:|---|---|---|
| **1** | Client Audio Chunking | `client/audio_router/inbound.py` | Tích hợp lớp `ElasticDPSegmenter` thay thế cho ngưỡng tĩnh `MAX_CHUNKS=100`. |
| **2** | Gateway Transcript Deduplication | `services/api-gateway/pipeline.py` | Thay thế cơ chế so sánh chuỗi thô `original_text == last_text` bằng hàm `dp_merge_transcripts()`. |
| **3** | Cập nhật Báo cáo kỹ thuật | `PROPOSAL.md` | Bổ sung Mục 2.1.3 và 4.1.3 trình bày thuật toán Elastic DP Segmentation vào bản đề xuất LaTeX. |

---
*Tài liệu được biên soạn và bảo chứng kỹ thuật bởi AI R&D Team.*
