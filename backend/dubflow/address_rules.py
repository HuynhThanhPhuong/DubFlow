"""Quy tắc xưng hô chung cho API và lệnh mẫu AI chat."""

SETTINGS = ('auto', 'modern', 'ancient')
SETTING_LABELS = {'modern': 'Hiện đại', 'ancient': 'Cổ trang'}

ADDRESS_RULES = """BƯỚC 1 — BỐI CẢNH XƯNG HÔ: trước khi dịch, đọc toàn bộ lời thoại và gợi ý tên video/bộ sưu tập để xác định thời đại; ưu tiên bối cảnh đã khóa hoặc đã xác định ở phần trước.
- Hiện đại: đô thị, học đường, công sở, gia đình, truyền cảm hứng/nói với khán giả; dấu hiệu 手机, 公司, 老板, 学校, 微信, 开车.
- Cổ trang/cổ đại: cung đình, võ hiệp, tiên hiệp, huyền huyễn, dân quốc cổ; dấu hiệu 朕, 本王, 本宫, 陛下, 殿下, 师尊, 师父, 师兄, 师妹, 在下, 阁下, 公子, 姑娘, 娘子, 夫君, 前辈, 晚辈, 仙, 宗门, 山门, 神君, 魔. Xét cả ngữ cảnh, không kết luận chỉ từ một từ.
BƯỚC 2 — CHỌN XƯNG HÔ theo tuổi, vai vế và mức thân thiết:
- Hiện đại: tôi – bạn (trung tính, người lạ, khán giả, độc thoại truyền cảm hứng); cậu – tớ (bạn bè/bạn học cùng tuổi); anh – em, chị – em (tình yêu, vợ chồng, anh chị em, chênh tuổi); tao – mày (thù địch/gây gổ hoặc bạn rất thân suồng sã); con – bố/mẹ, cháu – ông/bà/chú/cô (gia đình); cấp trên/khách hàng: tôi – anh/chị/sếp.
- Cổ trang: ta – ngươi (mặc định ngang hàng, bề trên với bề dưới, thù địch); tình yêu: ta – nàng, ta – chàng, thiếp – chàng/phu quân; đồng môn: huynh – đệ, tỷ – muội, sư huynh – sư muội, sư tỷ – sư đệ; thầy trò: sư phụ/sư tôn – đồ nhi, vi sư – con; lễ nghi: tại hạ – các hạ/công tử/cô nương, vãn bối – tiền bối, lão phu; cung đình: trẫm – khanh/ái khanh, thần – bệ hạ, bổn vương, bổn cung, nô tỳ – chủ tử, phụ hoàng, mẫu hậu.
- Tên riêng và danh xưng Trung Quốc dùng âm Hán-Việt (大泽山 → Đại Trạch Sơn, 神君 → Thần Quân), trừ thuật ngữ người dùng đã chốt.
BƯỚC 3 — NHẤT QUÁN: mỗi cặp người giữ cùng cặp xưng hô suốt video; chỉ đổi khi quan hệ thay đổi (thù thành yêu, lộ thân phận). Nói với nhiều người dùng số nhiều phù hợp: các ngươi, chư vị, mọi người, các cậu. Không trộn thời đại: tránh ta – ngươi ở văn phòng hoặc tôi – bạn ở cung đình. Giữ ngôi nói của lời gốc."""


def normalize_setting(value) -> str:
    return value if isinstance(value, str) and value in SETTINGS else 'auto'


def valid_setting(value) -> dict | None:
    if not isinstance(value, dict) or not isinstance(value.get('era'), str) or value['era'] not in SETTING_LABELS:
        return None
    note = value.get('note')
    return {'era': value['era'], 'note': note if isinstance(note, str) else ''}


def locked_setting(choice: str) -> dict | None:
    choice = normalize_setting(choice)
    return {'era': choice, 'note': 'Người dùng khóa bối cảnh: ' + SETTING_LABELS[choice]} if choice != 'auto' else None


def setting_instruction(choice: str = 'auto') -> str:
    choice = normalize_setting(choice)
    if choice == 'auto':
        return 'BỐI CẢNH: Tự động. Tự xác định ở bước 1 trước khi dịch; nếu context.setting đã có thì kế thừa, không tự đổi thời đại giữa các phần.'
    return f'BỐI CẢNH KHÓA: {SETTING_LABELS[choice]} ({choice}) do người dùng chọn. Bắt buộc dùng thời đại này; không được tự đổi kể cả khi lời thoại gợi ý khác.'
