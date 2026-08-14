import json
import os
import re
from typing import Dict, Any, Optional

import requests


class IntentService:
    def __init__(self, api_key: Optional[str], model: Optional[str] = None) -> None:
        if api_key:
            # Remove any accidental whitespace/newlines that break HTTP headers
            self.api_key = ''.join(api_key.split())
        else:
            self.api_key = None
        self.model = model or os.getenv("OPENROUTER_INTENT_MODEL", "openai/gpt-4o-mini")
        self.endpoint = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1/chat/completions")

    def parse_intent(self, artist: str, intent: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        filters = filters or {}
        if not intent:
            return self._fallback(artist, intent, filters, note="Empty intent")
        if not self.api_key:
            return self._fallback(artist, intent, filters, note="OpenRouter API key missing")
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You convert natural language intents into structured search filters for The MLC API. "
                            "Always return strict JSON with keys: recordings, songcode, chips, summary, warnings. "
                            "recordings: { titleFragments: string[], isrc: string|null }. "
                            "songcode: { titleFragments: string[], writerLastNames: string[], publisher: string|null, years: number[]|null }. "
                            "chips: array of short human-friendly suggestions (<=4). "
                            "summary: short sentence summarising the plan. "
                            "warnings: array of strings, can be empty."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Artist: {artist}\n"
                            f"Existing filters: {filters}\n"
                            f"Intent: {intent}\n"
                            "Respond with JSON only."
                        ),
                    },
                ],
                "temperature": 0.2,
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            response = requests.post(self.endpoint, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not text:
                return self._fallback(artist, intent, filters, note="No content from model")
            # Extract JSON (model might wrap in markdown)
            json_text = text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                json_text = match.group(0)
            parsed = json.loads(json_text)
            return self._normalise(parsed)
        except Exception as exc:
            return self._fallback(artist, intent, filters, note=str(exc))

    def _normalise(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        def list_of_str(value):
            if not value:
                return []
            if isinstance(value, str):
                return [value]
            return [str(v) for v in value]

        recordings = payload.get("recordings", {})
        songcode = payload.get("songcode", {})
        result = {
            "recordings": {
                "titleFragments": list_of_str(recordings.get("titleFragments")),
                "isrc": recordings.get("isrc"),
            },
            "songcode": {
                "titleFragments": list_of_str(songcode.get("titleFragments")),
                "writerLastNames": list_of_str(songcode.get("writerLastNames")),
                "publisher": songcode.get("publisher"),
                "years": songcode.get("years") if isinstance(songcode.get("years"), list) else None,
            },
            "chips": list_of_str(payload.get("chips")),
            "summary": payload.get("summary", ""),
            "warnings": list_of_str(payload.get("warnings")),
            "fallback": False,
        }
        return result

    def _fallback(self, artist: str, intent: str, filters: Dict[str, Any], note: str) -> Dict[str, Any]:
        intent_lower = (intent or "").lower()
        title_fragments = []
        writer_last_names = []
        publisher = None
        years = []

        # crude heuristics: look for quoted strings and year numbers
        quoted = re.findall(r'"([^"]+)"', intent_lower)
        if quoted:
            title_fragments.extend(quoted)
        if not title_fragments and intent_lower:
            tokens = [t.strip() for t in re.split(r"[,;]", intent_lower) if t.strip()]
            if tokens:
                title_fragments.append(tokens[0])
        # Use last word of artist for writer by default
        parts = [p for p in artist.split() if p]
        if parts:
            writer_last_names.append(parts[-1])
        # Year detection
        for match in re.findall(r"(19|20)\d{2}", intent_lower):
            try:
                years.append(int(match))
            except ValueError:
                pass
        result = {
            "recordings": {
                "titleFragments": title_fragments[:2],
                "isrc": None,
            },
            "songcode": {
                "titleFragments": title_fragments[:2],
                "writerLastNames": writer_last_names,
                "publisher": publisher,
                "years": years or None,
            },
            "chips": ["Latest releases", "Un-edited works"],
            "summary": note or "Heuristic filters applied",
            "warnings": ["AI intent service unavailable"] if note else [],
            "fallback": True,
        }
        return result
