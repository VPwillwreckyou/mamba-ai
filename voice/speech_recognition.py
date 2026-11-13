"""Speech-to-Text (STT) implementation for MAMBA AI."""
from __future__ import annotations

import logging

import speech_recognition as sr

logger = logging.getLogger(__name__)

class SpeechRecognizer:
    """
    Converts spoken audio from the microphone into text.
    Supports English, Russian, and Armenian.
    """

    def __init__(self, language: str = "en-US") -> None:
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.language = language

    def set_language(self, language: str) -> None:
        """
        Set the recognition language.
        Examples: "en-US", "ru-RU", "hy-AM"
        """
        self.language = language
        logger.info(f"STT language set to {language}")

    def listen(self, timeout: float = 5.0, phrase_time_limit: float = 10.0) -> str | None:
        """
        Listen for a single phrase and transcribe it.
        Returns the transcription or None if it failed.
        """
        try:
            with self.microphone as source:
                # Adjust for ambient noise
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                logger.info("Listening...")
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)

            # Using Google Web Speech API for MVP (free, no key required for low volume)
            text = self.recognizer.recognize_google(audio, language=self.language)
            logger.info(f"Transcribed: {text}")
            return text
        except sr.WaitTimeoutError:
            logger.warning("Listening timed out (no speech detected)")
        except sr.UnknownValueError:
            logger.warning("Speech was unintelligible")
        except sr.RequestError as e:
            logger.error(f"STT API request error: {e}")
        except Exception as e:
            logger.error(f"Unexpected STT error: {e}")

        return None
