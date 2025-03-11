<#
.DESCRIPTION
    使用 ffmpeg 提取视频文件中的音频流并保存为指定格式
.PARAMETER InputPath
    输入文件路径, 支持 glob 模式 (例如: "*.mp4", "videos/*.mkv")
.PARAMETER OutputDir
    可选的输出目录, 默认与源文件相同
.PARAMETER Format
    输出音频格式 (例如: mp3, wav, aac, flac), 默认为 mp3
.PARAMETER Help
    显示帮助信息
.EXAMPLE
    .\Extract-Audio.ps1 -InputPath "D:\Videos\*.mp4"
.EXAMPLE
    .\Extract-Audio.ps1 -InputPath "movies/*.mkv" -OutputDir "D:\Extracted_Audio"
.EXAMPLE
    .\Extract-Audio.ps1 -InputPath "D:\Videos\*.mp4" -Format wav
.EXAMPLE
    .\Extract-Audio.ps1 -Help
#>

param (
    [Parameter(Mandatory = $false, Position = 0)]
    [string]$InputPath,
    
    [Parameter(Mandatory = $false, Position = 1)]
    [string]$OutputDir = "",
    
    [Parameter(Mandatory = $false)]
    [string]$Format = "mp3",
    
    [Parameter(Mandatory = $false)]
    [Alias("h")]
    [switch]$Help
)

# 显示帮助信息
if ($Help) {
    Get-Help $MyInvocation.MyCommand.Definition -Detailed
    exit 0
}

# 检查必要参数
if ([string]::IsNullOrEmpty($InputPath)) {
    Write-Output "使用 -Help/-h 查看用法"
    exit 1
}

# 检测 ffmpeg
try {
    $null = ffmpeg -version
}
catch {
    Write-Error "找不到ffmpeg. 请确保ffmpeg已安装并添加到系统PATH中."
    exit 1
}

# 获取匹配的文件列表
$files = Get-ChildItem -Path $InputPath

if ($files.Count -eq 0) {
    Write-Warning "没有找到匹配的文件: $InputPath"
    exit 0
}

Write-Host "找到 $($files.Count) 个文件需要处理..." -ForegroundColor Cyan
Write-Host "输出格式: $Format" -ForegroundColor Cyan

foreach ($file in $files) {
    # 跳过非视频文件
    $videoExtensions = @(".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts")
    if ($videoExtensions -notcontains $file.Extension.ToLower()) {
        Write-Host "跳过非视频文件: $($file.Name)" -ForegroundColor Yellow
        continue
    }
    
    # 确定输出文件路径
    if ($OutputDir -ne "") {
        # 确保输出目录存在
        if (-not (Test-Path -Path $OutputDir -PathType Container)) {
            New-Item -Path $OutputDir -ItemType Directory | Out-Null
        }
        $outputPath = Join-Path -Path $OutputDir -ChildPath "$($file.BaseName).$Format"
    }
    else {
        $outputPath = Join-Path -Path $file.DirectoryName -ChildPath "$($file.BaseName).$Format"
    }
    
    Write-Host "处理: $($file.FullName)" -ForegroundColor Cyan
    Write-Host "输出: $outputPath" -ForegroundColor Cyan
    
    # 调用ffmpeg提取音频
    try {
        ffmpeg -i "$($file.FullName)" -vn -map 0:a "$outputPath" -y
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "完成: $($file.Name) -> $outputPath" -ForegroundColor Green
        }
        else {
            Write-Host "处理失败: $($file.Name), 退出代码: $LASTEXITCODE" -ForegroundColor Red
        }
    }
    catch {
        Write-Error "处理 $($file.Name) 时出错: $_"
    }
}

Write-Host "所有文件处理完成!" -ForegroundColor Green
