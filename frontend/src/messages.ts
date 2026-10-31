export function vietnameseMessage(message: string): string {
  if (/Review source transcript|Vietnamese text.*cues|Vietnamese cue text|Review Vietnamese text/i.test(message))
    return "Chưa có đủ lời Việt. Hãy nhập bản dịch vào từng câu hoặc nhập file SRT tiếng Việt trước khi xuất.";
  if (/Some cues failed|failed exact Vietnamese ASR/i.test(message))
    return "Một số câu vẫn bị đọc sai sau nhiều lần thử. Hãy sửa câu ngắn, rõ hơn rồi thử lại.";
  if (/No clean.*reference|Reference needs word timestamps/i.test(message))
    return "Chưa tìm được đoạn mẫu giọng sạch, đủ dài cho người nói. Hãy kiểm tra lại vai và mốc câu.";
  if (/paging file|1455|out of memory/i.test(message))
    return "Không đủ bộ nhớ để nạp model. Hãy đóng bớt ứng dụng rồi thử lại.";
  if (/unavailable or failed|configured Python environment/i.test(message))
    return "Bước xử lý chưa chạy được. Hãy kiểm tra runtime và nhật ký của tác vụ rồi thử lại.";
  if (/Failed to fetch|NetworkError|fetch failed/i.test(message))
    return "Mất kết nối với máy chủ. Hãy kiểm tra DubFlow đang chạy rồi thử lại.";
  if (/[À-ỹđĐ]/.test(message)) return message;
  return "Chưa thực hiện được thao tác. Hãy kiểm tra dữ liệu đầu vào và thử lại.";
}
