#!/usr/bin/env python3
"""
Tests for injury extraction — QA lock-in.

Covers:
  trauma_doc_extractor:
    - _extract_impression: IMPRESSION vs FINDINGS fallback, empty text
    - _split_impression_sentences: numbered items, sentence splitting
    - _extract_primary_injuries: negative filter, chronic/incidental filter,
      acute keyword exception, deduplication, max 8, NOT DOCUMENTED sentinel

  evidence_utils:
    - extract_injuries_from_imaging: keyword matching, section detection
    - extract_injuries_from_impression: historical filtering, keyword match,
      bullet cleanup, demographic skip
    - is_historical_reference: known patterns, negatives
"""

import sys
from pathlib import Path

import pytest

# Ensure project root is on import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.reporting.trauma_doc_extractor import (
    _extract_impression,
    _extract_primary_injuries,
    _NOT_DOCUMENTED,
    _split_impression_sentences,
    _snippets_by_type,
)
from cerebralos.reporting.evidence_utils import (
    extract_injuries_from_imaging,
    extract_injuries_from_impression,
    is_historical_reference,
)


# ═════════════════════════════════════════════════════════════════════
# _extract_impression tests
# ═════════════════════════════════════════════════════════════════════

class TestExtractImpression:
    """Lock in radiology IMPRESSION extraction logic."""

    def test_impression_section_extracted(self):
        text = "HISTORY: Fall\nIMPRESSION: Acute rib fractures\n\nFINDINGS: stuff"
        result = _extract_impression(text)
        assert "Acute rib fractures" in result

    def test_findings_fallback(self):
        text = "HISTORY: Fall\nFINDINGS: Rib fractures bilateral"
        result = _extract_impression(text)
        assert "Rib fractures bilateral" in result

    def test_impression_preferred_over_findings(self):
        text = (
            "FINDINGS: Detailed findings here.\n"
            "IMPRESSION: Concise summary here."
        )
        result = _extract_impression(text)
        assert "Concise summary" in result

    def test_empty_impression_falls_to_findings(self):
        text = "IMPRESSION:\n\nFINDINGS: Actual content here"
        result = _extract_impression(text)
        assert "Actual content here" in result

    def test_no_sections_returns_empty(self):
        text = "Random radiology text without sections"
        result = _extract_impression(text)
        assert result == ""

    def test_empty_text(self):
        assert _extract_impression("") == ""

    def test_impression_stops_at_technique(self):
        text = "IMPRESSION: Fracture noted TECHNIQUE: CT scan with contrast"
        result = _extract_impression(text)
        assert "Fracture noted" in result
        assert "CT scan with contrast" not in result

    def test_impression_case_insensitive(self):
        text = "impression: small subdural hematoma"
        result = _extract_impression(text)
        assert "subdural hematoma" in result


# ═════════════════════════════════════════════════════════════════════
# _split_impression_sentences tests
# ═════════════════════════════════════════════════════════════════════

class TestSplitImpressionSentences:
    """Lock in impression text splitting logic."""

    def test_numbered_items(self):
        text = "1. Rib fractures. 2. Pneumothorax. 3. Hemothorax."
        result = _split_impression_sentences(text)
        assert len(result) >= 2

    def test_sentence_splitting(self):
        text = "Rib fractures noted. No pneumothorax. Small effusion."
        result = _split_impression_sentences(text)
        assert len(result) >= 2

    def test_single_sentence(self):
        text = "No acute findings"
        result = _split_impression_sentences(text)
        assert len(result) == 1
        assert "No acute findings" in result[0]

    def test_empty_returns_empty(self):
        result = _split_impression_sentences("")
        assert result == []

    def test_numbered_preferred_over_sentence_split(self):
        """When numbered items are found, they take precedence."""
        text = "1. Acute rib fractures. 2. Small pneumothorax."
        result = _split_impression_sentences(text)
        assert any("rib fractures" in r.lower() for r in result)
        assert any("pneumothorax" in r.lower() for r in result)


# ═════════════════════════════════════════════════════════════════════
# _snippets_by_type tests
# ═════════════════════════════════════════════════════════════════════

class TestSnippetsByType:
    """Lock in evidence snippet filtering."""

    def test_returns_matching_type(self):
        ev = {"all_evidence_snippets": [
            {"source_type": "RADIOLOGY", "text": "CT Head"},
            {"source_type": "LAB", "text": "CBC"},
            {"source_type": "RADIOLOGY", "text": "XR Chest"},
        ]}
        result = _snippets_by_type(ev, "RADIOLOGY")
        assert len(result) == 2

    def test_returns_empty_for_no_match(self):
        ev = {"all_evidence_snippets": [
            {"source_type": "LAB", "text": "CBC"},
        ]}
        result = _snippets_by_type(ev, "RADIOLOGY")
        assert result == []

    def test_empty_evidence(self):
        ev = {"all_evidence_snippets": []}
        result = _snippets_by_type(ev, "RADIOLOGY")
        assert result == []

    def test_missing_snippets_key(self):
        ev = {}
        result = _snippets_by_type(ev, "RADIOLOGY")
        assert result == []


# ═════════════════════════════════════════════════════════════════════
# _extract_primary_injuries tests
# ═════════════════════════════════════════════════════════════════════

class TestExtractPrimaryInjuries:
    """Lock in primary injury extraction from RADIOLOGY evidence."""

    def _make_ev(self, radiology_texts):
        """Build minimal evidence dict with RADIOLOGY snippets."""
        return {
            "all_evidence_snippets": [
                {"source_type": "RADIOLOGY", "text": t}
                for t in radiology_texts
            ]
        }

    def test_acute_fracture_extracted(self):
        ev = self._make_ev(["IMPRESSION: Acute rib fracture right side"])
        result = _extract_primary_injuries(ev)
        assert "fracture" in result.lower()

    def test_multiple_injuries(self):
        ev = self._make_ev([
            "IMPRESSION: 1. Acute rib fractures. 2. Small pneumothorax."
        ])
        result = _extract_primary_injuries(ev)
        assert "fracture" in result.lower()
        assert "pneumothorax" in result.lower()

    def test_negative_findings_filtered(self):
        ev = self._make_ev([
            "IMPRESSION: No acute fracture. No pneumothorax. Unremarkable exam."
        ])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_no_evidence_no_fracture_filtered(self):
        ev = self._make_ev([
            "IMPRESSION: No evidence of acute injury"
        ])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_chronic_degenerative_filtered_without_acute(self):
        """Chronic/degenerative findings are filtered when no acute keyword."""
        ev = self._make_ev([
            "IMPRESSION: Degenerative changes of the lumbar spine"
        ])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_chronic_with_acute_keyword_kept(self):
        """If an acute injury keyword is present, chronic filter is bypassed."""
        ev = self._make_ev([
            "IMPRESSION: Degenerative changes with acute fracture noted"
        ])
        result = _extract_primary_injuries(ev)
        assert "fracture" in result.lower()

    def test_incidental_findings_filtered(self):
        """Non-injury clinical findings are filtered when no acute keyword."""
        ev = self._make_ev([
            "IMPRESSION: Mild atelectasis. Pleural effusion. Cardiomegaly."
        ])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_unchanged_without_hemorrhage_filtered(self):
        """'Unchanged' alone is filtered (starts-with check)."""
        ev = self._make_ev([
            "IMPRESSION: Unchanged appearance of the chest"
        ])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_unchanged_with_hemorrhage_kept(self):
        """'Unchanged hemorrhage' is kept."""
        ev = self._make_ev([
            "IMPRESSION: Unchanged subdural hemorrhage"
        ])
        result = _extract_primary_injuries(ev)
        assert "hemorrhage" in result.lower()

    def test_deduplication_by_prefix(self):
        """Duplicate injuries (by normalized 50-char prefix) are deduplicated."""
        # Two sentences whose first 50 chars (lowered) are identical → dedup
        base = "Acute comminuted fracture of the right femoral shaft with"
        ev = self._make_ev([
            f"IMPRESSION: {base} displacement",
            # Second study with same 50-char prefix but different tail
            f"IMPRESSION: {base} surgical fixation recommended",
        ])
        result = _extract_primary_injuries(ev)
        parts = result.split("; ")
        assert len(parts) == 1

    def test_max_8_injuries(self):
        """At most 8 unique injuries are returned."""
        texts = [f"IMPRESSION: Type_{i} fracture" for i in range(12)]
        ev = self._make_ev(texts)
        result = _extract_primary_injuries(ev)
        parts = result.split("; ")
        assert len(parts) <= 8

    def test_no_radiology_returns_not_documented(self):
        ev = {"all_evidence_snippets": []}
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_short_sentences_filtered(self):
        """Sentences < 5 chars are skipped."""
        ev = self._make_ev(["IMPRESSION: OK"])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_delimiter_lines_filtered(self):
        """Lines that are only dashes/underscores are filtered."""
        ev = self._make_ev(["IMPRESSION: ______\n---\nAcute fracture noted"])
        result = _extract_primary_injuries(ev)
        # Fracture should survive, delimiters should not
        if result != _NOT_DOCUMENTED:
            assert "____" not in result
            assert "---" not in result

    def test_numbering_cleaned(self):
        """Leading '1. ' numbering is stripped from output."""
        ev = self._make_ev(["IMPRESSION: 1. Acute rib fracture"])
        result = _extract_primary_injuries(ev)
        assert not result.startswith("1.")

    def test_study_deduplication(self):
        """Duplicate study texts (by first 100 chars) are skipped."""
        same_text = "IMPRESSION: Acute fracture of the pelvis" + " " * 100
        ev = self._make_ev([same_text, same_text])
        result = _extract_primary_injuries(ev)
        parts = result.split("; ")
        assert len(parts) == 1

    def test_within_normal_limits_filtered(self):
        ev = self._make_ev(["IMPRESSION: Within normal limits"])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_vague_references_filtered(self):
        ev = self._make_ev(["IMPRESSION: Chronic changes as above"])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_tube_placement_filtered_without_acute(self):
        """Central line/tube placement notes filtered when no acute keyword."""
        ev = self._make_ev(["IMPRESSION: Central line tip projects over the SVC"])
        result = _extract_primary_injuries(ev)
        assert result == _NOT_DOCUMENTED

    def test_contusion_extracted(self):
        ev = self._make_ev(["IMPRESSION: Pulmonary contusion right lower lobe"])
        result = _extract_primary_injuries(ev)
        assert "contusion" in result.lower()

    def test_hematoma_extracted(self):
        ev = self._make_ev(["IMPRESSION: Epidural hematoma right temporal region"])
        result = _extract_primary_injuries(ev)
        assert "hematoma" in result.lower()

    def test_laceration_extracted(self):
        ev = self._make_ev(["IMPRESSION: Hepatic laceration grade III"])
        result = _extract_primary_injuries(ev)
        assert "laceration" in result.lower()

    def test_injury_capped_at_200_chars(self):
        """Each individual injury is capped at 200 characters."""
        long_text = "Fracture " + "x" * 300
        ev = self._make_ev([f"IMPRESSION: {long_text}"])
        result = _extract_primary_injuries(ev)
        if result != _NOT_DOCUMENTED:
            for inj in result.split("; "):
                assert len(inj) <= 200


# ═════════════════════════════════════════════════════════════════════
# is_historical_reference tests  (evidence_utils)
# ═════════════════════════════════════════════════════════════════════

class TestIsHistoricalReference:
    """Lock in historical reference detection."""

    def test_history_of(self):
        assert is_historical_reference("history of diabetes") is True

    def test_past_medical_history(self):
        assert is_historical_reference("past medical history includes HTN") is True

    def test_pmh(self):
        assert is_historical_reference("pmh: DM2") is True

    def test_previous(self):
        assert is_historical_reference("previously treated fracture") is True

    def test_prior_to_admission(self):
        assert is_historical_reference("prior to admission patient was on Coumadin") is True

    def test_time_ago(self):
        assert is_historical_reference("fracture 3 months ago") is True
        assert is_historical_reference("surgery 2 years ago") is True

    def test_old_fracture(self):
        assert is_historical_reference("old fracture of the pelvis") is True

    def test_healed_fracture(self):
        assert is_historical_reference("healed fracture right humerus") is True

    def test_remote_history(self):
        assert is_historical_reference("remote history of TBI") is True

    def test_current_admission_not_historical(self):
        assert is_historical_reference("acute rib fracture") is False

    def test_plain_finding(self):
        assert is_historical_reference("subdural hematoma") is False

    def test_empty(self):
        assert is_historical_reference("") is False

    def test_none(self):
        assert is_historical_reference(None) is False


# ═════════════════════════════════════════════════════════════════════
# extract_injuries_from_imaging tests  (evidence_utils)
# ═════════════════════════════════════════════════════════════════════

class TestExtractInjuriesFromImaging:
    """Lock in imaging injury extraction based on keywords."""

    def test_fracture_detected(self):
        text = "IMPRESSION: Acute rib fracture"
        result = extract_injuries_from_imaging(text)
        assert any("fracture" in r.lower() for r in result)

    def test_hemorrhage_detected(self):
        text = "IMPRESSION: Subdural hemorrhage"
        result = extract_injuries_from_imaging(text)
        assert any("hemorrhage" in r.lower() for r in result)

    def test_no_injury_keyword_empty(self):
        text = "IMPRESSION: Normal study"
        result = extract_injuries_from_imaging(text)
        assert result == []

    def test_empty_text(self):
        assert extract_injuries_from_imaging("") == []

    def test_none_text(self):
        assert extract_injuries_from_imaging(None) == []

    def test_pneumothorax(self):
        text = "FINDINGS: Small left pneumothorax"
        result = extract_injuries_from_imaging(text)
        assert any("pneumothorax" in r.lower() for r in result)

    def test_multiple_keywords(self):
        text = (
            "IMPRESSION:\n"
            "Rib fractures bilateral\n"
            "Small pneumothorax left\n"
            "Normal heart size"
        )
        result = extract_injuries_from_imaging(text)
        assert len(result) >= 2

    def test_contusion_detected(self):
        text = "IMPRESSION: Pulmonary contusion"
        result = extract_injuries_from_imaging(text)
        assert any("contusion" in r.lower() for r in result)

    def test_dissection_detected(self):
        text = "IMPRESSION: Carotid dissection"
        result = extract_injuries_from_imaging(text)
        assert any("dissection" in r.lower() for r in result)


# ═════════════════════════════════════════════════════════════════════
# extract_injuries_from_impression tests  (evidence_utils)
# ═════════════════════════════════════════════════════════════════════

class TestExtractInjuriesFromImpression:
    """Lock in impression injury extraction with historical reference filtering."""

    def test_acute_fracture_extracted(self):
        result = extract_injuries_from_impression("Acute rib fracture right side")
        assert any("fracture" in r.lower() for r in result)

    def test_historical_filtered(self):
        text = "History of old fracture\nAcute new fracture found"
        result = extract_injuries_from_impression(text)
        # Historical line should be filtered, acute should survive
        assert any("Acute" in r or "fracture" in r.lower() for r in result)
        assert not any("History of" in r for r in result)

    def test_bullet_cleanup(self):
        """Leading bullets/dashes are cleaned."""
        text = "- Acute rib fracture\n• Pneumothorax"
        result = extract_injuries_from_impression(text)
        for r in result:
            assert not r.startswith("-")
            assert not r.startswith("•")

    def test_demographic_line_skipped(self):
        """Lines like '65 yo male' are skipped."""
        text = "65 yo male with trauma\nAcute rib fracture"
        result = extract_injuries_from_impression(text)
        assert not any("65 yo" in r for r in result)

    def test_empty_text(self):
        assert extract_injuries_from_impression("") == []

    def test_none_text(self):
        assert extract_injuries_from_impression(None) == []

    def test_abbreviation_keywords(self):
        """Abbreviated injury names (sah, sdh, edh, ich) are recognized."""
        text = "Small SAH noted\nSDH right temporal"
        result = extract_injuries_from_impression(text)
        assert len(result) >= 2

    def test_fx_abbreviation(self):
        text = "C2 fx"
        result = extract_injuries_from_impression(text)
        assert any("fx" in r.lower() for r in result)

    def test_no_injury_keywords(self):
        text = "Normal study\nNo acute findings"
        result = extract_injuries_from_impression(text)
        assert result == []

    def test_traumatic_keyword(self):
        text = "Traumatic brain injury"
        result = extract_injuries_from_impression(text)
        assert len(result) >= 1

    def test_minimum_length_filter(self):
        """Lines with cleaned content <= 2 chars are skipped."""
        text = "fx"  # "fx" → after cleanup still "fx" which is 2 chars, should be skipped
        result = extract_injuries_from_impression(text)
        assert result == []

    def test_spinal_cord_injury(self):
        text = "Spinal cord injury at T12"
        result = extract_injuries_from_impression(text)
        assert any("spinal cord" in r.lower() for r in result)
