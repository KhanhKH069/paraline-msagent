import sys
import os

try:
    import pyttsx3
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyttsx3"])
    import pyttsx3

print("Initializing TTS...")
engine = pyttsx3.init()
engine.setProperty('rate', 130)

# Generate an English test phrase
text = "This is a simulated audio stream from the virtual device. The purpose of this test is to verify the realtime speech-to-text and translation pipeline. Thank you for your cooperation."
out_wav = os.path.join(os.path.dirname(__file__), "mock_en.wav")

if os.path.exists(out_wav):
    os.remove(out_wav)

print(f"Saving to {out_wav}...")
engine.save_to_file(text, out_wav)
engine.runAndWait()

print(f"Generated {out_wav} successfully.")
