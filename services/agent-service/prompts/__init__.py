SUMMARY_PROMPT = """Bạn là trợ lý AI chuyên tóm tắt biên bản cuộc họp.
Dựa vào transcript dưới đây, hãy viết 1 câu tóm tắt chính và liệt kê tối đa 10 điểm chính (key points) của cuộc họp.
Transcript:
{transcript}
"""

ACTION_ITEMS_PROMPT = """Bạn là trợ lý AI phân tích cuộc họp.
Dựa vào transcript dưới đây, hãy trích xuất các công việc (action items). 
Trả về ĐÚNG định dạng JSON array chứa các object: {{"task": "tên công việc", "assignee": "người phụ trách nếu có", "deadline": "hạn chót nếu có"}}. Không kèm theo text nào khác ngoài JSON.
Transcript:
{transcript}
"""