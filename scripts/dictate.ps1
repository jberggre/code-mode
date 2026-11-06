<#
    dictate.ps1 - offline speech to text with the Windows speech engine (SAPI).

    Nothing to download and nothing phoning home: this is the recogniser that
    already ships with Windows. It listens for one utterance, stops when you
    pause, and prints the recognised text on stdout.

    Accuracy is dictation-grade, not Whisper-grade. Good enough for "add a null
    check before the parse", not for dictating identifiers.

    Usage:
        powershell -ExecutionPolicy Bypass -File scripts\dictate.ps1
        powershell -ExecutionPolicy Bypass -File scripts\dictate.ps1 -MaxSeconds 8
        powershell -ExecutionPolicy Bypass -File scripts\dictate.ps1 -Culture en-GB

    Exit codes: 0 text on stdout, 1 mic/engine error, 2 speech not installed,
                3 nothing recognised.
#>
[CmdletBinding()]
param(
    [int]$MaxSeconds = 20,
    [string]$Culture = ''
)

$ErrorActionPreference = 'Stop'

try {
    Add-Type -AssemblyName System.Speech
} catch {
    [Console]::Error.WriteLine(
        "Windows speech assemblies are unavailable. Enable Settings > Apps > Optional features > Speech.")
    exit 2
}

$engine = $null
try {
    if ($Culture) {
        $info = New-Object System.Globalization.CultureInfo($Culture)
        $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($info)
    } else {
        $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    }

    $engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)) | Out-Null
    $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds($MaxSeconds)
    $engine.BabbleTimeout = [TimeSpan]::FromSeconds($MaxSeconds)
    $engine.EndSilenceTimeout = [TimeSpan]::FromMilliseconds(1200)
    $engine.SetInputToDefaultAudioDevice()

    $result = $engine.Recognize()
    if ($null -eq $result) {
        [Console]::Error.WriteLine("nothing recognised - check the microphone is the default input")
        exit 3
    }
    Write-Output $result.Text.Trim()
    exit 0
} catch {
    [Console]::Error.WriteLine("mic/speech error: " + $_.Exception.Message)
    exit 1
} finally {
    if ($engine) { $engine.Dispose() }
}
