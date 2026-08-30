# Phân tích Fastboy Marketing & Đề xuất NailOS

> Tài liệu tổng hợp phần nghiên cứu về Fastboy Marketing (Go Checkin / Go POS) và đề xuất
> xây dựng nền tảng quản lý tiệm dịch vụ "NailOS", kèm phần mở rộng chiến lược marketing funnel.

## 1. Tổng quan công ty Fastboy Marketing

Fastboy Marketing là công ty marketing và công nghệ có trụ sở tại Mỹ (hiện ở Houston, Texas)
do người Việt sáng lập và điều hành, chuyên cung cấp giải pháp marketing online và phần mềm
quản lý cho các tiệm nails, spa và doanh nghiệp nhỏ do người Việt làm chủ tại Mỹ. Công ty có
hơn 16,000 khách hàng, doanh thu hơn 10 triệu đô/năm và 2 năm liền lọt vào Inc. 5000 (Top
công ty phát triển nhanh nhất nước Mỹ).

## 2. Mô hình quản lý — Phần mềm Go POS

| Module | Chức năng |
| --- | --- |
| QR Check-in | Khách checkin lấy ticket → thợ note dịch vụ → scan QR tính tiền |
| App Chủ | Xem income, payroll, lịch hẹn, tips từng service từ xa |
| App Thợ | Xem thông tin cá nhân, turn, thu nhập |
| Go Booking Online | Đặt hẹn từ Google, Facebook; auto-remind để giảm no-show |
| Marketing Automation | SMS Reminder, Promotion, Happy Birthday tự động |
| Payroll | Tính lương thợ, chia turn, bán gift card, report |
| Review Management | Tự động tăng review trên Google/Facebook |

## 3. Mô hình kinh doanh (Business Model)

Fastboy không chỉ là công ty quảng cáo mà là nhà cung cấp giải pháp công nghệ toàn diện cho
tiệm nails — kết hợp phần mềm quản lý Go Checkin POS và marketing tự động, giải quyết đúng
vấn đề thực tế của các chủ tiệm người Việt tại Mỹ.

Điểm mạnh của mô hình:

- Tập trung ngách hẹp (niche): tiệm nails người Việt ở Mỹ
- Bundle phần mềm + marketing + quảng cáo = một gói duy nhất
- Phần cứng (máy POS Intel) + phần mềm = doanh thu kép
- SaaS subscription → doanh thu định kỳ ổn định

## 4. Đề xuất: "NailOS" — Nền tảng quản lý toàn diện cho tiệm dịch vụ

Thay vì copy y chang Fastboy, có thể mở rộng sang nhiều ngành dịch vụ (nails, spa, tóc, thẩm
mỹ, massage) — hướng chuyển đổi từ "công ty cho tiệm nails" sang "nền tảng quản lý và
marketing số hàng đầu cho các doanh nghiệp nhỏ".

### 4.1 Kiến trúc module đề xuất

```
NailOS Platform
├── App Khách hàng
│   ├── QR Check-in / Đặt lịch online
│   ├── Xem lịch sử dịch vụ
│   └── Nhận ưu đãi, nhắc lịch
│
├── App Thợ/Nhân viên
│   ├── Xem turn & lịch làm việc
│   ├── Ghi note dịch vụ
│   └── Xem thu nhập cá nhân
│
├── Dashboard Chủ Tiệm
│   ├── Real-time revenue
│   ├── Payroll & chia turn
│   ├── Quản lý nhân viên
│   └── Báo cáo phân tích
│
└── Marketing Engine
    ├── SMS/Email tự động
    ├── Tăng review Google
    ├── Loyalty points
    └── Campaign quản lý
```

### 4.2 Stack công nghệ gợi ý

| Layer | Technology |
| --- | --- |
| Frontend Web | React + Tailwind CSS |
| Mobile App | React Native (iOS + Android) |
| Backend | Node.js / FastAPI |
| Database | PostgreSQL + Redis |
| Cloud | AWS / GCP |
| SMS/Email | Twilio, SendGrid |
| Payment | Stripe |

### 4.3 Lộ trình phát triển (MVP → Scale)

**Giai đoạn 1 — MVP (3–4 tháng)**
- QR Check-in + Ticket system
- App chủ + App thợ cơ bản
- Tính tiền & payroll đơn giản

**Giai đoạn 2 — Growth (3–6 tháng)**
- Đặt lịch online (tích hợp Google/Facebook)
- SMS auto-reminder & marketing
- Báo cáo doanh thu nâng cao

**Giai đoạn 3 — Scale**
- Mở rộng sang spa, tóc, thẩm mỹ
- AI phân tích xu hướng khách hàng
- Multi-branch management

### 4.4 Điểm khác biệt so với Fastboy

| Tiêu chí | Fastboy | Đề xuất NailOS |
| --- | --- | --- |
| Thị trường | Mỹ/Canada | Việt Nam + Đông Nam Á |
| Ngành | Chỉ nails | Nails + Spa + Tóc + Massage |
| Ngôn ngữ | Tiếng Việt cho Việt kiều | Tiếng Việt bản địa |
| Phần cứng | Bán máy POS riêng | Dùng tablet/điện thoại sẵn có |
| Giá | ~$100–200/tháng USD | Phù hợp thị trường VN |

## 5. UX Flow & Database Schema (tóm tắt)

Bản UX/schema đầy đủ (dashboard preview, 3 luồng người dùng Khách hàng → Chủ tiệm → Nhân
viên, wireframe 3 màn hình chính) được dựng thành prototype React riêng (`Nailos ux schema`).
Điểm chính của schema:

- **Kiến trúc đa tenant (multi-tenant SaaS)**: bảng `tenants` — mỗi tiệm là một tenant.
- **`tickets`**: bảng lõi, mỗi lượt khách checkin/tính tiền là một record.
- **`ticket_services`**: quan hệ nhiều-nhiều giữa ticket và các dịch vụ được thực hiện.
- **`campaigns`**: marketing automation, dùng cột JSONB để lưu trigger rules linh hoạt
  (birthday, no-show reminder, promotion...).
- Tổng cộng schema đề xuất gồm 8 bảng, phủ đủ 8 module trong module map (khách hàng, thợ,
  ticket, dịch vụ, payroll, campaign, review, tenant).

## 6. Mở rộng chiến lược Marketing Funnel

Rà soát lại phễu marketing cho thấy còn một số yếu tố quan trọng nên bổ sung:

### Top of Funnel (Nhận diện thương hiệu)
- **Hiện diện siêu địa phương (hyperlocal)**: tăng độ nhận diện trên các nền tảng lân cận
  như Facebook Groups khu phố, Nextdoor, Patch.
- **Tối ưu Bing SEO**: optimize riêng cho Bing vì Microsoft đang dùng Bing cho các sản phẩm AI.
- **Phân phối review tổng hợp**: hiển thị các review 5 sao trên website, trong tiệm, quảng cáo.

### Middle of Funnel (Giáo dục & gắn kết)
- **Trang FAQ và nội dung Q&A** để trả lời các câu hỏi phổ biến trước khi đặt lịch.
- **Video hướng dẫn vẽ nail** để xây dựng uy tín chuyên gia.
- **Chuỗi email nuôi dưỡng (nurturing)** để giáo dục khách hàng tiềm năng theo thời gian.

### Bottom of Funnel (Chuyển đổi & trung thành)
- **Phục hồi đơn đặt lịch bị bỏ dở**: phân tích lý do, follow-up cá nhân hoá.
- **Predictive upsell**: gợi ý các dịch vụ add-on phù hợp để tăng giá trị đơn hàng.
- **Chương trình giới thiệu (referral program)** để khuyến khích truyền miệng.

Việc bổ sung các yếu tố này giúp tối ưu toàn bộ hành trình khách hàng — từ lúc khám phá ban
đầu đến khi giữ chân lâu dài — thay vì chỉ tập trung vào giai đoạn chuyển đổi.
