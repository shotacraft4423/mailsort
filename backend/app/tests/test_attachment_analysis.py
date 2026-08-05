from __future__ import annotations

import io

from app.services import attachment_analysis_service as svc


def test_classify_kind_by_filename_keywords():
    assert svc.classify_kind(file_name="山田太郎_スキルシート.xlsx", extracted_text="") == "skill_sheet"
    assert svc.classify_kind(file_name="2024年8月分_請求書.pdf", extracted_text="") == "invoice"
    assert svc.classify_kind(file_name="基本契約書_20240801.docx", extracted_text="") == "contract"
    assert svc.classify_kind(file_name="random.pdf", extracted_text="今月の飲み会のお知らせです") == "other"


def test_classify_kind_falls_back_to_extracted_text_when_filename_is_generic():
    assert svc.classify_kind(file_name="document.pdf", extracted_text="本書は個別契約書として...") == "contract"


def test_extract_text_docx_round_trip():
    import docx

    buffer = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("案件名: Javaエンジニア募集")
    document.add_paragraph("単価: 70万円")
    document.save(buffer)

    text = svc.extract_text(
        file_name="案件票.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=buffer.getvalue(),
    )
    assert "Javaエンジニア募集" in text
    assert "70万円" in text


def test_extract_text_xlsx_round_trip():
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["氏名", "スキル", "単価"])
    sheet.append(["A氏", "Java, Spring", "65万円"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    text = svc.extract_text(
        file_name="skill_sheet.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data=buffer.getvalue(),
    )
    assert "Java, Spring" in text
    assert "65万円" in text


def test_extract_text_invalid_pdf_bytes_returns_empty_string_not_raise():
    text = svc.extract_text(file_name="broken.pdf", content_type="application/pdf", data=b"not a real pdf")
    assert text == ""


def test_extract_text_plain_text_uses_utf8_decode():
    text = svc.extract_text(file_name="notes.txt", content_type="text/plain", data="メモ書き".encode("utf-8"))
    assert text == "メモ書き"


def test_analyze_returns_kind_and_text_together():
    import docx

    buffer = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("請求書 合計金額 500,000円")
    document.save(buffer)

    result = svc.analyze(
        file_name="invoice.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=buffer.getvalue(),
    )
    assert result.kind == "invoice"
    assert "500,000円" in result.extracted_text
