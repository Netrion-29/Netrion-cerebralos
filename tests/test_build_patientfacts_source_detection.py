import pytest
from pathlib import Path
from cerebralos.ntds_logic.build_patientfacts_from_txt import build_patientfacts, SourceType, _is_section_header

def test_true_header_switches_source():
    lines = [
        "PHYSICIAN NOTE:",
        "Some physician note text.",
        "IMAGING:",
        "Imaging report text.",
        "CONSULT NOTE:",
        "Consult note body."
    ]
    path = Path("/tmp/fake_patient.txt")
    content = "\n".join(lines)
    path.write_text(content)
    pf = build_patientfacts(path, {})
    # Only body lines are in evidence: indices 0,1,2
    assert pf.evidence[0].source_type == SourceType.PHYSICIAN_NOTE  # 'Some physician note text.'
    assert pf.evidence[1].source_type == SourceType.IMAGING         # 'Imaging report text.'
    assert pf.evidence[2].source_type == SourceType.CONSULT_NOTE    # 'Consult note body.'


def test_inline_mention_does_not_switch_source():
    lines = [
        "PHYSICIAN NOTE:",
        "Imaging performed - CTH no acute process/bleed, CTPE - no acute PE...",
        "Assessment: AKI m/l 2/2 to volume/hypoperfusion"
    ]
    path = Path("/tmp/fake_patient2.txt")
    content = "\n".join(lines)
    path.write_text(content)
    pf = build_patientfacts(path, {})
    # Only body lines are in evidence
    for ev in pf.evidence:
        assert ev.source_type == SourceType.PHYSICIAN_NOTE


def test_regression_consult_with_inline_imaging():
    lines = [
        "CONSULT NOTE:",
        "Imaging performed - CTH no acute process/bleed, CTPE - no acute PE...",
        "Assessment: AKI m/l 2/2 to volume/hypoperfusion"
    ]
    path = Path("/tmp/fake_patient3.txt")
    content = "\n".join(lines)
    path.write_text(content)
    pf = build_patientfacts(path, {})
    # Only body lines are in evidence
    for ev in pf.evidence:
        assert ev.source_type == SourceType.CONSULT_NOTE


def test_bracketed_header_and_timestamp():
    lines = [
        "[PHYSICIAN_NOTE] 01/15/26 0830",
        "Some physician note text.",
        "IMAGING: 01/15/26 0900",
        "Imaging report text.",
        "CONSULT NOTE: 01/15/26 1000",
        "Consult note body."
    ]
    path = Path("/tmp/fake_patient4.txt")
    content = "\n".join(lines)
    path.write_text(content)
    pf = build_patientfacts(path, {})
    # Evidence should skip header lines, so evidence[0] is first body line
    assert pf.evidence[0].source_type == SourceType.PHYSICIAN_NOTE
    assert pf.evidence[1].source_type == SourceType.IMAGING
    assert pf.evidence[2].source_type == SourceType.CONSULT_NOTE

def test_imaging_header_and_inline():
    lines = [
        "IMAGING:",
        "Imaging report text.",
        "PHYSICIAN NOTE:",
        "Imaging performed - CTH no acute process/bleed, CTPE - no acute PE...",
        "Assessment: AKI m/l 2/2 to volume/hypoperfusion"
    ]
    path = Path("/tmp/fake_patient5.txt")
    content = "\n".join(lines)
    path.write_text(content)
    pf = build_patientfacts(path, {})
    # Only body lines are in evidence: indices 0,1,2
    assert pf.evidence[0].source_type == SourceType.IMAGING           # 'Imaging report text.'
    assert pf.evidence[1].source_type == SourceType.PHYSICIAN_NOTE    # 'Imaging performed ...'
    assert pf.evidence[2].source_type == SourceType.PHYSICIAN_NOTE    # 'Assessment: ...'


def test_header_lines_excluded_from_evidence():
    """Header lines must not appear as evidence rows."""
    lines = [
        "PHYSICIAN NOTE:",
        "Note body line 1.",
        "IMAGING:",
        "Imaging body line 1.",
    ]
    path = Path("/tmp/fake_patient6.txt")
    content = "\n".join(lines)
    path.write_text(content)
    pf = build_patientfacts(path, {})
    evidence_texts = [ev.text for ev in pf.evidence]
    assert "PHYSICIAN NOTE:" not in evidence_texts
    assert "IMAGING:" not in evidence_texts
    assert len(pf.evidence) == 2
    assert pf.evidence[0].text == "Note body line 1."
    assert pf.evidence[1].text == "Imaging body line 1."


def test_is_section_header_consistency():
    """_is_section_header must agree with _detect_source_type on what is/isn't a header."""
    # True headers
    assert _is_section_header("PHYSICIAN NOTE:") is True
    assert _is_section_header("IMAGING:") is True
    assert _is_section_header("CONSULT NOTE:") is True
    assert _is_section_header("[PHYSICIAN_NOTE] 01/15/26 0830") is True
    assert _is_section_header("IMAGING: 01/15/26 0900") is True
    # Inline mentions — NOT headers
    assert _is_section_header("Imaging performed - CTH no acute process/bleed") is False
    assert _is_section_header("Lab was ordered for CBC") is False
    assert _is_section_header("Imaging shows right-sided pneumothorax") is False
