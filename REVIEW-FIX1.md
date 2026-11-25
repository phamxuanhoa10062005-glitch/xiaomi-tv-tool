# Rà soát bản fix1 — 2026-11-26

Nguồn: ZIP người dùng cung cấp xiaomi-tv-tool-ban-fix1.zip. Đã đọc FIXES.md và kiểm tra mã thực tế, không coi các câu trong tài liệu là bằng chứng đã thử TV thật.

## Kết quả

ZIP nguồn hợp lệ, SHA256 gói lồng khớp, manager.py bên ngoài trùng bên trong, mọi APK/ảnh/tài nguyên khớp payload-hashes.json. Đây là nhánh2.5.1 (VXM/mitv), KHÔNG phải nhánhGoogle2.6 và không chứa project.apk mới. Giữ đúng nhánh người dùng yêu cầu rà soát trong lần này.

## Lỗi đã sửa bổ sung trước khi phát hành

1. Bảnfix1 có thể tắt toàn bộ package đang giữ HOME. Với log thực tế, đó có thể là com.xiaomi.mitv.settings chứaFallbackHome. Bảnreviewed chỉ cho phép tầngfallback tắt com.mitv.tvhome; không tắt Settings, SystemUI, android hay package bất kỳ.
2. Khi chặn reboot ở nhánhASTR0, bảnfix1 chỉ bật lại gói do tầngfallback tắt, nhưng bước9 đã tắt tvhome trước đó. Vì thế có thể để lại tvhome tắt và HOME chưa xác nhận. Bảnreviewed thử khôi phục cả các gói vừa tắt trong quy trình; không bật gói đã tắt từ trước lượt cài. APK/tài nguyên/settings đã cài vẫn giữ, có báo chưa hoàn tất.
3. Trạng thái theo dõi gói tắt được xóa đầu mỗi lượt; lỗi đọc trạng thái dừng thay vì coi gói đang bật; ghi nhận trước khi gửi disable để vẫn thử phục hồi nếu mất kết nối sau khi TV đã tắt gói.
4. Bộ tải dùng staging riêng từng lượt; kiểm tra compile manager và mọi hash tài nguyên trước thay bản cũ; không bỏ qua lỗi sao chép logs/profiles; cố trả lại bản cũ nếu đổi staging thất bại. Không mang google-profile.json cũ sang nhánhVXM.

## Kiểm tra đã chạy

- 23 kiểm tra hồi quy (workflow, gói theoSDK, ASTR0, preflight, cài lỗi, phiên bản mới hơn, kết nối/thử lại, Enter).
- 8 kiểm tra bổ sung: HOME chỉ đổi sau disable, FallbackHome không bị tắt, firmware từ chối disable, lỗi đọc trạng thái, mất kết nối sau disable, gói đã tắt từ trước, khôi phục nhánhASTR0 khi reboot bịchặn, không lẫn theo dõi giữaTV.
- 6 kiểm tra bộ tải bằng shellMSYS thật, ADB và tải mạng được môphỏng: cập nhật tốt/giữlog+bản dựphòng, SHAarchive sai, SHApayload sai, thiếumanager, ZIP traversal, thay thưmục thấtbại và trảbảncũ.
- sh -n cho start.sh và xác minh tính toàn vẹnZIP/tài nguyên.

## Giới hạn thực tế

Chưa chạy bảnfix1 hoặc reviewed trên TV thật. Trong log cũ, tvhome đã disabled thành công và HOME vẫn làFallbackHome; giả thuyết trong FIXES.md rằng tvhome chưa tắt KHÔNG giải thích đủ trường hợp đó. Bảnreviewed sẽ KHÔNG tắtSettings để ép vượt kiểmtra. Không công bố là đã sửa triệt để đenmàn, mic hoặc tắt/bật nguồn.

## Phát hành

Phiênbản hiểnthị: 2.5.1-fix1-reviewed.
Đăng start.sh lên main và xiaomi-phone.zip + xiaomi-phone.zip.sha256 cùng một Release, đánh dấu latest. Giữ release cũ để có thể quay lại.
Điệnthoại cần tải lại start.sh mới, không chỉ chạy file tv-start.sh đã có:

```sh
curl -fsSL https://raw.githubusercontent.com/phamxuanhoa10062005-glitch/xiaomi-tv-tool/main/start.sh -o tv-start.sh &&
sh tv-start.sh phamxuanhoa10062005-glitch/xiaomi-tv-tool
```

Chỉ xácnhận vận hành sau khi TVthật qua Home, mic, reboot và tắt/bậtnguồn.
