---
tags: [deney, kalibrasyon]
tarih: 2026-07-04
sonuç: veto-korundu
---

# Karşı-Trend Analizi — "Vetoyu Kaldır" İddiasının Testi

**Bağlam:** Gemini "1h trendin tersine işlem intihardır, veto delme kuralını tamamen kaldır" dedi (tek işleme bakarak, sonucunu bilmeden). Sonnet "önce alt kümeyi ölç" dedi. Ölçtük.

**Yöntem:** Doğrulama setinde SHORT sinyalleri, 1h trend yönüne göre ikiye bölündü; her proba diliminin gerçek isabeti ayrı ölçüldü. Başabaş: %40.

## Sonuç

| Dilim | Trend uyumlu | **Karşı-trend** |
|---|---|---|
| 0.55–0.63 | %54.9 (n=1080) | %47.8 (n=959) |
| 0.63–0.70 (veto delen) | %75.7 (n=378) | **%70.4 (n=355)** |
| 0.70+ (veto delen) | %95.9 (n=341) | **%83.3 (n=347)** |

## Yorum

- Vetoyu delen karşı-trend sinyaller başabaşın **30-43 puan üzerinde** — "intihar" iddiası veriyle çürüdü.
- Karşı-trend, uyumludan tutarlı şekilde 5-12 puan zayıf → +0.15'lik ek çıta tam bu farkı fiyatlıyor; tasarım doğru kalibre.
- İlk paper işlem (2026-07-03, ETH SHORT p=0.70) %83.3'lük dilimdendi.

**Karar:** Veto delme kuralı korundu. → [[Kararlar-Kaydı]] K-11

## Ders
Tek işlemden genel kural çıkarma; alt küme iddiası varsa **alt kümeyi ayrıca kalibre et**. Genel kalibrasyonun bir alt kümede tutacağı varsayılamaz — burada tuttu, ama ölçmeden bilinemezdi.
