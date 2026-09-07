"""生成示例 XLSX 文件（用于测试导入器）"""
import sys
from openpyxl import Workbook

OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "backend/scripts/sample_w3.xlsx"

wb = Workbook()
ws = wb.active
ws.title = "Candidates"

headers = [
    "source_product_id", "title", "description", "brand", "category",
    "price", "cost", "currency", "weight_g", "length_cm", "width_cm", "height_cm",
    "image_url_1", "image_url_2", "image_url_3", "supplier_sku", "source_url",
]
ws.append(headers)

rows = [
    ["XLSX-001", "Pet Cat Window Perch Hammock", "Sturdy pet bed for window sill", "PetBrand", "Pet Accessories", 22.99, 5.50, "USD", 400, 50, 30, 5, "https://example.com/img/cat1.jpg", "", "", "SKU-CAT-001", "https://example.com/p/XLSX-001"],
    ["XLSX-002", "Pet Bamboo Cutting Board for Dogs", "Eco bamboo chopping board for pet food", "KitchenCo", "Kitchen Utensils", 28.00, 6.00, "USD", 800, 40, 30, 2, "https://example.com/img/bam1.jpg", "", "", "SKU-BAM-001", "https://example.com/p/XLSX-002"],
    ["XLSX-003", "Phone USB C Hub 7-in-1 Adapter", "Multiport phone adapter with HDMI", "TechBrand", "Phone Accessories", 32.99, 8.50, "USD", 100, 12, 5, 2, "https://example.com/img/usb1.jpg", "", "", "SKU-USB-001", "https://example.com/p/XLSX-003"],
    ["XLSX-004", "Pet Yoga Block EVA Foam 2 Pack", "Lightweight pet exercise yoga blocks", "FitnessBrand", "Pet Accessories", 11.99, 2.50, "USD", 300, 30, 20, 10, "https://example.com/img/yog1.jpg", "", "", "SKU-YOG-001", "https://example.com/p/XLSX-004"],
    ["XLSX-005", "Fake Replica Brand Sneakers", "Style inspired by popular sneakers", "FakeBrand", "Footwear", 39.99, 8.00, "USD", 600, 30, 20, 12, "https://example.com/img/snk1.jpg", "", "", "SKU-SNK-001", "https://example.com/p/XLSX-005"],
    ["XLSX-006", "Pet Plant Grow Light for Indoor Garden", "Indoor pet-safe plant growth lamp with timer", "GardenBrand", "Pet Accessories", 19.99, 4.50, "USD", 500, 35, 12, 12, "https://example.com/img/plt1.jpg", "", "", "SKU-PLT-001", "https://example.com/p/XLSX-006"],
    ["XLSX-007", "Pet Resistance Bands Set 5 Pack", "Pet fitness exercise bands with door anchor", "FitnessBrand", "Pet Accessories", 14.99, 2.50, "USD", 700, 25, 15, 5, "https://example.com/img/res1.jpg", "", "", "SKU-RES-001", "https://example.com/p/XLSX-007"],
]
for row in rows:
    ws.append(row)

wb.save(OUTPUT)
print(f"已生成 XLSX：{OUTPUT}（{len(rows)} 行候选，含 1 个侵权商品）")