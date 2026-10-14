# Báo cáo Lab 26 — COLOSSEUM

**Nhóm:** One-person-team  
**Thành viên:** Nguyễn Xuân Trường  
**MSSV:** 2A202602761  
**Ngày kiểm tra cuối:** 14/10/2026

## 1. Nội dung bài làm

Bài này tôi thực hiện một mình, gồm ba phần: bộ bài tấn công trong `deck/`,
chương trình công tố trong `eval/` và phần phòng thủ trong `agent/`.
Tôi sử dụng bộ kit và dữ liệu world do bài lab cung cấp.

### Phòng thủ

Trong `agent/gateway.py`, tôi kiểm tra yêu cầu trước khi cho phép gọi công cụ.
Các bước chính là kiểm tra công cụ có hợp lệ không, thông tin định tuyến có
nằm trong header không, vé truy cập còn hiệu lực không và yêu cầu có đúng
quyền của người học đang được phục vụ không. Gateway cũng tính chi phí dự
kiến và giới hạn số lần gọi một số công cụ.

Với yêu cầu ghi dữ liệu, gateway yêu cầu có `If-Match` từ kết quả provenance
đã nhận và `Idempotency-Key` để kiểm soát việc gọi lặp. Với các agent khác,
tôi kiểm tra việc chấp nhận agent và kỹ năng được phép gọi. Nếu có token
ủy quyền, chương trình dùng hàm kiểm tra của kit để kiểm tra token.

Trong `agent/guardrails.py`, tôi bổ sung kiểm tra nguồn trích dẫn, một số
dấu hiệu chèn chỉ dẫn, nội dung được đánh dấu riêng tư và phép tính đơn giản.
`agent/defender.py` nối các kiểm tra này vào bước nhận kết quả và trả lời.
Nếu câu trả lời thiếu nguồn hoặc thiếu trường bắt buộc, chương trình có
thể trả lời rằng chưa đủ thông tin. Phần này chỉ hoạt động khi nơi chạy
bài gọi wrapper đó.

### Công tố

Trong `eval/prosecute.py`, tôi dùng các sự kiện L1 để tìm bằng chứng về lỗi
của bên phòng thủ. Mỗi cáo buộc có tên lớp lỗi, bằng chứng, kết quả mong
đợi, kết quả quan sát được và phần giải thích. Chương trình giới hạn tối
đa 4 cáo buộc trong một lượt, tối đa 1 cáo buộc trong mỗi nhóm lỗi và phần
giải thích không quá 400 ký tự.

Hàm `prosecute` không đọc file, gọi mạng hoặc đọc đáp án ẩn khi xử lý trace.
Với các lỗi cần hiểu nội dung câu trả lời, chương trình hiện dùng những
dấu hiệu đơn giản nên chưa phát hiện được mọi trường hợp.

Trên 40 mẫu kiểm tra có sẵn, chương trình nộp 32 cáo buộc và cả 32 được
scorer mẫu xác nhận. Precision là 1,000 và recall khoảng 0,941. Hai mẫu
`stale_read` chưa được phát hiện vì trace không có đủ thông tin về độ lệch
và replica mới hơn. Đây là kết quả trên mẫu, không phải điểm giải đấu.

### Bộ bài tấn công

Bộ bài có 14 lá, gồm 10 lá tấn công và 4 lá trắng. Trong 10 lá tấn công có
4 lá thuộc lớp MCP, 4 lá thuộc lớp A2A và 2 lá thuộc lớp gateway, bao phủ
9 loại tấn công của lab.

Thứ tự chơi được lưu trong `deck/lineup.json`, gồm 10 lá không lặp. Tôi đặt
một lá trắng ở lượt 3 để thử cách xử lý câu hỏi sạch. Lá `replica_flip`
dùng `path_id=e0614beb`, thuộc tập có độ lệch trong world được cung cấp.

## 2. Kết quả kiểm tra trước khi nộp

Tôi dùng Ubuntu 26.04.1 LTS chạy trên WSL2, Python 3.12.9 và môi trường
Python riêng cho Linux. Các lệnh kiểm tra vẫn dùng target trong Makefile;
tham số `BIN` chỉ chọn đường dẫn môi trường Python này.

| Nội dung kiểm tra | Kết quả |
|---|---|
| `make test` | 4.608 passed, 7 skipped, không có failed. |
| `make validate` | 0 failing checks, không có FAIL; có 1 WARN về lethality. |
| `make doctor` | Đạt, có thông báo `ready to spar.` |
| 36 unittest bổ sung của bài làm | Cả 36 test đều đạt. |
| Git status của `kit/`, `bots/`, `fixtures/` | Không có thay đổi khi đối chiếu theo thiết lập của checkout Windows. |
| Kiểm tra import và G-KEY | Không phát hiện thư viện bên thứ ba hoặc import bị cấm; G-KEY đạt. Các import `kit`, `agent`, `eval` là module nội bộ của lab. |
| Bundle | Đã tạo `submissions/One-person-team.bundle`; nội dung, manifest và hash từng file khớp với bản nguồn hiện tại. |
| Thông tin thành viên | `K4-DAY26-One-person-team/TEAMMATES.md` có đủ họ tên, MSSV, tên nhóm và vai trò. |

Trước đó, chạy bộ test trên Windows có một lỗi do thư viện `msvcrt` không
có hàm `open` mà test sử dụng. Khi chạy lại trên Ubuntu WSL2, test này đã
đạt. Tôi không sửa test hoặc các thư mục được bảo vệ để xử lý lỗi đó.

Các test dành riêng cho sandbox macOS không chạy trên Linux theo điều
kiện có sẵn của kit. Vì vậy, kết quả pass trên Ubuntu chưa xác nhận được
sandbox macOS. Cảnh báo lethality cũng cho biết validator chỉ kiểm tra
theo các điều kiện cục bộ, chưa chứng minh kết quả trên arena thật.

Log kiểm tra được giữ ngoài gói nộp, trong `../wsl-final-checks/`.

Dự án nằm trên ổ Windows nên khi kiểm tra bằng Git trong WSL, tôi dùng
`-c core.autocrlf=true -c core.filemode=false` để đối chiếu đúng cách xử lý
xuống dòng và quyền file của checkout này. Lệnh trả về không có thay đổi;
tôi không sửa nội dung các file được bảo vệ hoặc lưu lại cấu hình Git.

## 3. Giới hạn và phần cần cải thiện

Bộ test hiện tại đã đạt, nhưng vẫn còn những điểm cần cải thiện trong code.
Đích ghi `learner` và `anchor` cần được ràng buộc chặt hơn; sau lỗi conflict
cần bắt buộc đọc lại provenance trước khi thử ghi lại. Giới hạn chi tiêu
hiện là 12 credits mỗi vòng, trong khi referee dùng ngưỡng 11.

Phần kiểm tra câu trả lời cần xử lý nguồn từ kết quả một phần cẩn thận hơn.
Prosecutor cũng cần tối ưu một vòng lặp để tránh vượt 5 giây trên trace
stress lớn. Các kiểm tra nội dung bằng mẫu và từ khóa chưa hiểu được mọi
cách diễn đạt. Việc sửa báo cáo lần này không thay đổi các phần code đó.

Spar dùng kế hoạch gọi công cụ và câu trả lời có sẵn, nên kết quả spar
không đủ để kết luận toàn bộ phần kiểm tra câu trả lời đã hoạt động trong
giải đấu. Hash kit trong bundle đã được đối chiếu với file hiện tại;
hash gate của giảng viên với bản gốc nhận ban đầu chưa được kiểm tra ở đây.

## 4. Gói bài nộp

Thư mục giao bài gồm:

```text
K4-DAY26-One-person-team/
├── TEAMMATES.md
└── One-person-team.bundle
```

Bundle được tạo bằng `make submit`, chứa `agent/`, `deck/`, `eval/` và
`MANIFEST.json`. Báo cáo này nằm trong `agent/` của bundle. Bản bundle
trong thư mục giao bài được đồng bộ với bản trong `submissions/`.
Không đóng gói môi trường Python, world, cache hoặc log kiểm tra.

Các lệnh chạy lại trên Ubuntu, từ thư mục gốc của dự án:

```bash
make test BIN="$HOME/.venvs/day26-check/bin"
make validate BIN="$HOME/.venvs/day26-check/bin"
make doctor BIN="$HOME/.venvs/day26-check/bin"
make submit BIN="$HOME/.venvs/day26-check/bin" TEAM=One-person-team
cp submissions/One-person-team.bundle K4-DAY26-One-person-team/One-person-team.bundle
```
