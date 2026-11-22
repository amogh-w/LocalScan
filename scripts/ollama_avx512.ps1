# Keeps the installed Ollama off its AVX-512 CPU builds while Windows hides AVX-512 (the CPU still advertises it, so
# Ollama picks those builds and dies with "illegal instruction" 0xc000001d). Renames them to *.dll.disabled-avx512, so
# Ollama falls back to the AVX2 build (alderlake); the GPU (CUDA) is unaffected. An Ollama update brings them back:
# run this again afterwards, then restart Ollama.
#   .\scripts\ollama_avx512.ps1          disable the AVX-512 builds
#   .\scripts\ollama_avx512.ps1 -Undo    restore them (once AVX-512 works again)
param([switch]$Undo)
$lib = "$env:LOCALAPPDATA\Programs\Ollama\lib\ollama"
$variants = "cannonlake", "cascadelake", "cooperlake", "icelake", "sapphirerapids", "skylakex", "zen4"
foreach ($v in $variants) {
    $dll = "$lib\ggml-cpu-$v.dll"
    if ($Undo) {
        if (Test-Path "$dll.disabled-avx512") { Rename-Item "$dll.disabled-avx512" "ggml-cpu-$v.dll" }
    } elseif (Test-Path $dll) {
        Rename-Item $dll "ggml-cpu-$v.dll.disabled-avx512"
    }
}
"CPU builds Ollama can use: " + ((Get-ChildItem $lib -Filter "ggml-cpu-*.dll").Name -replace 'ggml-cpu-|\.dll' -join ', ')
"Restart Ollama for the change to apply."
