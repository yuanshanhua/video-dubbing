<#
.DESCRIPTION
    使用FFmpeg将音频文件作为音轨添加到视频文件.
.PARAMETER VideoPath
    输入视频文件的路径，支持 glob 模式（如 "*.mp4"）。当匹配多个视频时，将忽略 AudioPath 和 OutputPath 参数。
.PARAMETER AudioPath
    要添加的音频文件的路径（当 VideoPath 匹配单个文件时使用）
.PARAMETER OutputPath
    输出视频文件的路径, 如不指定, 则创建同名文件, 带有后缀 -with-audio.
.PARAMETER Help
    显示帮助信息
.EXAMPLE
    .\Add-Audio.ps1 -VideoPath "d:\videos\input.mp4" -AudioPath "d:\audio\music.mp3"

.EXAMPLE
    .\Add-Audio.ps1 -VideoPath "d:\videos\input.mp4" -AudioPath "d:\audio\music.mp3" -OutputPath "d:\output\final.mp4"

.EXAMPLE
    .\Add-Audio.ps1 -VideoPath "d:\videos\*.mp4"
    
.NOTES
    需要已安装FFmpeg并添加到系统路径中
#>

param (
    [Parameter(Mandatory = $false, Position = 0)]
    [string]$VideoPath,
    
    [Parameter(Mandatory = $false, Position = 1)]
    [string]$AudioPath,
    
    [Parameter(Mandatory = $false)]
    [string]$OutputPath,

    [Parameter(Mandatory = $false)]
    [Alias("h")]
    [switch]$Help
)

# 显示帮助信息
if ($Help) {
    Get-Help $MyInvocation.MyCommand.Definition -Detailed
    exit 0
}

# 检查FFmpeg是否可用
try {
    $null = Get-Command ffmpeg -ErrorAction Stop
}
catch {
    Write-Error "找不到ffmpeg. 请确保ffmpeg已安装并添加到系统PATH中."
    exit 1
}

# 定义处理单个视频的函数
function Convert-SingleVideo {
    param (
        [string]$VideoFile,
        [string]$AudioFile,
        [string]$OutputFile
    )
    
    # 构建FFmpeg命令
    $ffmpegCommand = "ffmpeg -i `"$VideoFile`" -i `"$AudioFile`" -map 0 -map 1:a -c copy `"$OutputFile`""
    
    Write-Host "开始处理: 将 '$AudioFile' 添加到 '$VideoFile'" -ForegroundColor Yellow
    
    try {
        # 执行FFmpeg命令
        Invoke-Expression $ffmpegCommand
        
        # 验证输出文件是否已创建
        if (Test-Path $OutputFile) {
            Write-Host "处理完成！输出文件已保存为: $OutputFile" -ForegroundColor Green
            return $true
        }
        else {
            Write-Error "处理完成, 但未找到输出文件。可能在处理过程中出现了错误。"
            return $false
        }
    }
    catch {
        Write-Error "处理视频时出错: $_"
        return $false
    }
}

# 获取匹配的视频文件
$videoFiles = @(Get-Item -Path $VideoPath -ErrorAction SilentlyContinue)

# 如果路径包含通配符但没有直接匹配，尝试使用 Resolve-Path
if ($videoFiles.Count -eq 0 -and ($VideoPath -match '\*' -or $VideoPath -match '\?')) {
    $resolvedPaths = @(Resolve-Path -Path $VideoPath -ErrorAction SilentlyContinue)
    if ($resolvedPaths.Count -gt 0) {
        $videoFiles = @($resolvedPaths | ForEach-Object { Get-Item -Path $_.Path })
    }
}

# 如果仍未匹配到文件，但路径包含通配符，尝试使用目录+模式的方式
if ($videoFiles.Count -eq 0 -and ($VideoPath -match '\*' -or $VideoPath -match '\?')) {
    $directory = Split-Path -Parent $VideoPath
    $pattern = Split-Path -Leaf $VideoPath
    
    if ($directory -eq "") {
        $directory = "."
    }
    
    if (Test-Path -Path $directory -PathType Container) {
        $videoFiles = @(Get-ChildItem -Path $directory -Filter $pattern)
    }
}

# 如果匹配到多个视频文件
if ($videoFiles.Count -gt 1) {
    Write-Host "找到 $($videoFiles.Count) 个视频文件，将为每个视频查找对应的音频文件..." -ForegroundColor Yellow
    
    $processedCount = 0
    $successCount = 0
    
    foreach ($videoFile in $videoFiles) {
        $processedCount++
        Write-Host "处理 $processedCount / $($videoFiles.Count): $($videoFile.Name)" -ForegroundColor Cyan
        
        $videoDirectory = $videoFile.DirectoryName
        $videoBaseName = [System.IO.Path]::GetFileNameWithoutExtension($videoFile.Name)
        
        # 查找可能的音频文件（支持常见音频格式）
        $audioExtensions = @('.mp3', '.wav', '.aac', '.flac', '.ogg', '.m4a')
        $audioFile = $null
        
        foreach ($ext in $audioExtensions) {
            $possibleAudioPath = Join-Path -Path $videoDirectory -ChildPath "$videoBaseName$ext"
            if (Test-Path $possibleAudioPath) {
                $audioFile = $possibleAudioPath
                break
            }
        }
        
        if ($audioFile) {
            $outputFile = Join-Path -Path $videoDirectory -ChildPath "$videoBaseName-with-audio$($videoFile.Extension)"
            Write-Host "找到匹配的音频文件: $audioFile" -ForegroundColor Green
            
            $success = Convert-SingleVideo -VideoFile $videoFile.FullName -AudioFile $audioFile -OutputFile $outputFile
            if ($success) {
                $successCount++
            }
        }
        else {
            Write-Warning "无法找到 '$($videoFile.Name)' 对应的音频文件，跳过处理。"
        }
    }
    
    Write-Host "批量处理完成: 成功处理 $successCount / $processedCount 个文件" -ForegroundColor Green
}
else {
    # 单个文件处理逻辑
    if ($videoFiles.Count -eq 1) {
        $VideoPath = $videoFiles[0].FullName
    }
    
    # 检查必要参数
    if (-not $VideoPath -or -not (Test-Path $VideoPath)) {
        Write-Error "视频文件不存在或未指定: $VideoPath"
        exit 1
    }
    
    if (-not $AudioPath -or -not (Test-Path $AudioPath)) {
        Write-Error "音频文件不存在或未指定: $AudioPath"
        exit 1
    }
    
    # 如果未指定输出路径, 则创建默认输出路径
    if (-not $OutputPath) {
        $directory = Split-Path -Parent $VideoPath
        $fileName = [System.IO.Path]::GetFileNameWithoutExtension($VideoPath)
        $extension = [System.IO.Path]::GetExtension($VideoPath)
        $OutputPath = Join-Path -Path $directory -ChildPath "$fileName-with-audio$extension"
    }
    
    Convert-SingleVideo -VideoFile $VideoPath -AudioFile $AudioPath -OutputFile $OutputPath
}
