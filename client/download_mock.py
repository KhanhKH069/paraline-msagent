import urllib.request

url = "https://raw.githubusercontent.com/mdn/webaudio-examples/main/audio-analyser/viper.ogg"
# Actually, I need a WAV file so we don't have to parse ogg
url = "https://www2.cs.uic.edu/~i101/SoundFiles/preamble.wav" # English speech: "We the people of the United States..."
out_path = r"c:\Users\Admin\paraline-msagent\client\mock_en.wav"

print(f"Downloading from {url}...")
urllib.request.urlretrieve(url, out_path)
print(f"Downloaded successfully to {out_path}")
