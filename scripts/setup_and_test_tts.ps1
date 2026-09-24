#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Setup & Test TTS Service (Meeting AI Assistant)
    Download Piper model + build Docker + test /synthesize API
    Luu audio output ra file WAV de kiem tra
#>

$ErrorActionPreference = "Stop"
$ROOT_DIR    = Split-Path -Parent $PSScriptRoot
$MODELS_DIR  = Join-Path $ROOT_DIR "models-cache\piper"
$VOICE       = "vi_VN-vais1000-medium"
$HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium"
$TTS_PORT    = 8003
$OUTPUT_WAV  = Join-Path $ROOT_DIR "test_tts_output.wav"

Write-Host ""
Write-Host "Meetting AI - TTS Setup & Test" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor DarkGray

# STEP 1: Download Piper model
Write-Host ""
Write-Host "[1/4] Checking Piper TTS model..." -ForegroundColor Yellow

$onnxFile   = Join-Path $MODELS_DIR "$VOICE.onnx"
$configFile = Join-Path $MODELS_DIR "$VOICE.onnx.json"

if (-not (Test-Path $MODELS_DIR)) {
    New-Item -ItemType Directory -Force -Path $MODELS_DIR | Out-Null
    Write-Host "    Created: $MODELS_DIR" -ForegroundColor DarkGray
}

if (-not (Test-Path $onnxFile)) {
    Write-Host "    Downloading $VOICE.onnx (~63 MB)..." -ForegroundColor Cyan
    curl.exe -L --retry 3 --retry-delay 5 -o $onnxFile "$HF_BASE/$VOICE.onnx"
    Write-Host "    OK Downloaded .onnx" -ForegroundColor Green
} else {
    Write-Host "    OK .onnx already exists" -ForegroundColor Green
}

if (-not (Test-Path $configFile)) {
    Write-Host "    Downloading $VOICE.onnx.json..." -ForegroundColor Cyan
    curl.exe -L --retry 3 --retry-delay 5 -o $configFile "$HF_BASE/$VOICE.onnx.json"
    Write-Host "    OK Downloaded .json config" -ForegroundColor Green
} else {
    Write-Host "    OK .json config already exists" -ForegroundColor Green
}

# STEP 2: Build TTS Docker image
Write-Host ""
Write-Host "[2/4] Building TTS Docker image..." -ForegroundColor Yellow
Set-Location $ROOT_DIR
docker build -t meeting-tts-service:local ./services/tts-service
if ($LASTEXITCODE -ne 0) { throw "Docker build failed!" }
Write-Host "    OK Image built: meeting-tts-service:local" -ForegroundColor Green

# STEP 3: Run TTS container
Write-Host ""
Write-Host "[3/4] Starting TTS container..." -ForegroundColor Yellow

$existing = docker ps -aq --filter "name=meeting-piper-test" 2>$null
if ($existing) {
    docker rm -f meeting-piper-test | Out-Null
    Write-Host "    Removed existing container" -ForegroundColor DarkGray
}

$containerVolume = "${MODELS_DIR}:/models/piper"
docker run -d `
    --name meeting-piper-test `
    -p "${TTS_PORT}:8003" `
    -v "${containerVolume}" `
    -e "PIPER_VOICE=$VOICE" `
    -e "MODEL_CACHE_DIR=/models/piper" `
    -e "SAMPLE_RATE=22050" `
    meeting-tts-service:local

if ($LASTEXITCODE -ne 0) { throw "Docker run failed!" }
Write-Host "    OK Container started: meeting-piper-test" -ForegroundColor Green

# Wait for service to be ready
Write-Host "    Waiting for service to be ready..." -ForegroundColor DarkGray
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:${TTS_PORT}/health" -Method GET -TimeoutSec 3
        if ($health.status -eq "ok") {
            $ready = $true
            Write-Host "    OK Service ready! Voice: $($health.voice)" -ForegroundColor Green
            break
        }
    } catch {
        Write-Host "    ... ($([int]($i*2))s)" -ForegroundColor DarkGray
    }
}
if (-not $ready) { throw "Service did not start in time. Check: docker logs meeting-piper-test" }

# STEP 4: Test /synthesize
Write-Host ""
Write-Host "[4/4] Testing /synthesize API..." -ForegroundColor Yellow

$testTexts = @(
    "Xin chao, cuoc hop bat dau.",
    "He thong tro ly cuoc hop da san sang.",
    "Phien dich tieng Nhat sang tieng Viet thanh cong."
)

$allPassed = $true
foreach ($text in $testTexts) {
    Write-Host ""
    Write-Host "    Input: $text" -ForegroundColor White
    $body = @{ text = $text; speed = 1.0 } | ConvertTo-Json
    try {
        $resp = Invoke-RestMethod `
            -Uri "http://localhost:${TTS_PORT}/synthesize" `
            -Method POST `
            -ContentType "application/json" `
            -Body $body `
            -TimeoutSec 30

        $audioBytes = [System.Convert]::FromBase64String($resp.audio_b64)
        Write-Host "    Audio size : $($audioBytes.Length.ToString('N0')) bytes" -ForegroundColor Cyan
        Write-Host "    Sample rate: $($resp.sample_rate) Hz" -ForegroundColor Cyan
        Write-Host "    Latency    : $([math]::Round($resp.latency_ms, 0)) ms" -ForegroundColor Cyan

        if ($audioBytes.Length -gt 1000) {
            Write-Host "    PASS" -ForegroundColor Green
            [System.IO.File]::WriteAllBytes($OUTPUT_WAV, $audioBytes)
        } else {
            Write-Host "    FAIL - audio too short" -ForegroundColor Red
            $allPassed = $false
        }
    } catch {
        Write-Host "    ERROR: $_" -ForegroundColor Red
        $allPassed = $false
    }
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor DarkGray
if ($allPassed) {
    Write-Host "ALL TESTS PASSED!" -ForegroundColor Green
} else {
    Write-Host "SOME TESTS FAILED - check logs above" -ForegroundColor Red
}
Write-Host "Audio saved to: $OUTPUT_WAV" -ForegroundColor Cyan
Write-Host "Open with Windows Media Player to listen."
Write-Host ""
Write-Host "Container still running at: http://localhost:${TTS_PORT}"
Write-Host "To stop: docker rm -f meeting-piper-test"
Write-Host ""
