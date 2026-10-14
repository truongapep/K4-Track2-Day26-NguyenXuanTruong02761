# Báo cáo bài làm — One-person-team

Thành viên: **Nguyễn Xuân Trường — 2A202602761**.

## Phòng thủ

Gateway thực hiện bốn nhiệm vụ: định tuyến bằng header; kiểm tra lease và peer;
kiểm tra learner/scope theo ctx.act; kiểm soát ngân sách và rate window.
Không dùng ctx.sub làm quyền, không đoán canonical luôn mới hơn working.
Write cần pin etag từ provenance đáng tin và key chưa được cho phép trong duel.
Signed Agent Card dùng verify_card; structured delegation-token khi có dùng
verify_delegation để kiểm tra signature, audience, TTL, replay và act.
Không tự mint token trong gateway; các hàm mint chỉ dùng trong test.

Guardrails kiểm tra anchor theo trang/span/revision; nhận diện override imperative;
che nội dung nguồn đánh dấu private cả trong text và trường cấu trúc; kiểm tra
phép tính hai toán hạng và số liệu có nguồn. Khi thiếu nguồn/trường bắt buộc,
wrapper trả câu trả lời abstained. Nếu nguồn có a/b mâu thuẫn, nêu rõ bất đồng.
SafeEnvironment lọc hàng private/injection trước lượt model tiếp theo và kiểm tra
ANSWER trước khi chuyển tới trusted executor; không thay quyền thực thi của arena.
Prompt vẫn được nối sau prompt harness, giữ grammar và giới hạn lượt/thời gian.

## Công tố

17 entry point phát hiện lỗi theo L1 trace, câu trả lời và ask; các heuristic ngữ
nghĩa chỉ nêu khi có dấu hiệu rõ. Budget giữ tối đa 4 claim, tối đa 1 mỗi family,
argument tối đa 400 ký tự. Ưu tiên enforcement_failure trước protocol_misuse trong A.
Không đọc file, truth.json, fixture đáp án, mạng hay đồng hồ trong prosecute.

Kết quả trên 40 fixture: precision **1.000**, recall **0.941**, F1 **0.970**,
false_claim_rate **0.000**. Hai stale_read fixture thiếu metadata drift/fresher
trong trace nên không nêu cáo buộc chỉ từ việc thấy citation `/c/`.
Kết quả fixture là phép đo cục bộ, không bảo đảm điểm trọng tài giải đấu.

## Bộ bài

14 lá: 10 attack + 4 blank; giữ cân bằng layer/class và các anchor đã kiểm chứng
trong world df8c55dabb35. Thay defense_event mọi attack thành gateway.denied để
khớp proxy validator; schema_bomb dùng 24 hàng decoy thay vì dump 40 hàng mẫu.
Lineup có 10 lá không lặp, đưa blk_01 vào round 3 để thử false positive trên câu
hỏi sạch, thay atk_09. Các identity attack giữ ở cuối để tận dụng round scale.
Đây là lựa chọn chiến thuật, không khẳng định tối ưu.

Validator trên world thật: **0 failing checks, 1 warning** về lethality band.
Proxy kit không chứng minh hoàn toàn lethality trong tournament.

## Kiểm tra cuối

- Đúng phạm vi tương đương `make test`: G-KEY đạt; `pytest tests/` có
  **4.607 passed, 1 failed, 7 skipped**. Mục “make test pass” **chưa đạt** trên
  Windows hiện tại. Không coi test bổ sung đạt là thay thế cho bộ test BTC.

- 36 unittest bổ sung đạt: gateway 17, guardrails/wrapper 11, công tố 8.
- Full pytest: **4.643 passed, 1 failed, 7 skipped**; lỗi duy nhất là test sandbox
  Windows gọi libc.open không tồn tại. Không sửa/skip test để làm kết quả đạt giả.
- G-KEY đạt; không thay kit/, bots/, fixtures/, tests/ hoặc RULES.md.
- Trận all: Rookie seed 1 thắng **100–0**; Operator seed 2 thắng **75–0**;
  Adversary seed 2 thua **16–25**. Không tuyên bố thắng mọi bot hoặc mọi seed.

Spar dùng kế hoạch tool/answer cố định, không gọi prompt hoặc wrapper mới; vì vậy
chỉ dùng test tích hợp loop để xác nhận wrapper hoạt động, không lấy điểm spar
làm bằng chứng hiệu quả guardrails. Spar cũng tạo gateway mỗi exchange và chưa
cập nhật đầy đủ lease/history; test riêng kiểm tra state qua nhiều round.

## Giới hạn thực tế

Heuristic injection/semantic/quantity không hiểu được mọi paraphrase, phủ định
hay phép tính phức tạp. Cần nguồn private đáng tin để redact; không thể suy ra mọi
dữ liệu nhạy cảm từ văn bản không có metadata. Prompt có thể được arena sử dụng
độc lập; wrapper chỉ có hiệu lực khi caller dùng run_defender.
Token chưa có trên command chỉ đi qua trusted peer admission/harness path;
gateway không tuyên bố đã verify token không được cung cấp.
Pacing dự toán theo tool spec; số lần write/rate đếm lần cho phép nên bảo thủ
khi executor thất bại. Sandbox macOS chưa thể đo trên Windows này.

## Nộp bài

Repository của bài: https://github.com/truongapep/K4-Track2-Day26-NguyenXuanTruong02761.git

Thư mục giao bài cục bộ:

```text
K4-DAY26-One-person-team/
├── TEAMMATES.md
└── One-person-team.bundle
```

Bundle được tạo bằng kit.submit với tên team chính xác, bao gồm agent/, deck/,
eval/, MANIFEST.json và hash kit. Báo cáo team nằm trong agent/ của bundle.
TEAMMATES.md ở ngoài bundle theo cấu trúc được yêu cầu. Không chứa .venv, world,
token đăng nhập, runs hoặc cache. Agent/deck khóa lúc bắt đầu session theo luật.
Đóng gói tạo file cục bộ; nộp bằng kênh do BTC quy định, chưa tự gửi lên GitHub.

```powershell
python -m unittest agent.test_gateway_policy agent.test_guardrails eval.test_prosecution_detectors -v
python -m pytest tests/ agent/test_gateway_policy.py agent/test_guardrails.py eval/test_prosecution_detectors.py -q
python -m eval.prosecute
python -m kit.gate_no_key
python validate_deck.py deck/deck.json deck/lineup.json --world kit/world/df8c55dabb35/
python -m kit.submit --team "One-person-team"
Copy-Item -LiteralPath ".\submissions\One-person-team.bundle" -Destination ".\K4-DAY26-One-person-team\One-person-team.bundle" -Force
```
