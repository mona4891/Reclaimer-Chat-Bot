"""Text-to-speech: speaks bot chat lines out loud via Google TTS + pygame."""

import os
import tempfile
import time

import pygame
from gtts import gTTS

from logger_setup import logger


def speak_to_game(text):
    """Generate TTS audio using Google TTS and play it."""
    try:
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_audio.close()

        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(temp_audio.name)

        pygame.mixer.init()
        pygame.mixer.music.load(temp_audio.name)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            time.sleep(0.1)

        pygame.mixer.quit()
        os.unlink(temp_audio.name)

    except Exception as e:
        logger.info(f"[TTS ERROR] {e}")
