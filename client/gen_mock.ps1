Add-Type -AssemblyName System.Speech
$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speak.Rate = -1
$speak.SetOutputToWaveFile("c:\Users\Admin\paraline-msagent\client\mock_en.wav")
$speak.Speak("Hello recording test. Today we are testing the real time translation system from English to Vietnamese. Here is some more audio to test continuous speech recognition. The quick brown fox jumps over the lazy dog. Thank you for your patience and cooperation.")
$speak.Dispose()
