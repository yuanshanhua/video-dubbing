#!/bin/bash

# 对传入的文件执行命令
# 用法: ./process_files.sh file1 file2 ...

set -e

# 显示帮助信息
show_help() {
    echo "用法: $0 file1 [file2 ...]"
    echo "示例: $0 *.txt"
    echo "     $0 *.mp3"
    echo
    echo "说明: 对每个指定的文件执行硬编码命令"
}

# 参数检查
if [ $# -lt 1 ]; then
    echo "错误: 缺少必要参数"
    show_help
    exit 1
fi

# 修改此函数以设置命令
process_file() {
    local file=$1
    echo "正在处理文件: $file"
    
    cat "$file" | wc -l
}

# 检查是否有匹配的文件
files_found=0

echo "正在处理传入的文件..."

# 遍历所有传入的文件参数
for file in "$@"; do
    # 检查文件是否存在
    if [ -f "$file" ]; then
        files_found=1
        
        # 调用处理函数
        process_file "$file"
        
        if [ $? -eq 0 ]; then
            echo "命令执行成功: $file"
        else
            echo "警告: 命令执行失败: $file"
        fi
    else
        echo "警告: 文件不存在: $file"
    fi
done

# 检查是否找到了匹配的文件
if [ $files_found -eq 0 ]; then
    echo "警告: 没有找到可处理的文件"
    exit 2
fi

echo "所有文件处理完成"
