"""Local macOS speech synthesis for AILY, including pt-BR Luciana."""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult


@TTSRegistry.register("macos_tts")
class MacOSTTSBackend(TTSBackend):
    backend_id = "macos_tts"

    def health(self) -> bool:
        return (
            platform.system() == "Darwin"
            and bool(shutil.which("say"))
            and bool(shutil.which("afconvert"))
        )

    def available_voices(self) -> list[str]:
        if not self.health():
            return []
        output = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, check=True, timeout=10
        ).stdout
        return [line.split()[0] for line in output.splitlines() if line.strip()]

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "Luciana",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        if not self.health():
            raise RuntimeError("macOS say/afconvert indisponíveis")
        if output_format != "wav":
            raise ValueError("macos_tts suporta apenas WAV")
        if not text.strip():
            raise ValueError("Texto vazio")
        voice = voice_id or "Luciana"
        if voice not in self.available_voices():
            raise ValueError(f"Voz macOS indisponível: {voice}")
        rate = max(80, min(450, round(175 * speed)))
        with tempfile.TemporaryDirectory(prefix="aily-tts-") as work:
            aiff = Path(work) / "speech.aiff"
            wav = Path(work) / "speech.wav"
            subprocess.run(
                ["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text],
                check=True,
                timeout=120,
                capture_output=True,
            )
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@24000", str(aiff), str(wav)],
                check=True,
                timeout=30,
                capture_output=True,
            )
            audio = wav.read_bytes()
        return TTSResult(audio=audio, format="wav", voice_id=voice, sample_rate=24000)
