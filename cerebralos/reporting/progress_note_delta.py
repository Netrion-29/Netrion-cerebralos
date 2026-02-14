#!/usr/bin/env python3
"""
Progress note delta extractor.

Identifies what CHANGED day-to-day in progress notes by comparing against
previous day's content. Epic copies forward large amounts of text, so
detecting new sentences/sections is critical for clinical review.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime
from difflib import SequenceMatcher


def _normalize_sentence(sentence: str) -> str:
    """
    Normalize sentence for comparison (lowercase, strip whitespace).

    Returns normalized string.
    """
    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', sentence.strip())
    # Lowercase for comparison
    return normalized.lower()


def _extract_sentences(text: str) -> List[str]:
    """
    Extract sentences from clinical note text.

    Returns list of sentences.
    """
    # Split on periods, question marks, exclamation points followed by space or newline
    # But preserve decimal numbers (e.g., "1.5", "3.2")
    sentences = re.split(r'(?<!\d)\.(?!\d)\s+|[!?]\s+|\n{2,}', text)

    # Clean and filter
    cleaned = []
    for s in sentences:
        s = s.strip()
        if len(s) > 10:  # Skip very short fragments
            cleaned.append(s)

    return cleaned


def _is_similar(text1: str, text2: str, threshold: float = 0.85) -> bool:
    """
    Check if two text strings are highly similar (likely copied forward).

    Uses sequence matching to detect minor edits.
    """
    matcher = SequenceMatcher(None, text1.lower(), text2.lower())
    return matcher.ratio() > threshold


def extract_note_deltas(evaluation: Dict) -> List[Dict[str, Any]]:
    """
    Extract progress note deltas showing what CHANGED each day.

    Returns list of daily delta records with:
    - date: Date string
    - new_content: List of new sentences/sections not seen in prior days
    - modified_content: List of sentences that were edited from prior versions
    - prior_note_count: How many prior notes this was compared against
    """
    # Collect all physician notes sorted by date
    physician_notes = []

    for snippet in evaluation.get("all_evidence_snippets", []):
        if snippet.get("source_type") not in ("PHYSICIAN_NOTE", "PROGRESS_NOTE"):
            continue

        timestamp = snippet.get("timestamp", "")
        text = snippet.get("text", "")

        if not text or len(text) < 50:
            continue

        # Parse date from timestamp
        try:
            date_obj = datetime.strptime(timestamp.split()[0], "%Y-%m-%d")
            date_str = date_obj.strftime("%Y-%m-%d")
        except:
            continue

        physician_notes.append({
            "date": date_str,
            "timestamp": timestamp,
            "text": text,
        })

    # Sort by timestamp
    physician_notes.sort(key=lambda n: n["timestamp"])

    # Group by date
    notes_by_date: Dict[str, List[Dict]] = {}
    for note in physician_notes:
        date = note["date"]
        if date not in notes_by_date:
            notes_by_date[date] = []
        notes_by_date[date].append(note)

    # Process each day to find deltas
    deltas = []
    all_prior_sentences: Set[str] = set()

    for date in sorted(notes_by_date.keys()):
        daily_notes = notes_by_date[date]

        # Extract all sentences from today's notes
        today_sentences = []
        for note in daily_notes:
            sentences = _extract_sentences(note["text"])
            today_sentences.extend(sentences)

        # Find new content (not seen in any prior day)
        new_content = []
        modified_content = []

        for sentence in today_sentences:
            normalized = _normalize_sentence(sentence)

            # Check if this exact sentence appeared before
            if normalized in all_prior_sentences:
                continue  # Skip copied-forward content

            # Check if this is a MODIFICATION of a prior sentence
            is_modification = False
            for prior in all_prior_sentences:
                if _is_similar(normalized, prior, threshold=0.85):
                    # This is an edited version of prior content
                    modified_content.append(sentence)
                    is_modification = True
                    break

            if not is_modification:
                # This is genuinely new content
                new_content.append(sentence)

        # Record delta
        if new_content or modified_content:
            deltas.append({
                "date": date,
                "new_content": new_content[:10],  # Limit to first 10 new items
                "modified_content": modified_content[:5],  # Limit to first 5 modifications
                "prior_note_count": len(all_prior_sentences),
                "total_sentences_today": len(today_sentences),
            })

        # Add today's normalized sentences to prior set for next day's comparison
        for sentence in today_sentences:
            normalized = _normalize_sentence(sentence)
            all_prior_sentences.add(normalized)

    return deltas


def format_note_deltas_report(deltas: List[Dict[str, Any]]) -> str:
    """
    Format note deltas as human-readable report showing what changed each day.

    Returns formatted text.
    """
    if not deltas:
        return "No progress note changes detected (or only single day of notes)."

    lines = []
    lines.append("📝 PROGRESS NOTE CHANGES (Day-to-Day)")
    lines.append("")
    lines.append("Showing NEW content only (copied-forward text filtered out)")
    lines.append("")

    for delta in deltas:
        date = delta["date"]
        new = delta.get("new_content", [])
        modified = delta.get("modified_content", [])

        if not new and not modified:
            continue

        lines.append(f"📅 {date}")
        lines.append("")

        if new:
            lines.append("  ✨ New content:")
            for content in new[:8]:  # Show first 8 new items
                # Truncate long sentences
                display = content[:200]
                if len(content) > 200:
                    display += "..."
                lines.append(f"    • {display}")

            if len(new) > 8:
                lines.append(f"    ... and {len(new) - 8} more new items")
            lines.append("")

        if modified:
            lines.append("  ✏️  Modified content:")
            for content in modified[:5]:
                display = content[:150]
                if len(content) > 150:
                    display += "..."
                lines.append(f"    • {display}")
            lines.append("")

        lines.append("")

    return "\n".join(lines)
